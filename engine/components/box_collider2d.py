import warnings

from engine.components.collider2d import Collider2D
from engine.components.sprite_renderer import SpriteRenderer
from engine.core.debug_manager import DebugManager
from engine.utils.anchors import VALID_ANCHORS, anchor_to_topleft_offset
from engine.utils.warnings import EngineWarning


class BoxCollider2D(Collider2D):
    """An axis-aligned box used for collision (solid) or overlap (trigger)
    detection.

    Sizing: pass `size=(w, h)` explicitly when you can - it's the most
    predictable option. If you omit it, the size is captured *once*, from
    whatever sprite is on this GameObject's SpriteRenderer at `start()`
    time, and then locked in place. It deliberately does **not** keep
    re-measuring the live sprite every frame, because an Animator can swap the
    sprite out from under it, and a collider that changes shape mid-collision
    is what produced the old landing jitter. If you deliberately want the hitbox
    to resize later (e.g. a crouch), call `set_size()` explicitly.

    Anchor: controls where the *hitbox* sits relative to the transform
    position. SpriteRenderer has a matching `anchor` parameter using the exact
    same names and math (engine/utils/anchors.py); the two do **not**
    automatically agree unless you set them to the same value. If a sprite and
    its collider look misaligned, that's almost always the fix.

    `layer` / `mask`: see engine/physics/layers.py.
    """

    shape = "box"
    update_order = -90

    def __init__(self, size=None, offset_x=0, offset_y=0, anchor="topleft", is_trigger=False,
                 layer=None, mask=None):
        super().__init__(is_trigger=is_trigger, layer=layer, mask=mask)

        if anchor not in VALID_ANCHORS:
            warnings.warn(
                f"BoxCollider2D: unknown anchor '{anchor}', falling back to 'topleft'. "
                f"Valid anchors are: {sorted(VALID_ANCHORS)}",
                EngineWarning,
                stacklevel=2,
            )
            anchor = "topleft"

        self._explicit_size = tuple(size) if size is not None else None
        self._locked_size = self._explicit_size or (0, 0)

        self.offset_x = offset_x
        self.offset_y = offset_y
        self.anchor = anchor
        self.sprite_renderer = None
        self._anchor_cache = None   # (w, h, anchor, dx, dy)

    @property
    def size(self):
        return self._locked_size

    def start(self):
        self.sprite_renderer = self.game_object.get_component(SpriteRenderer)
        if self._explicit_size is None:
            self._locked_size = self._measure_from_sprite()
            if self._locked_size == (0, 0):
                DebugManager.log_warning(
                    f"BoxCollider2D on '{self.game_object.name}' has no size: pass size=(w, h) or "
                    f"add a SpriteRenderer with a sprite before it.", source="BoxCollider2D")
        self._shape_dirty = True

    def _measure_from_sprite(self):
        if self.sprite_renderer and self.sprite_renderer.sprite:
            return self.sprite_renderer.sprite.get_size()
        return (0, 0)

    def set_size(self, width, height):
        """Explicitly (re)size the collider, e.g. for a deliberate crouch
        hitbox. Once called, the size is locked to (width, height) and will
        not be affected by sprite/animation changes."""
        self._explicit_size = (width, height)
        self._locked_size = (width, height)
        self._shape_dirty = True
        self.refresh()

    def _recompute_bounds(self, transform):
        w, h = self._locked_size
        cache = self._anchor_cache
        if cache is None or cache[0] != w or cache[1] != h or cache[2] != self.anchor:
            dx, dy = anchor_to_topleft_offset(self.anchor, w, h)
            cache = self._anchor_cache = (w, h, self.anchor, dx, dy)
        left = transform._world_x + self.offset_x + cache[3]
        top = transform._world_y + self.offset_y + cache[4]
        self._l = left
        self._t = top
        self._r = left + w
        self._b = top + h

    # -- exact positioning (kept for API compatibility) --------------------------------

    def _move_transform_by(self, dx, dy):
        transform = self.game_object.transform
        transform.set_world_position(transform.world_x + dx, transform.world_y + dy)
        self.refresh()

    def snap_left_to(self, world_x):
        """Move the owning Transform so this collider's left edge sits at exactly `world_x`."""
        self.refresh()
        self._move_transform_by(world_x - self._l, 0.0)

    def snap_right_to(self, world_x):
        self.refresh()
        self._move_transform_by(world_x - self._r, 0.0)

    def snap_top_to(self, world_y):
        self.refresh()
        self._move_transform_by(0.0, world_y - self._t)

    def snap_bottom_to(self, world_y):
        self.refresh()
        self._move_transform_by(0.0, world_y - self._b)
