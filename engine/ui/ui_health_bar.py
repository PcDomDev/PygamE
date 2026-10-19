"""UIHealthBar: a filled bar for health, stamina, cooldowns, loading.

    hp = UIHealthBar(200, 20, max_value=100, anchor="TopLeft", show_text=True)
    hud.add_component(hp)
    hp.value = 60                       # or hp.set_value(60), or bind it:
    hp.bind(lambda: player.health)      # re-read every frame

As a HUD element (screen space) it anchors like any UIElement. As a bar floating
over a character, parent its GameObject to that character and make it world-space:

    bar_go = GameObject(0, -28, parent=enemy)
    bar_go.add_component(UIHealthBar(40, 6, world_space=True, pivot="Center"))

Options: the fill colour switches to `low_color` under `low_threshold` (a
fraction of max); `smooth_speed` (fraction of the bar per second, 0 = instant)
makes the fill glide instead of jumping; `trail_color` draws a lagging chip of
"recently lost" health behind the fill, the way fighting games do.
"""
import pygame

from engine.ui.ui_element import UIElement
from engine.utils.fonts import get_font, render_text


class UIHealthBar(UIElement):
    def __init__(self, width=200, height=20, max_value=100.0, value=None,
                 fill_color=(80, 200, 90), low_color=(215, 65, 65), low_threshold=0.3,
                 background_color=(35, 35, 40), border_color=(12, 12, 15), border_width=2,
                 trail_color=None, smooth_speed=0.0, show_text=False,
                 text_color=(245, 245, 245), font_size=None, **kwargs):
        super().__init__(width=width, height=height, **kwargs)
        self.max_value = float(max_value)
        self._value = self.max_value if value is None else max(0.0, min(float(value), self.max_value))
        self.fill_color = fill_color
        self.low_color = low_color
        self.low_threshold = low_threshold
        self.background_color = background_color
        self.border_color = border_color
        self.border_width = border_width
        self.trail_color = trail_color
        self.smooth_speed = smooth_speed
        self.show_text = show_text
        self.text_color = text_color
        self._font = get_font(None, font_size or max(10, int(height * 0.8)))

        self._shown = self.ratio         # the fill actually drawn (glides toward `ratio`)
        self._trail = self.ratio         # the lagging "damage" chip
        self._getter = None

    # -- value -----------------------------------------------------------------

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_value):
        self._value = max(0.0, min(float(new_value), self.max_value))
        if self.smooth_speed <= 0:
            self._shown = self.ratio
            self._trail = min(self._trail, self.ratio) if self.trail_color is None else self._trail

    def set_value(self, new_value):
        self.value = new_value

    def set_max_value(self, max_value, keep_ratio=False):
        ratio = self.ratio
        self.max_value = max(1e-9, float(max_value))
        self._value = ratio * self.max_value if keep_ratio else min(self._value, self.max_value)

    @property
    def ratio(self):
        """Fill fraction 0..1 (the true value, ignoring smoothing)."""
        return self._value / self.max_value if self.max_value > 0 else 0.0

    @property
    def displayed_ratio(self):
        return self._shown

    def bind(self, getter):
        """Read the value from `getter()` every frame (None to unbind)."""
        self._getter = getter

    # -- update / draw ---------------------------------------------------------

    def update(self, delta_time):
        if self._getter is not None:
            self.value = self._getter()

        target = self.ratio
        if self.smooth_speed > 0:
            step = self.smooth_speed * delta_time
            if self._shown < target:
                self._shown = min(target, self._shown + step)
            else:
                self._shown = max(target, self._shown - step)
        else:
            self._shown = target

        if self.trail_color is not None:
            if self._trail < self._shown:
                self._trail = self._shown              # healing: chip snaps up
            else:
                self._trail = max(self._shown, self._trail - 0.6 * delta_time)

    def draw(self, screen):
        if not self.visible:
            return
        rect = self.rect
        pygame.draw.rect(screen, self.background_color, rect)

        inner = rect.inflate(-2 * self.border_width, -2 * self.border_width)
        if inner.width > 0 and inner.height > 0:
            if self.trail_color is not None and self._trail > self._shown:
                trail = pygame.Rect(inner.x, inner.y, round(inner.width * self._trail), inner.height)
                pygame.draw.rect(screen, self.trail_color, trail)
            fill_width = round(inner.width * self._shown)
            if fill_width > 0:
                color = self.low_color if self.ratio <= self.low_threshold else self.fill_color
                pygame.draw.rect(screen, color, pygame.Rect(inner.x, inner.y, fill_width, inner.height))

        if self.border_width > 0:
            pygame.draw.rect(screen, self.border_color, rect, width=self.border_width)

        if self.show_text:
            label = f"{round(self._value)}/{round(self.max_value)}"
            surface = render_text(self._font, label, self.text_color)
            screen.blit(surface, (rect.centerx - surface.get_width() // 2, rect.centery - surface.get_height() // 2))
