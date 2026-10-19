"""UIText: renders a text string at a screen position. Width/height are
measured from the rendered text unless given explicitly (and follow later
`text` changes when they were measured).

The rendered surface is cached (see engine/utils/fonts.py), so a label that
doesn't change costs a blit per frame, not a font render."""
from engine.ui.ui_element import UIElement
from engine.ui.ui_style import UIStyle
from engine.utils.fonts import get_font, render_text


class UIText(UIElement):
    def __init__(self, text="", style=None, align="left", width=None, height=None, **kwargs):
        self.style = style or UIStyle.default()
        self._font = get_font(self.style.font_name, self.style.font_size)
        self._auto_width = width is None
        self._auto_height = height is None

        measured_w, measured_h = self._font.size(text) if text else (0, self.style.font_size)
        super().__init__(width=width if width is not None else measured_w,
                         height=height if height is not None else measured_h,
                         **kwargs)

        self._text = text
        # "left" / "center" / "right" - only affects horizontal placement
        # within this element's own width; vertical placement is always
        # centered within its height.
        self.align = align

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        value = str(value)
        if value == self._text:
            return
        self._text = value
        measured_w, measured_h = self._font.size(value) if value else (0, self.style.font_size)
        if self._auto_width:
            self.width = measured_w
        if self._auto_height:
            self.height = measured_h

    def set_text(self, text):
        self.text = text

    def draw(self, screen):
        if not self.visible or not self._text:
            return

        surface = render_text(self._font, self._text, self.style.text_color)
        rect = self.rect

        if self.align == "center":
            x = rect.x + (self.width - surface.get_width()) / 2
        elif self.align == "right":
            x = rect.x + self.width - surface.get_width()
        else:
            x = rect.x

        y = rect.y + (self.height - surface.get_height()) / 2
        screen.blit(surface, (round(x), round(y)))
