"""Tilemap / static-scenery baking.

Drawing 2,000 static tiles costs 2,000 `blit()` calls every frame, forever.
Baking draws them *once*, at load time, onto big pre-rendered surfaces; each
frame then costs one blit per visible chunk (usually one to four).

    grid = [[1, 1, 1], [0, 2, 0]]                    # tile ids (None/-1 = empty)
    ground = bake_tilemap(grid, {0: dirt, 1: grass, 2: rock}, tile_size=32)
    scene.add_game_object(ground)

or bake sprites that are already in the scene:

    bake_static_sprites(scene)      # every static, non-animated SpriteRenderer

Layout: with `chunk_size=None` a layer is a single Surface, unless it would
exceed ~16 megapixels (64 MB), in which case it is split into 2048-px chunks
so a huge sparse level doesn't allocate one enormous image. Only chunks the
camera overlaps are blitted, and only chunks that contain something are
allocated.

Translucent sprites: overlapping semi-transparent pixels can't be accumulated
correctly with pygame's plain alpha blit (it ignores the destination's own alpha),
so non-opaque layers are accumulated in *premultiplied* alpha and drawn with
`BLEND_PREMULTIPLIED`; the result matches drawing the sprites one by one to
within rounding (+-2 levels). A one-time self-test checks the blend on the
running pygame build and, if it misbehaves, falls back to plain blits (exact for
opaque/non-overlapping sprites, approximate where translucent pixels overlap) with
a warning. `opaque=True` layers never need any of this.

Trade-offs: baked pixels are frozen (a baked sprite can't move, animate or
change - keep those as normal objects), and all baked sprites of one z_index
become one layer, so they no longer interleave by-y with dynamic sprites *of the
same z_index*. Give props that must interleave a distinct z_index.
"""
import math

import pygame

from engine.components.component import Component
from engine.core.debug_manager import DebugManager
from engine.core.game_object import GameObject
from engine.rendering.surface_cache import prepare_surface


_premultiplied_ok = None


def _premultiply(surface):
    """A premultiplied-alpha copy of a per-pixel-alpha surface, built with blend
    flags only (no numpy): colour*alpha comes from blitting onto black; the alpha
    channel is restored with a per-channel minimum against the original."""
    width, height = surface.get_size()
    black = pygame.Surface((width, height))
    black.fill((0, 0, 0))
    black.blit(surface, (0, 0))
    result = black.convert_alpha()
    alpha_only = surface.copy()
    alpha_only.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_ADD)
    result.blit(alpha_only, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return result


def _premultiplied_supported():
    """One-time check that premultiplied accumulation works on this pygame build."""
    global _premultiplied_ok
    if _premultiplied_ok is None:
        try:
            if pygame.display.get_surface() is None or not hasattr(pygame, "BLEND_PREMULTIPLIED"):
                return False          # can't tell yet / not available; don't cache the answer
            def solid(color):
                s = pygame.Surface((4, 4), pygame.SRCALPHA)
                s.fill(color)
                return s.convert_alpha()
            a, b = solid((255, 0, 0, 128)), solid((0, 0, 255, 128))
            expected = pygame.Surface((4, 4))
            expected.fill((10, 20, 30))
            expected.blit(b, (0, 0))
            expected.blit(a, (0, 0))
            chunk = pygame.Surface((4, 4), pygame.SRCALPHA).convert_alpha()
            chunk.blit(_premultiply(b), (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
            chunk.blit(_premultiply(a), (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
            actual = pygame.Surface((4, 4))
            actual.fill((10, 20, 30))
            actual.blit(chunk, (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
            _premultiplied_ok = all(abs(x - y) <= 3 for x, y in
                                    zip(expected.get_at((1, 1))[:3], actual.get_at((1, 1))[:3]))
        except (pygame.error, AttributeError):
            _premultiplied_ok = False
        if not _premultiplied_ok:
            DebugManager.log_warning(
                "BakedLayer: premultiplied blending isn't reliable on this pygame build; overlapping "
                "translucent baked sprites will composite approximately.", source="Render")
    return bool(_premultiplied_ok)


class BakedLayer(Component):
    """A pre-rendered static layer. Attach to a (static) GameObject and call
    `bake(items)`, or build one with `bake_tilemap` / `bake_static_sprites`."""

    MAX_SINGLE_SURFACE_PIXELS = 4096 * 4096
    AUTO_CHUNK_SIZE = 2048
    sort_y = float("-inf")     # draws before ordinary sprites with the same z_index

    def __init__(self, z_index=-100, chunk_size=None, opaque=False, background=(0, 0, 0)):
        super().__init__()
        self.z_index = z_index
        self.chunk_size = chunk_size
        self.opaque = opaque
        self.background = background
        self.bounds = None           # (left, top, right, bottom) in world pixels
        self.item_count = 0
        self._chunks = {}            # (cx, cy) -> pygame.Surface
        self._origin = (0, 0)
        self._chunk_px = 0
        self._blit_flags = 0         # BLEND_PREMULTIPLIED when chunks hold premultiplied pixels

    @staticmethod
    def premultiplied_supported():
        """Whether translucent layers can be baked exactly on this pygame build
        (result of a one-time self-test; needs a display to have been created)."""
        return _premultiplied_supported()

    @property
    def chunk_count(self):
        return len(self._chunks)

    def clear(self):
        self._chunks.clear()
        self.bounds = None
        self.item_count = 0

    def bake(self, items):
        """Render `items` - an iterable of `(surface, world_x, world_y)` - into
        the layer. Later items draw over earlier ones. Replaces previous content."""
        self.clear()
        placed = []
        for surface, x, y in items:
            if surface is None:
                continue
            placed.append((prepare_surface(surface), round(x), round(y)))
        if not placed:
            return self

        left = min(x for _, x, _ in placed)
        top = min(y for _, _, y in placed)
        right = max(x + s.get_width() for s, x, _ in placed)
        bottom = max(y + s.get_height() for s, _, y in placed)
        width, height = right - left, bottom - top
        self.bounds = (left, top, right, bottom)
        self._origin = (left, top)
        self.item_count = len(placed)

        chunk = self.chunk_size
        if chunk is None:
            chunk = max(width, height) if width * height <= self.MAX_SINGLE_SURFACE_PIXELS else self.AUTO_CHUNK_SIZE
        self._chunk_px = max(1, int(chunk))
        cpx = self._chunk_px

        premultiplied = not self.opaque and _premultiplied_supported()
        self._blit_flags = pygame.BLEND_PREMULTIPLIED if premultiplied else 0
        premultiplied_copies = {}      # each distinct tile image is premultiplied once

        for surface, x, y in placed:
            source, flags = surface, 0
            if premultiplied and surface.get_flags() & pygame.SRCALPHA:
                source = premultiplied_copies.get(id(surface))
                if source is None:
                    source = premultiplied_copies[id(surface)] = _premultiply(surface)
                flags = pygame.BLEND_PREMULTIPLIED
            rx, ry = x - left, y - top
            for cx in range(rx // cpx, (rx + surface.get_width() - 1) // cpx + 1):
                for cy in range(ry // cpx, (ry + surface.get_height() - 1) // cpx + 1):
                    target = self._chunks.get((cx, cy))
                    if target is None:
                        cw = min(cpx, width - cx * cpx)
                        ch = min(cpx, height - cy * cpx)
                        target = self._new_chunk(cw, ch)
                        self._chunks[(cx, cy)] = target
                    target.blit(source, (rx - cx * cpx, ry - cy * cpx), special_flags=flags)

        DebugManager.log_info(
            f"BakedLayer z={self.z_index}: baked {self.item_count} sprites into {len(self._chunks)} "
            f"chunk(s), {width}x{height}px", source="Render")
        return self

    def _new_chunk(self, width, height):
        if self.opaque:
            surface = pygame.Surface((width, height))
            surface.fill(self.background)
            return surface.convert() if pygame.display.get_surface() is not None else surface
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        return surface.convert_alpha() if pygame.display.get_surface() is not None else surface

    def draw_world(self, screen, ox, oy, alpha):
        if not self._chunks:
            return 0
        left, top = self._origin
        cpx = self._chunk_px
        sw, sh = screen.get_size()
        # Visible chunk index range (view expressed relative to the layer origin).
        cx0 = max(0, (ox - left) // cpx)
        cy0 = max(0, (oy - top) // cpx)
        cx1 = (ox + sw - left) // cpx
        cy1 = (oy + sh - top) // cpx
        calls = 0
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                surface = self._chunks.get((cx, cy))
                if surface is not None:
                    screen.blit(surface, (left + cx * cpx - ox, top + cy * cpx - oy),
                                special_flags=self._blit_flags)
                    calls += 1
        return calls


def bake_tilemap(grid, tileset, tile_size, origin=(0, 0), z_index=-100, chunk_size=None,
                 opaque=False, background=(0, 0, 0), name="BakedTilemap"):
    """A static GameObject holding a BakedLayer of a tile grid.

    `grid` is a list of rows of tile ids (None or -1 = empty cell); `tileset`
    maps ids to surfaces (dict, or list indexed by id). `tile_size` is an int or
    (w, h). Tiles are placed on a regular grid starting at `origin` (world px).
    """
    tile_w, tile_h = (tile_size, tile_size) if isinstance(tile_size, int) else tile_size
    items = []
    for row_index, row in enumerate(grid):
        for col_index, tile_id in enumerate(row):
            if tile_id is None or tile_id == -1:
                continue
            try:
                surface = tileset[tile_id]
            except (KeyError, IndexError):
                DebugManager.log_warning(f"bake_tilemap: tile id {tile_id!r} isn't in the tileset.", source="Render")
                continue
            items.append((surface, origin[0] + col_index * tile_w, origin[1] + row_index * tile_h))

    go = GameObject(name=name, is_static=True)
    go.add_component(BakedLayer(z_index=z_index, chunk_size=chunk_size, opaque=opaque, background=background)).bake(items)
    return go


def bake_static_sprites(scene, chunk_size=None, z_range=None, opaque=False, name_prefix="Baked"):
    """Bake every static, non-animated SpriteRenderer already in `scene` into
    one BakedLayer per z_index, then disable the original renderers (their
    GameObjects - colliders, scripts - keep working). Returns the new layer
    GameObjects. `z_range=(lo, hi)` limits which z_index values are baked."""
    from engine.components.animator import Animator
    from engine.components.sprite_renderer import SpriteRenderer

    groups = {}
    for renderer in scene.get_components(SpriteRenderer):
        go = renderer.game_object
        if not go._effective_static or not renderer.enabled or renderer._sprite is None:
            continue
        if renderer._static_bounds is None or go.get_component(Animator) is not None:
            continue
        if z_range is not None and not (z_range[0] <= renderer.z_index <= z_range[1]):
            continue
        groups.setdefault(renderer.z_index, []).append(renderer)

    layers = []
    for z, renderers in sorted(groups.items()):
        renderers.sort(key=lambda r: (r._static_sort_y, r._seq))
        items = [(r._dsurf, r._dx, r._dy) for r in renderers]
        go = GameObject(name=f"{name_prefix}_z{z}", is_static=True)
        go.add_component(BakedLayer(z_index=z, chunk_size=chunk_size, opaque=opaque)).bake(items)
        scene.add_game_object(go)
        for renderer in renderers:
            renderer.enabled = False
        layers.append(go)
    return layers
