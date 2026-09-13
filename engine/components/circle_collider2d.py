import warnings

import pygame

from engine.components.collider2d import Collider2D, _circle_circle_overlap, _circle_rect_overlap
from engine.components.sprite_renderer import SpriteRenderer
from engine.utils.anchors import VALID_ANCHORS, anchor_to_topleft_offset
from engine.utils.warnings import EngineWarning


class CircleCollider2D(Collider2D):
    """A circular collider with precise circle-vs-circle and circle-vs-box
    overlap testing - unlike `create_circle()`'s default bounding-box
    approximation, this tests actual distance-to-center, so a coin at the
    very corner of another object's bounding box that doesn't actually
    touch the visible circle correctly reads as "not overlapping".

    Scope: **overlap/trigger detection only.** `Rigidbody2D` only looks
    for a `BoxCollider2D` to resolve solid collisions against - a
    CircleCollider2D can still move under gravity/velocity (nothing stops
    that), but it will not push against or be pushed by other colliders
    the way a BoxCollider2D does. For a coin, sensor, pickup radius, or
    detection zone (all commonly circular, all typically triggers) this is
    exactly what you want. For a solid, physically-colliding round object
    (a rolling ball that should bounce/rest correctly), this engine does
    not yet implement that - use a BoxCollider2D approximation, or treat
    this as a documented extension point.

    `anchor` works exactly like BoxCollider2D/SpriteRenderer's - the same
    9 named points, applied to the circle's `(diameter, diameter)`
    bounding square. The default, `"topleft"`, is what makes a default
    CircleCollider2D line up with a default (also `anchor="topleft"`)
    SpriteRenderer showing a circle drawn centered in its own surface -
    both then agree that the transform position is the top-left corner of
    the same bounding square, so the collider is centered exactly under
    the visible circle with no extra offset math needed.
    """

    shape = "circle"
    update_order = -90  # same phase as BoxCollider2D - sync after Rigidbody2D

    def __init__(self, radius=None, offset_x=0, offset_y=0, anchor="topleft", is_trigger=False):
        super().__init__(is_trigger=is_trigger)

        if anchor not in VALID_ANCHORS:
            warnings.warn(
                f"CircleCollider2D: unknown anchor '{anchor}', falling back to 'topleft'. "
                f"Valid anchors are: {sorted(VALID_ANCHORS)}",
                EngineWarning,
                stacklevel=2,
            )
            anchor = "topleft"

        self._explicit_radius = radius
        self._locked_radius = radius if radius is not None else 0.0

        self.offset_x = offset_x
        self.offset_y = offset_y
        self.anchor = anchor

        self.center_x = 0.0
        self.center_y = 0.0
        self.rect = pygame.Rect(0, 0, 0, 0)  # bounding box - broad-phase queries, debug outlines

        self.sprite_renderer = None

    def start(self):
        self.sprite_renderer = self.game_object.get_component(SpriteRenderer)
        if self._explicit_radius is None:
            self._locked_radius = self._measure_from_sprite()
        self._update_shape()

    def _measure_from_sprite(self):
        if self.sprite_renderer and self.sprite_renderer.sprite:
            w, h = self.sprite_renderer.sprite.get_size()
            return max(w, h) / 2.0
        return 0.0

    def set_radius(self, radius):
        """Explicitly (re)size the collider - same idea as
        BoxCollider2D.set_size(): locks the radius so it stops tracking
        the sprite, even if you didn't pass one explicitly at construction."""
        self._explicit_radius = radius
        self._locked_radius = radius
        self._update_shape()

    @property
    def radius(self):
        return self._locked_radius

    def update(self, delta_time):
        self._update_shape()

    def _update_shape(self):
        transform = self.game_object.transform
        r = self._locked_radius
        diameter = r * 2

        # Offset from the anchor point to the bounding square's top-left,
        # same math BoxCollider2D uses - the center is then half a
        # diameter further down-right from that corner.
        dx, dy = anchor_to_topleft_offset(self.anchor, diameter, diameter)

        anchor_x = transform.position.x + self.offset_x
        anchor_y = transform.position.y + self.offset_y
        self.center_x = anchor_x + dx + r
        self.center_y = anchor_y + dy + r

        self.rect = pygame.Rect(
            round(self.center_x - r), round(self.center_y - r),
            round(diameter), round(diameter),
        )
        self._sync_spatial_hash()

    def overlaps(self, other):
        if other.shape == "circle":
            return _circle_circle_overlap(
                self.center_x, self.center_y, self.radius,
                other.center_x, other.center_y, other.radius,
            )
        if other.shape == "box":
            return _circle_rect_overlap(self.center_x, self.center_y, self.radius, other.rect)
        return False
