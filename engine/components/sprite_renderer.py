import warnings

from engine.components.component import Component
from engine.core.game_time import Time
from engine.rendering.surface_cache import prepare_surface, sprite_cache
from engine.utils.anchors import VALID_ANCHORS, anchor_to_topleft_offset
from engine.utils.warnings import EngineWarning


class SpriteRenderer(Component):
    """Draws `sprite` at its GameObject's world position, honoring the
    transform's (world) rotation and scale.

    `anchor` controls which point of the sprite sits at the transform
    position - the same 9 named anchors BoxCollider2D/CircleCollider2D use
    (see engine/utils/anchors.py), deliberately the *same parameter name and
    values*, so lining a sprite up with its own collider is just "pass the same
    anchor to both":

        go.add_component(SpriteRenderer(sprite=img, anchor="center"))
        go.add_component(BoxCollider2D(size=img.get_size(), anchor="center"))

    `z_index` controls draw-order between layers (lower draws first / behind).
    Within the same z_index the scene sorts by `world y + offset_y`, so objects
    lower on screen draw in front - a cheap depth approximation for
    top-down/platformer sprites. `offset_y` only affects that sort key.

    Performance:
      - `convert=True` (default) converts the image to the display format once;
        pass False to keep your surface object untouched.
      - rotated/scaled variants come from a shared LRU cache (see
        engine/rendering/surface_cache.py). Rotation is quantized to
        `rotation_step` degrees (default 1.0; 0 = exact).
      - Off-screen sprites are culled before any drawing work. Static objects
        (`is_static=True`) are registered in a spatial grid once, so a big static
        scene only pays for what the camera can see.
      - `is_visible` tells you whether the sprite was drawn recently; Animator
        uses it to skip off-screen animation ticks.

    Use `set_sprite()` (or assign `.sprite`) to change the image - it keeps the
    cache and the static registration in sync.
    """

    ROTATION_STEP = 1.0

    def __init__(self, sprite=None, z_index=0, offset_y=0, anchor="topleft", convert=True):
        super().__init__()

        if anchor not in VALID_ANCHORS:
            warnings.warn(
                f"SpriteRenderer: unknown anchor '{anchor}', falling back to 'topleft'. "
                f"Valid anchors are: {sorted(VALID_ANCHORS)}",
                EngineWarning,
                stacklevel=2,
            )
            anchor = "topleft"

        self.z_index = z_index
        self.offset_y = offset_y
        self.anchor = anchor
        self.convert = convert
        self.rotation_step = self.ROTATION_STEP

        self._sprite = None
        self._anchor_cache = None       # (width, height, anchor, dx, dy)
        self._transform = None
        self._system = None             # the RenderSystem while registered
        self._last_drawn_frame = None
        self._registered_frame = 0

        # Filled by RenderSystem for the frame's blit: the surface to draw and
        # its top-left in world space (already rotated/scaled/anchored).
        self._dsurf = None
        self._dx = 0.0
        self._dy = 0.0
        self._static_bounds = None
        self._static_sort_y = 0.0

        if sprite is not None:
            self.set_sprite(sprite)

    # -- sprite -------------------------------------------------------------------

    @property
    def sprite(self):
        return self._sprite

    @sprite.setter
    def sprite(self, value):
        self.set_sprite(value)

    def set_sprite(self, sprite):
        if sprite is not None and self.convert:
            sprite = prepare_surface(sprite)
        if sprite is self._sprite:
            return
        self._sprite = sprite
        self._anchor_cache = None
        if self._system is not None:
            self._system.sprite_changed(self)

    # -- geometry -----------------------------------------------------------------

    def get_anchor_offset(self):
        """(dx, dy) from the transform position to this sprite's *original*
        (pre-rotation/scale) top-left corner, based on `anchor`. (0, 0) if
        there's no sprite set yet."""
        if self._sprite is None:
            return (0, 0)
        w, h = self._sprite.get_size()
        return anchor_to_topleft_offset(self.anchor, w, h)

    def get_transformed_sprite(self, rotation, scale_x, scale_y):
        """`sprite` rotated and scaled to match the given transform values
        (None if there's no sprite). Served from the shared cache."""
        if self._sprite is None:
            return None
        if rotation % 360 == 0 and scale_x == 1.0 and scale_y == 1.0:
            return self._sprite
        return sprite_cache.get_transformed(self._sprite, rotation, scale_x, scale_y, self.rotation_step)

    def get_placement(self, world_x, world_y, rotation, scale_x, scale_y):
        """(surface, left, top): what to blit and where, in world space, for a
        transform at (world_x, world_y) with the given world rotation/scale.
        Rotation and scaling pivot around the sprite's own center (after
        anchor placement)."""
        sprite = self._sprite
        w0, h0 = sprite.get_size()
        cache = self._anchor_cache
        if cache is None or cache[0] != w0 or cache[1] != h0 or cache[2] != self.anchor:
            dx, dy = anchor_to_topleft_offset(self.anchor, w0, h0)
            cache = self._anchor_cache = (w0, h0, self.anchor, dx, dy)
        left = world_x + cache[3]
        top = world_y + cache[4]
        if rotation == 0 and scale_x == 1 and scale_y == 1:
            return sprite, left, top
        surface = sprite_cache.get_transformed(sprite, rotation, scale_x, scale_y, self.rotation_step)
        w, h = surface.get_size()
        return surface, left + (w0 - w) * 0.5, top + (h0 - h) * 0.5

    @property
    def is_visible(self):
        """True if this sprite was drawn in the last couple of frames. A sprite
        that hasn't been through a draw pass *yet* (just added to the scene)
        counts as visible for one frame of grace; after that, never having been
        drawn means it is off-screen. If the scene itself isn't being drawn at all
        (a headless simulation), everything counts as visible."""
        frame = Time.frame_count
        system = self._system
        if system is not None:
            drawn = system.last_draw_frame
            if drawn is None or frame - drawn > 1:
                return True      # this scene isn't being drawn (headless run, tests): "off-screen" is meaningless
        last = self._last_drawn_frame
        if last is None:
            return frame - self._registered_frame <= 1
        return frame - last <= 1

    # -- scene registration ------------------------------------------------------

    def _on_scene_enter(self, scene):
        self._transform = self.game_object.transform
        self._system = scene.render_system
        self._last_drawn_frame = None
        self._registered_frame = Time.frame_count
        scene.render_system.add_renderer(self)

    def _on_scene_exit(self, scene):
        scene.render_system.remove_renderer(self)
        self._system = None
