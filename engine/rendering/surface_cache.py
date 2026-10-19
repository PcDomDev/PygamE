"""Surface conversion and cached sprite variants.

Two related problems, one module:

1. `prepare_surface()` converts an image to the display's pixel format once
   (`convert()` / `convert_alpha()`). Blitting a surface in a different format
   forces SDL to convert *on every blit* - often the single biggest avoidable
   cost in a pygame game. Conversions are memoized, and an already-converted
   surface is recognized and returned as-is.

2. `SurfaceCache` remembers rotated/scaled copies of a sprite. Scaling and
   rotating are expensive, and Animator swaps frames constantly; the old
   one-entry cache per renderer was thrown away on every frame change. This
   one is shared by all renderers (fifty enemies using the same frames at the
   same scale share one set of variants) and bounded (LRU).
"""
import weakref
from collections import OrderedDict

import pygame

_prepared = weakref.WeakKeyDictionary()   # original surface -> converted surface
_converted = weakref.WeakSet()            # surfaces that are already display-format


def prepare_surface(surface):
    """`surface` in the display's pixel format (a converted copy, or the same
    object if it's already converted / no display exists yet)."""
    if surface is None or surface in _converted:
        return surface
    cached = _prepared.get(surface)
    if cached is not None:
        return cached
    if pygame.display.get_surface() is None:
        return surface            # no video mode yet; converted later, at start()
    try:
        if surface.get_flags() & pygame.SRCALPHA:
            converted = surface.convert_alpha()
        else:
            converted = surface.convert()
    except pygame.error:
        return surface
    _prepared[surface] = converted
    _converted.add(converted)
    return converted


class SurfaceCache:
    """LRU cache of `(sprite, rotation, scale)` -> transformed surface."""

    def __init__(self, max_entries=512):
        self.max_entries = max_entries
        self._entries = OrderedDict()
        self.hits = 0
        self.misses = 0

    def __len__(self):
        return len(self._entries)

    def clear(self):
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def get_transformed(self, sprite, rotation, scale_x, scale_y, rotation_step=1.0):
        """`sprite` scaled then rotated.

        Rotation is clockwise-positive degrees (the engine's Y-down convention;
        pygame's own is counter-clockwise, hence the negation). It is quantized
        to `rotation_step` degrees (0 = exact to 1/1000 degree) so a smoothly
        spinning sprite reuses a bounded set of variants instead of creating a
        new surface every frame. A negative scale mirrors the sprite.
        """
        if rotation_step > 0:
            rot_index = round(rotation / rotation_step)
            rot = (rot_index * rotation_step) % 360.0
            rot_key = rot_index
        else:
            rot = rotation % 360.0
            rot_key = round(rot, 3)
        key = (id(sprite), rot_key, round(scale_x, 3), round(scale_y, 3))

        entry = self._entries.get(key)
        if entry is not None and entry[0] is sprite:
            self._entries.move_to_end(key)
            self.hits += 1
            return entry[1]

        self.misses += 1
        result = sprite
        if scale_x != 1.0 or scale_y != 1.0:
            width, height = sprite.get_size()
            new_w = max(1, round(width * abs(scale_x)))
            new_h = max(1, round(height * abs(scale_y)))
            if (new_w, new_h) != (width, height):
                result = pygame.transform.scale(result, (new_w, new_h))
            if scale_x < 0 or scale_y < 0:
                result = pygame.transform.flip(result, scale_x < 0, scale_y < 0)
        if rot % 360.0:
            result = pygame.transform.rotate(result, -rot)

        # The entry keeps a strong reference to `sprite`, so its id() can't be
        # recycled by another surface while the entry exists.
        self._entries[key] = (sprite, result)
        if len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return result


sprite_cache = SurfaceCache()
