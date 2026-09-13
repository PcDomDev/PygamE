import warnings

import pygame

from engine.components.component import Component
from engine.utils.anchors import VALID_ANCHORS, anchor_to_topleft_offset
from engine.utils.warnings import EngineWarning


class SpriteRenderer(Component):
    """Draws `sprite` at its GameObject's transform position every frame,
    honoring the transform's rotation and scale.

    `anchor` controls which point of the sprite sits at the transform
    position - the same 9 named anchors BoxCollider2D/CircleCollider2D
    use (see engine/utils/anchors.py), and deliberately the *same
    parameter name and values*, so lining a sprite up with its own
    collider is just "pass the same anchor to both":

        go.add_component(SpriteRenderer(sprite=img, anchor="center"))
        go.add_component(BoxCollider2D(size=img.get_size(), anchor="center"))

    Before this, SpriteRenderer had no anchor concept at all and *always*
    drew from the raw transform position as a top-left corner - so a
    collider anchored anywhere else (very reasonably, e.g. "center" or
    "bottomleft") would visually disagree with where its own sprite
    appeared. Defaulting `anchor="topleft"` here keeps existing code
    (which never set a collider anchor other than the default) rendering
    identically to before.

    `z_index` controls draw-order between layers (lower draws first / behind).
    Within the same z_index, Scene sorts by `transform.position.y + offset_y`
    so objects lower on screen draw in front - a common cheap approximation
    of depth for top-down/platformer sprites. `offset_y` only affects that
    sort key, not the actual draw position, so you can nudge an object's
    "feet" reference point for sorting purposes without moving its sprite.

    Rotation/scale note: `self.sprite` always stays the original, unrotated,
    unscaled image you set - get_transformed_sprite() returns a *new*
    surface built from it, cached and only rebuilt when the transform's
    rotation/scale (or the sprite itself) actually changes, so a static
    object doesn't pay the cost of re-rotating/re-scaling every frame.
    Rotation/scaling always pivots around the sprite's own center (after
    anchor placement), which is the visually expected behaviour.
    """

    def __init__(self, sprite=None, z_index=0, offset_y=0, anchor="topleft"):
        super().__init__()

        if anchor not in VALID_ANCHORS:
            warnings.warn(
                f"SpriteRenderer: unknown anchor '{anchor}', falling back to 'topleft'. "
                f"Valid anchors are: {sorted(VALID_ANCHORS)}",
                EngineWarning,
                stacklevel=2,
            )
            anchor = "topleft"

        self.sprite = sprite
        self.z_index = z_index
        self.offset_y = offset_y
        self.anchor = anchor

        self._cache_key = None
        self._cached_sprite = None

    def set_sprite(self, sprite):
        self.sprite = sprite
        self._cache_key = None  # invalidate the rotation/scale cache

    def get_anchor_offset(self):
        """(dx, dy) from the transform position to this sprite's
        *original* (pre-rotation/scale) top-left corner, based on
        `anchor`. (0, 0) if there's no sprite set yet."""
        if self.sprite is None:
            return (0, 0)
        w, h = self.sprite.get_size()
        return anchor_to_topleft_offset(self.anchor, w, h)

    def get_transformed_sprite(self, rotation, scale_x, scale_y):
        """`self.sprite`, rotated and scaled to match the given transform
        values. Returns None if there's no sprite set.

        Rotation is clockwise-positive in degrees (matching this engine's
        on-screen, Y-down coordinate system), which is the opposite of
        pygame.transform.rotate's own counter-clockwise-positive
        convention - hence the negated angle below.
        """
        if self.sprite is None:
            return None

        # Rounding the cache key means "close enough" rotation/scale values
        # reuse the same cached surface instead of rebuilding on every
        # microscopic floating-point change.
        key = (id(self.sprite), round(rotation, 2), round(scale_x, 3), round(scale_y, 3))
        if key == self._cache_key:
            return self._cached_sprite

        result = self.sprite

        if scale_x != 1.0 or scale_y != 1.0:
            original_w, original_h = self.sprite.get_size()
            new_w = max(1, round(original_w * scale_x))
            new_h = max(1, round(original_h * scale_y))
            result = pygame.transform.scale(result, (new_w, new_h))

        if rotation % 360 != 0:
            result = pygame.transform.rotate(result, -rotation)

        self._cache_key = key
        self._cached_sprite = result
        return result
