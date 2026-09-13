"""UIPanel: the simplest UI building block - a plain rectangular
background, optionally bordered. Used on its own (a colored box, a
window background) or as a visual base other elements build on."""
import pygame

from engine.ui.ui_element import UIElement
from engine.ui.ui_style import UIStyle


class UIPanel(UIElement):
    def __init__(self, width=200, height=100, style=None, **kwargs):
        super().__init__(width=width, height=height, **kwargs)
        self.style = style or UIStyle.default()

    def draw(self, screen):
        if not self.visible:
            return
        rect = self.rect
        pygame.draw.rect(screen, self.style.background_color, rect)
        if self.style.border_width > 0:
            pygame.draw.rect(screen, self.style.border_color, rect, width=self.style.border_width)
