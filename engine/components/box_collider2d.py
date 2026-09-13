import warnings

import pygame

from engine.components.collider2d import Collider2D, _circle_rect_overlap
from engine.components.sprite_renderer import SpriteRenderer
from engine.utils.anchors import VALID_ANCHORS, anchor_to_topleft_offset
from engine.utils.warnings import EngineWarning


class BoxCollider2D(Collider2D):
    """An axis-aligned box used for collision (solid) or overlap (trigger)
    detection.

    Sizing: pass `size=(w, h)` explicitly when you can - it's the most
    predictable option. If you omit it, the size is captured *once*, from
    whatever sprite is on this GameObject's SpriteRenderer at `start()`
    time, and then locked in place. It deliberately does **not** keep
    re-measuring the live sprite every frame, because this GameObject's
    sprite can change out from under it (an Animator swapping frames), and
    if two animation frames aren't pixel-identical in size, a collider that
    tracks the current frame changes shape mid-collision - which is exactly
    what produced the reported landing jitter (see README "What changed"
    history). If you deliberately want the hitbox to resize later (e.g. a
    crouch), call `set_size()` explicitly.

    Anchor note: this only controls where the *hitbox* sits relative to
    the transform position - SpriteRenderer has a matching `anchor`
    parameter using the exact same names and math (see
    engine/utils/anchors.py), and the two do **not** automatically agree
    unless you set them to the same value. If a sprite and its collider
    look misaligned, that's almost always the fix - see the README's
    Transform/anchors section.
    """

    shape = "box"
    update_order = -90  # sync right after Rigidbody2D resolves movement

    def __init__(self, size=None, offset_x=0, offset_y=0, anchor="topleft", is_trigger=False):
        super().__init__(is_trigger=is_trigger)

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

        self.rect = pygame.Rect(0, 0, 0, 0)
        self.sprite_renderer = None

    def start(self):
        self.sprite_renderer = self.game_object.get_component(SpriteRenderer)
        if self._explicit_size is None:
            self._locked_size = self._measure_from_sprite()
        self._update_rect()

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
        self._update_rect()

    def update(self, delta_time):
        self._update_rect()

    def _update_rect(self):
        w, h = self._locked_size
        self.rect = pygame.Rect(0, 0, w, h)

        transform = self.game_object.transform
        target_x = transform.position.x + self.offset_x
        target_y = transform.position.y + self.offset_y

        # anchor is validated in __init__, so this attribute always exists.
        # pygame quantizes this to an int rect internally (see
        # snap_*_to below for why that quantization must never leak into
        # collision *resolution*, only detection/rendering).
        setattr(self.rect, self.anchor, (target_x, target_y))
        self._sync_spatial_hash()

    # -- exact (unrounded) positioning, used for collision resolution ------------

    def _anchor_offset(self):
        return anchor_to_topleft_offset(self.anchor, *self._locked_size)

    def snap_left_to(self, world_x):
        """Move the owning Transform so this collider's left edge sits at
        exactly `world_x`, computed from the exact float transform position
        rather than the already pixel-rounded `.rect` - see
        Rigidbody2D._resolve_collisions_x for why."""
        dx, _ = self._anchor_offset()
        self.game_object.transform.position.x = world_x - dx - self.offset_x
        self._update_rect()

    def snap_right_to(self, world_x):
        dx, _ = self._anchor_offset()
        w, _ = self._locked_size
        self.game_object.transform.position.x = (world_x - w) - dx - self.offset_x
        self._update_rect()

    def snap_top_to(self, world_y):
        _, dy = self._anchor_offset()
        self.game_object.transform.position.y = world_y - dy - self.offset_y
        self._update_rect()

    def snap_bottom_to(self, world_y):
        _, dy = self._anchor_offset()
        _, h = self._locked_size
        self.game_object.transform.position.y = (world_y - h) - dy - self.offset_y
        self._update_rect()

    # -- overlap test ---------------------------------------------------------------

    def overlaps(self, other):
        if other.shape == "box":
            return self.rect.colliderect(other.rect)
        if other.shape == "circle":
            return _circle_rect_overlap(other.center_x, other.center_y, other.radius, self.rect)
        return False
