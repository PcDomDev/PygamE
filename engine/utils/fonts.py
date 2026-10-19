"""Font cache. `pygame.font.SysFont` scans the system for a matching font on
every call (milliseconds); UI elements and debug overlays used to call it per
instance. Fonts are immutable once built, so one shared instance per
(name, size, bold) is enough."""
import pygame

_fonts = {}


def get_font(name=None, size=20, bold=False):
    key = (name, size, bold)
    font = _fonts.get(key)
    if font is None:
        if not pygame.font.get_init():
            pygame.font.init()
        font = pygame.font.SysFont(name, size, bold=bold)
        _fonts[key] = font
    return font


# Rendered text is a Surface; re-rendering the same string every frame (a HUD
# label, the debug overlay) is pure waste. Small LRU keyed by everything that
# affects the pixels. The key holds the font object itself, so a cached entry
# can never be confused with a different font that reused a memory address.
from collections import OrderedDict

_text_cache = OrderedDict()
MAX_TEXT_CACHE = 256


def render_text(font, text, color, antialias=True):
    key = (font, text, tuple(color), antialias)
    surface = _text_cache.get(key)
    if surface is None:
        surface = font.render(text, antialias, color)
        _text_cache[key] = surface
        if len(_text_cache) > MAX_TEXT_CACHE:
            _text_cache.popitem(last=False)
    else:
        _text_cache.move_to_end(key)
    return surface
