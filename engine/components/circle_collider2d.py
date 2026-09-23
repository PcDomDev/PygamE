import warnings

from engine.components.collider2d import Collider2D
from engine.components.sprite_renderer import SpriteRenderer
from engine.utils.anchors import VALID_ANCHORS, anchor_to_topleft_offset
from engine.utils.warnings import EngineWarning


class CircleCollider2D(Collider2D):
    """A circular collider with precise circle-vs-circle and circle-vs-box
    overlap testing - unlike `create_circle()`'s default bounding-box
    approximation, this tests actual distance-to-center.

    Scope: **overlap/trigger detection only.** `Rigidbody2D` only resolves
    solid collisions against `BoxCollider2D`s - a CircleCollider2D can move
    under gravity/velocity and fire trigger/collision events, but it will not
    push against other colliders. For a coin, sensor, pickup radius or
    detection zone this is exactly what you want; for a solid rolling ball use
    a BoxCollider2D approximation.

    `anchor` works exactly like BoxCollider2D/SpriteRenderer's, applied to the
    circle's `(diameter, diameter)` bounding square; the default "topleft"
    lines a default CircleCollider2D up with a default SpriteRenderer showing a
    circle drawn centered in its own surface.
    """

    shape = "circle"
    update_order = -90

    def __init__(self, radius=None, offset_x=0, offset_y=0, anchor="topleft", is_trigger=False,
                 layer=None, mask=None):
        super().__init__(is_trigger=is_trigger, layer=layer, mask=mask)

        if anchor not in VALID_ANCHORS:
            warnings.warn(
                f"CircleCollider2D: unknown anchor '{anchor}', falling back to 'topleft'. "
                f"Valid anchors are: {sorted(VALID_ANCHORS)}",
                EngineWarning,
                stacklevel=2,
            )
            anchor = "topleft"

        self._explicit_radius = radius
        self._radius = radius if radius is not None else 0.0
        self._cx = 0.0
        self._cy = 0.0

        self.offset_x = offset_x
        self.offset_y = offset_y
        self.anchor = anchor
        self.sprite_renderer = None

    def start(self):
        self.sprite_renderer = self.game_object.get_component(SpriteRenderer)
        if self._explicit_radius is None:
            self._radius = self._measure_from_sprite()
        self._shape_dirty = True

    def _measure_from_sprite(self):
        if self.sprite_renderer and self.sprite_renderer.sprite:
            w, h = self.sprite_renderer.sprite.get_size()
            return max(w, h) / 2.0
        return 0.0

    def set_radius(self, radius):
        """Explicitly (re)size the collider; locks the radius so it stops tracking the sprite."""
        self._explicit_radius = radius
        self._radius = radius
        self._shape_dirty = True
        self.refresh()

    @property
    def radius(self):
        return self._radius

    @property
    def center_x(self):
        self.refresh()
        return self._cx

    @property
    def center_y(self):
        self.refresh()
        return self._cy

    def _recompute_bounds(self, transform):
        r = self._radius
        diameter = r * 2
        dx, dy = anchor_to_topleft_offset(self.anchor, diameter, diameter)
        self._cx = transform._world_x + self.offset_x + dx + r
        self._cy = transform._world_y + self.offset_y + dy + r
        self._l = self._cx - r
        self._t = self._cy - r
        self._r = self._cx + r
        self._b = self._cy + r
