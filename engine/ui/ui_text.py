"""UIText: renders a text string at a screen position. Width/height are
measured from the rendered text unless given explicitly."""
import pygame

from engine.ui.ui_element import UIElement
from engine.ui.ui_style import UIStyle


class UIText(UIElement):
    def __init__(self, text="", style=None, align="left", width=None, height=None, **kwargs):
        self.style = style or UIStyle.default()
        self._font = pygame.font.SysFont(self.style.font_name, self.style.font_size)

        measured_w, measured_h = self._font.size(text) if text else (0, self.style.font_size)
        super().__init__(width=width if width is not None else measured_w,
                          height=height if height is not None else measured_h,
                          **kwargs)

        self.text = text
        # "left" / "center" / "right" - only affects horizontal placement
        # within this element's own width; vertical placement is always
        # centered within its height.
        self.align = align

    def set_text(self, text):
        self.text = text

    def draw(self, screen):
        if not self.visible or not self.text:
            return

        surface = self._font.render(self.text, True, self.style.text_color)
        pos = self.game_object.transform.position

        if self.align == "center":
            x = pos.x + (self.width - surface.get_width()) / 2
        elif self.align == "right":
            x = pos.x + self.width - surface.get_width()
        else:
            x = pos.x

        y = pos.y + (self.height - surface.get_height()) / 2
        screen.blit(surface, (round(x), round(y)))
