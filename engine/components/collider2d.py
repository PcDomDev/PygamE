"""Collider2D: shared base for BoxCollider2D and CircleCollider2D.

Holds everything that doesn't depend on the actual shape: layer/mask,
trigger flag, callback lists, exact float bounds, and the shape-vs-shape
overlap tests. Each subclass only knows how to compute its own bounds from
the transform (`_recompute_bounds`).

Geometry is kept as exact floats (`_l/_t/_r/_b` = left/top/right/bottom in
world space); `rect` is a pygame.Rect *view* of that, rounded, for drawing and
legacy code. Physics never uses the rounded rect - pixel rounding was the root
cause of the old landing jitter.

Events (fired by PhysicsWorld once per physics step):
  - Solid vs solid, when at least one side has a Rigidbody2D:
        on_collision_enter / on_collision_stay / on_collision_exit
  - Anything vs a trigger (`is_trigger=True`, a non-solid sensor):
        on_trigger_enter / on_trigger_stay / on_trigger_exit
Two ways to receive each:
  - append a callback to the collider's list: `cb(collider, other_collider)`
  - or define a method of the same name on any Component of either GameObject
    (Unity style): `on_trigger_enter(self, other)`, `on_collision_enter(self, collision)`.
"""
import math

import pygame

from engine.components.component import Component
from engine.core.debug_manager import DebugManager
from engine.physics.layers import CollisionLayers


def _resolve_mask(mask):
    if isinstance(mask, int):
        return mask & CollisionLayers.ALL
    return CollisionLayers.mask(*mask)


def _circle_box_overlap(cx, cy, radius, box):
    """Circle vs axis-aligned box (a collider): distance to the closest point."""
    closest_x = box._l if cx < box._l else (box._r if cx > box._r else cx)
    closest_y = box._t if cy < box._t else (box._b if cy > box._b else cy)
    dx = cx - closest_x
    dy = cy - closest_y
    return (dx * dx + dy * dy) < (radius * radius)


class Collider2D(Component):
    shape = None                  # "box" or "circle", set by subclasses
    updates_when_static = False   # sync is driven by PhysicsWorld, never per-frame

    def __init__(self, is_trigger=False, layer=None, mask=None):
        super().__init__()
        self.is_trigger = is_trigger
        self._layer_override = None if layer is None else CollisionLayers.index(layer)
        self.mask = CollisionLayers.ALL if mask is None else _resolve_mask(mask)
        self._layer_bit = 1

        self._l = self._t = self._r = self._b = 0.0
        self._rect = pygame.Rect(0, 0, 0, 0)
        self._rect_valid = True
        self._synced_version = -1
        self._shape_dirty = True
        self._world = None        # the PhysicsWorld while registered
        self._body = None         # the Rigidbody2D on the same object, if any
        self._touching = {}       # colliders currently in contact (ordered set)

        # Lists of `callback(collider, other_collider)`; append to subscribe.
        self.on_trigger_enter = []
        self.on_trigger_stay = []
        self.on_trigger_exit = []
        self.on_collision_enter = []
        self.on_collision_stay = []
        self.on_collision_exit = []

    # -- layers ---------------------------------------------------------------

    @property
    def layer(self):
        """Collision layer index. Defaults to the GameObject's layer."""
        if self._layer_override is not None:
            return self._layer_override
        return self.game_object.layer if self.game_object is not None else 0

    @layer.setter
    def layer(self, value):
        self._layer_override = None if value is None else CollisionLayers.index(value)
        self._on_layer_changed()

    def _on_layer_changed(self):
        self._layer_bit = 1 << self.layer

    def can_collide_with(self, other):
        return bool(self.mask & other._layer_bit) and bool(other.mask & self._layer_bit)

    # -- geometry ---------------------------------------------------------------

    def _recompute_bounds(self, transform):
        raise NotImplementedError

    def refresh(self):
        """Bring the bounds up to date with the transform. Cheap when nothing
        moved (one integer comparison against the transform's world version)."""
        transform = self.game_object.transform
        if transform._dirty:
            transform._ensure_world()
        if transform._world_version == self._synced_version and not self._shape_dirty:
            return False
        self._synced_version = transform._world_version
        self._shape_dirty = False
        self._recompute_bounds(transform)
        self._rect_valid = False
        world = self._world
        if world is not None:
            world._collider_moved(self)
        return True

    @property
    def bounds(self):
        """(left, top, right, bottom) in world space, as exact floats."""
        self.refresh()
        return self._l, self._t, self._r, self._b

    @property
    def rect(self):
        """Axis-aligned bounding box as a (pixel-rounded) pygame.Rect - for
        drawing and legacy code; physics uses the exact float `bounds`."""
        self.refresh()
        if not self._rect_valid:
            self._rect = pygame.Rect(round(self._l), round(self._t),
                                     round(self._r) - round(self._l), round(self._b) - round(self._t))
            self._rect_valid = True
        return self._rect

    @property
    def is_static(self):
        return self.game_object is not None and self.game_object._effective_static

    # -- overlap tests ---------------------------------------------------------

    def _overlap_strict(self, other):
        """True if the shapes overlap by more than an edge touch."""
        if self.shape == "box":
            if other.shape == "box":
                return (self._l < other._r and self._r > other._l and
                        self._t < other._b and self._b > other._t)
            if other.shape == "circle":
                return _circle_box_overlap(other._cx, other._cy, other._radius, self)
        elif self.shape == "circle":
            if other.shape == "circle":
                dx = self._cx - other._cx
                dy = self._cy - other._cy
                radius_sum = self._radius + other._radius
                return (dx * dx + dy * dy) < (radius_sum * radius_sum)
            if other.shape == "box":
                return _circle_box_overlap(self._cx, self._cy, self._radius, other)
        return False

    def _touching_within(self, other, skin):
        """Like _overlap_strict, but boxes count as touching when the gap
        between them is within `skin` (so a body resting on the ground
        reads as in contact despite float error)."""
        if self.shape == "box" and other.shape == "box":
            return (self._l < other._r + skin and self._r > other._l - skin and
                    self._t < other._b + skin and self._b > other._t - skin)
        return self._overlap_strict(other)

    def overlaps(self, other):
        """Precise shape-vs-shape overlap test."""
        self.refresh()
        other.refresh()
        return self._overlap_strict(other)

    def contact_normal(self, other):
        """Unit normal (nx, ny) pointing away from `other` toward this collider."""
        if self.shape == "box" and other.shape == "box":
            candidates = (
                (other._r - self._l, 1.0, 0.0),    # other is on our left  -> push right
                (self._r - other._l, -1.0, 0.0),   # other is on our right -> push left
                (other._b - self._t, 0.0, 1.0),    # other is above us     -> push down
                (self._b - other._t, 0.0, -1.0),   # other is below us     -> push up
            )
            best = min(candidates, key=lambda c: c[0])
            return best[1], best[2]
        ax, ay = (self._cx, self._cy) if self.shape == "circle" else ((self._l + self._r) / 2, (self._t + self._b) / 2)
        bx, by = (other._cx, other._cy) if other.shape == "circle" else ((other._l + other._r) / 2, (other._t + other._b) / 2)
        dx, dy = ax - bx, ay - by
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length else (0.0, -1.0)

    @property
    def overlapping_colliders(self):
        """Read-only snapshot of colliders this one is currently touching
        (as of the last physics step)."""
        return frozenset(self._touching)

    # -- scene registration -----------------------------------------------------

    def _on_scene_enter(self, scene):
        self._on_layer_changed()
        self._synced_version = -1
        self._shape_dirty = True
        self._body = None
        for component in self.game_object.components:
            if getattr(component, "_is_rigidbody", False):
                self._body = component
        scene.physics.add_collider(self)

    def _on_scene_exit(self, scene):
        scene.physics.remove_collider(self)
        self._touching.clear()

    # -- callback plumbing -------------------------------------------------------

    def _dispatch(self, callbacks, other_collider):
        for callback in list(callbacks):  # copy: a callback may unsubscribe itself
            try:
                callback(self, other_collider)
            except Exception as exc:  # noqa: BLE001 - a bad user callback must not crash the game
                owner = getattr(self.game_object, "name", "?")
                DebugManager.log_error(f"Physics callback on '{owner}' raised {exc!r}")
