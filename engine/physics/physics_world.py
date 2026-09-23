"""PhysicsWorld: the per-Scene physics system.

Owns the collider broad-phase (a SpatialHash), the list of simulated
Rigidbody2Ds, and the table of currently-touching collider pairs that drives
the enter/stay/exit callbacks. `Scene.fixed_update()` calls `step(dt)` once per
fixed timestep, after every component's `fixed_update` hook has run:

    1. refresh colliders that were moved by scripts (transform changed)
    2. simulate every Rigidbody2D (forces -> swept movement)
    3. find touching pairs, diff against the previous step, dispatch
       exit / enter / stay callbacks

Static objects never appear in step 1 or 2 and never *initiate* pair queries,
so a scene of ten thousand static tiles costs nothing per step.
"""
from engine.core.debug_manager import DebugManager
from engine.core.spatial_hash import SpatialHash
from engine.physics.collision import Collision2D
from engine.physics.layers import CollisionLayers
from engine.utils.vector2 import Vector2

_TRIGGER = 1
_COLLISION = 2

_ENTER = "enter"
_STAY = "stay"
_EXIT = "exit"


class PhysicsStats:
    __slots__ = ("steps", "bodies", "colliders", "pairs", "queries")

    def __init__(self):
        self.steps = 0
        self.bodies = 0
        self.colliders = 0
        self.pairs = 0
        self.queries = 0


class PhysicsWorld:
    # Solid boxes closer than this (px) count as in contact for collision events.
    CONTACT_SKIN = 0.05

    def __init__(self, scene, cell_size=128):
        self.scene = scene
        self.spatial_hash = SpatialHash(cell_size)
        self._colliders = {}    # every registered collider (ordered set)
        self._dynamic = {}      # colliders on non-static objects
        self._bodies = {}       # simulated Rigidbody2Ds
        self._pairs = {}        # (seq_a, seq_b) -> (a, b, kind) touching as of the last step
        self.stats = PhysicsStats()

    # -- registration --------------------------------------------------------------

    def add_collider(self, collider):
        collider._world = self
        collider.refresh()
        self._colliders[collider] = None
        if not collider.game_object._effective_static:
            self._dynamic[collider] = None
        self.spatial_hash.update_bounds(collider, collider._l, collider._t, collider._r, collider._b)

    def remove_collider(self, collider):
        self.spatial_hash.remove(collider)
        self._colliders.pop(collider, None)
        self._dynamic.pop(collider, None)
        collider._world = None

    def add_body(self, body):
        if not body.game_object._effective_static:
            self._bodies[body] = None

    def remove_body(self, body):
        self._bodies.pop(body, None)

    @property
    def colliders(self):
        """Every registered collider (snapshot list)."""
        return list(self._colliders)

    @property
    def bodies(self):
        """Every simulated Rigidbody2D (snapshot list)."""
        return list(self._bodies)

    def _collider_moved(self, collider):
        self.spatial_hash.update_bounds(collider, collider._l, collider._t, collider._r, collider._b)

    def clear(self):
        self.spatial_hash.clear()
        self._colliders.clear()
        self._dynamic.clear()
        self._bodies.clear()
        self._pairs.clear()

    # -- the step ------------------------------------------------------------------

    def step(self, dt):
        stats = self.stats
        stats.steps += 1

        for collider in self._dynamic:
            collider.refresh()

        for body in tuple(self._bodies):
            if body.enabled:
                body._simulate(dt)

        self._update_contacts()
        stats.bodies = len(self._bodies)
        stats.colliders = len(self._colliders)

    def solid_candidates(self, collider, left, top, right, bottom):
        """Solid BoxCollider2Ds near the box that `collider` can physically hit
        (layer/mask permitting) - what a Rigidbody2D sweeps against."""
        self.stats.queries += 1
        mask = collider.mask
        bit = collider._layer_bit
        result = []
        for other in self.spatial_hash.query_bounds(left, top, right, bottom):
            if other is collider or other.is_trigger or other.shape != "box" or not other.enabled:
                continue
            if not (mask & other._layer_bit) or not (other.mask & bit):
                continue
            result.append(other)
        return result

    # -- contacts and events ------------------------------------------------------------

    def _update_contacts(self):
        skin = self.CONTACT_SKIN
        query = self.spatial_hash.query_bounds
        new_pairs = {}

        for a in self._dynamic:
            if not a.enabled:
                continue
            a_mask = a.mask
            a_bit = a._layer_bit
            a_trigger = a.is_trigger
            a_has_body = a._body is not None
            a_box = a.shape == "box"
            al, at, ar, ab = a._l, a._t, a._r, a._b
            for other in query(al - skin, at - skin, ar + skin, ab + skin):
                if other is a or not other.enabled:
                    continue
                if not (a_mask & other._layer_bit) or not (other.mask & a_bit):
                    continue          # layers don't interact: skip the exact test entirely
                if a_trigger or other.is_trigger:
                    if not a._overlap_strict(other):
                        continue
                    kind = _TRIGGER
                elif a_has_body or other._body is not None:
                    if a_box and other.shape == "box":
                        if not (al < other._r + skin and ar > other._l - skin and
                                at < other._b + skin and ab > other._t - skin):
                            continue
                    elif not a._touching_within(other, skin):
                        continue
                    kind = _COLLISION
                else:
                    continue
                key = (a._seq, other._seq) if a._seq < other._seq else (other._seq, a._seq)
                if key not in new_pairs:
                    new_pairs[key] = (a, other, kind)

        old_pairs = self._pairs
        self._pairs = new_pairs
        self.stats.pairs = len(new_pairs)
        if not old_pairs and not new_pairs:
            return

        exits = [v for k, v in old_pairs.items() if k not in new_pairs]
        enters = [v for k, v in new_pairs.items() if k not in old_pairs]
        stays = [v for k, v in new_pairs.items() if k in old_pairs]

        for a, b, kind in exits:
            self._dispatch(_EXIT, a, b, kind)
        for a, b, kind in enters:
            self._dispatch(_ENTER, a, b, kind)
        for a, b, kind in stays:
            self._dispatch(_STAY, a, b, kind)

    def _dispatch(self, phase, a, b, kind):
        if phase == _ENTER:
            a._touching[b] = None
            b._touching[a] = None
        elif phase == _EXIT:
            a._touching.pop(b, None)
            b._touching.pop(a, None)

        name = ("on_trigger_" if kind == _TRIGGER else "on_collision_") + phase
        for me, other in ((a, b), (b, a)):
            callbacks = getattr(me, name)
            go = me.game_object
            hooks = go._get_hooks(name) if go is not None else ()
            if not callbacks and not hooks:
                continue
            if callbacks:
                me._dispatch(callbacks, other)
            if hooks:
                if kind == _TRIGGER:
                    argument = other
                else:
                    nx, ny = me.contact_normal(other)
                    argument = Collision2D(me, other, Vector2(nx, ny))
                for fn in hooks:
                    try:
                        fn(argument)
                    except Exception as exc:  # noqa: BLE001 - a bad gameplay hook must not crash the game
                        DebugManager.log_error(f"{name} on '{go.name}' raised {exc!r}", source="Physics")

    # -- queries ---------------------------------------------------------------------

    def query_bounds(self, left, top, right, bottom, mask=CollisionLayers.ALL, include_triggers=True):
        """Colliders that overlap the box (exact test), in deterministic order."""
        probe = _Box(left, top, right, bottom)
        result = []
        for collider in self.spatial_hash.query_bounds(left, top, right, bottom):
            if not collider.enabled or not (mask & collider._layer_bit):
                continue
            if collider.is_trigger and not include_triggers:
                continue
            collider.refresh()
            if collider._overlap_strict(probe):
                result.append(collider)
        return result

    def query_rect(self, rect, mask=CollisionLayers.ALL, include_triggers=True):
        """Colliders overlapping a pygame.Rect (world space)."""
        return self.query_bounds(rect.left, rect.top, rect.right, rect.bottom, mask, include_triggers)

    def query_point(self, x, y, mask=CollisionLayers.ALL, include_triggers=True):
        """Colliders containing the world point (x, y)."""
        result = []
        for collider in self.spatial_hash.query_bounds(x, y, x, y):
            if not collider.enabled or not (mask & collider._layer_bit):
                continue
            if collider.is_trigger and not include_triggers:
                continue
            collider.refresh()
            if collider.shape == "box":
                inside = collider._l <= x <= collider._r and collider._t <= y <= collider._b
            else:
                dx, dy = x - collider._cx, y - collider._cy
                inside = dx * dx + dy * dy <= collider._radius * collider._radius
            if inside:
                result.append(collider)
        return result


class _Box:
    """A bare box with the attributes the overlap tests read (for queries)."""

    shape = "box"
    __slots__ = ("_l", "_t", "_r", "_b")

    def __init__(self, left, top, right, bottom):
        self._l = left
        self._t = top
        self._r = right
        self._b = bottom
