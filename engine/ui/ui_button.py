"""UIButton: a clickable rectangle with a text label. Fires callbacks on
click - subscribe via `button.on_click.append(callback)`, the same pattern
BoxCollider2D uses for on_trigger_enter."""
import pygame

from engine.core.debug_manager import DebugManager
from engine.input.input_manager import Input
from engine.ui.ui_element import UIElement
from engine.ui.ui_style import UIStyle
from engine.utils.fonts import get_font, render_text


class UIButton(UIElement):
    def __init__(self, text="Button", width=140, height=40, style=None, **kwargs):
        super().__init__(width=width, height=height, **kwargs)
        self.text = text
        self.style = style or UIStyle.default()
        self._font = get_font(self.style.font_name, self.style.font_size)

        # list of callback(button) -> None - append to subscribe, more than
        # one listener is fine, same pattern as BoxCollider2D.on_trigger_enter
        self.on_click = []

        self.is_hovered = False
        self.is_pressed = False

    def update(self, delta_time):
        if not self.is_visible:
            # A hidden button (or one inside a hidden panel) can't be clicked.
            self.is_hovered = False
            self.is_pressed = False
            return

        mouse_x, mouse_y = Input.mouse_position()
        self.is_hovered = self.contains_point(mouse_x, mouse_y)

        if self.is_hovered and Input.is_mouse_just_pressed(0):
            self.is_pressed = True

        if self.is_pressed and Input.is_mouse_just_released(0):
            self.is_pressed = False
            if self.is_hovered:
                # A "click" is press-then-release while still over the
                # button - the standard button gesture. Moving off before
                # releasing cancels it, same as most UI toolkits.
                self._dispatch_click()
        elif not Input.is_mouse_pressed(0):
            self.is_pressed = False

    def _dispatch_click(self):
        for callback in list(self.on_click):  # copy: a callback may unsubscribe itself
            try:
                callback(self)
            except Exception as exc:  # noqa: BLE001 - a bad callback must not crash the game
                DebugManager.log_error(f"UIButton '{self.text}' click callback raised {exc!r}")

    def draw(self, screen):
        if not self.visible:
            return

        if self.is_pressed:
            color = self.style.pressed_color
        elif self.is_hovered:
            color = self.style.hover_color
        else:
            color = self.style.background_color

        rect = self.rect
        pygame.draw.rect(screen, color, rect)
        if self.style.border_width > 0:
            pygame.draw.rect(screen, self.style.border_color, rect, width=self.style.border_width)

        if self.text:
            text_surface = render_text(self._font, self.text, self.style.text_color)
            text_x = rect.x + (rect.width - text_surface.get_width()) / 2
            text_y = rect.y + (rect.height - text_surface.get_height()) / 2
            screen.blit(text_surface, (round(text_x), round(text_y)))
