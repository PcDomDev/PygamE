"""RenderSystem: the world-space draw pass of a Scene.

Per frame it: builds the camera's view box, gathers visible sprites (static
ones from a spatial grid, dynamic ones by testing each), adds custom
drawables (particles, baked layers, world-space UI), sorts everything by
(z_index, y, creation order) and draws it in batched `blits()`.

Costs scale with what's *visible*, not what exists: a static sprite far from
the camera is never touched. For static scenery the real win is baking (see
engine/rendering/tilemap.py) - hundreds of blits become a handful.
"""
import pygame

from engine.core.game_time import Time
from engine.core.spatial_hash import SpatialHash

_HAS_FBLITS = hasattr(pygame.Surface, "fblits")     # pygame-ce's faster batch blit


class RenderStats:
    __slots__ = ("draw_calls", "sprites_drawn", "sprites_culled", "static_registered",
                 "dynamic_registered", "drawables")

    def __init__(self):
        self.reset()
        self.static_registered = 0
        self.dynamic_registered = 0

    def reset(self):
        self.draw_calls = 0
        self.sprites_drawn = 0
        self.sprites_culled = 0
        self.drawables = 0


class RenderSystem:
    def __init__(self, scene, cell_size=256):
        self.scene = scene
        self.stats = RenderStats()
        self.culling = True
        self.last_draw_frame = None     # Time.frame_count of the most recent draw pass
        self._static_grid = SpatialHash(cell_size)
        self._static = {}       # static SpriteRenderers (ordered set)
        self._dynamic = {}      # SpriteRenderers on non-static objects
        self._drawables = {}    # components that override draw_world()

    # -- registration --------------------------------------------------------------

    def add_renderer(self, renderer):
        if renderer.game_object._effective_static:
            self._static[renderer] = None
            self.refresh_static(renderer)
        else:
            self._dynamic[renderer] = None
        self.stats.static_registered = len(self._static)
        self.stats.dynamic_registered = len(self._dynamic)

    def remove_renderer(self, renderer):
        if renderer in self._static:
            del self._static[renderer]
            self._static_grid.remove(renderer)
        self._dynamic.pop(renderer, None)
        self.stats.static_registered = len(self._static)
        self.stats.dynamic_registered = len(self._dynamic)

    def add_drawable(self, component):
        self._drawables[component] = None

    def remove_drawable(self, component):
        self._drawables.pop(component, None)

    def sprite_changed(self, renderer):
        if renderer in self._static:
            self.refresh_static(renderer)

    def refresh_static(self, renderer):
        """Recompute a static sprite's placement and grid entry (registration
        time, or after its sprite changed)."""
        if renderer._sprite is None:
            self._static_grid.remove(renderer)
            renderer._static_bounds = None
            return
        t = renderer._transform or renderer.game_object.transform
        t._ensure_world()
        surface, x, y = renderer.get_placement(t._world_x, t._world_y, t._world_rot, t._world_sx, t._world_sy)
        w, h = surface.get_size()
        renderer._dsurf = surface
        renderer._dx = x
        renderer._dy = y
        renderer._static_sort_y = t._world_y + renderer.offset_y
        renderer._static_bounds = (x, y, x + w, y + h)
        self._static_grid.update_bounds(renderer, x, y, x + w, y + h)

    def clear(self):
        self._static_grid.clear()
        self._static.clear()
        self._dynamic.clear()
        self._drawables.clear()

    # -- drawing --------------------------------------------------------------------

    def draw_world(self, screen, ox, oy, alpha):
        """Draw everything in the world. `ox, oy` is the (integer) camera
        offset: the world point at the screen's top-left corner."""
        stats = self.stats
        stats.reset()
        self.last_draw_frame = Time.frame_count
        sw, sh = screen.get_size()
        vl, vt, vr, vb = ox, oy, ox + sw, oy + sh
        frame = Time.frame_count
        culling = self.culling
        items = []
        add = items.append

        # Static sprites: only the grid cells the camera overlaps.
        if self._static:
            candidates = self._static_grid.query_bounds(vl, vt, vr, vb)
            for r in candidates:
                if not r.enabled:
                    continue
                bl, bt, br, bb = r._static_bounds
                if br < vl or bl > vr or bb < vt or bt > vb:
                    continue
                r._last_drawn_frame = frame
                add((r.z_index, r._static_sort_y, r._seq, r, True))
            stats.sprites_culled += len(self._static) - len(candidates)

        # Dynamic sprites: interpolated position, transformed placement, cull.
        culled = 0
        for r in self._dynamic:
            if not r.enabled:
                continue
            sprite = r._sprite
            if sprite is None:
                continue
            t = r._transform
            wx, wy = t.get_render_xy(alpha)
            surface, x, y = r.get_placement(wx, wy, t._world_rot, t._world_sx, t._world_sy)
            w, h = surface.get_size()
            if culling and (x + w < vl or x > vr or y + h < vt or y > vb):
                culled += 1
                continue
            r._dsurf = surface
            r._dx = x
            r._dy = y
            r._last_drawn_frame = frame
            add((r.z_index, wy + r.offset_y, r._seq, r, True))
        stats.sprites_culled += culled

        for d in self._drawables:
            if d.enabled:
                add((getattr(d, "z_index", 0), getattr(d, "sort_y", 0.0), d._seq, d, False))

        items.sort()

        blits = []
        for _z, _y, _seq, obj, is_sprite in items:
            if is_sprite:
                blits.append((obj._dsurf, (round(obj._dx) - ox, round(obj._dy) - oy)))
            else:
                if blits:
                    self._flush(screen, blits)
                    blits = []
                calls = obj.draw_world(screen, ox, oy, alpha)
                if calls:
                    stats.draw_calls += calls
                    stats.drawables += 1
        if blits:
            self._flush(screen, blits)

    def _flush(self, screen, blits):
        self.stats.draw_calls += len(blits)
        self.stats.sprites_drawn += len(blits)
        if _HAS_FBLITS:
            screen.fblits(blits, 0)
        else:
            screen.blits(blits, False)
