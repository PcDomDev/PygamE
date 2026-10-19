"""A small, shared bundle of visual parameters for UI elements - this is
the "styles" piece of the UI system. It's deliberately not a full theming
engine (no stylesheets, no cascading, no per-state style trees) - just
enough to avoid repeating five colour/font arguments on every single
UIPanel/UIText/UIButton you create, and to have one obvious place to
change if you want every button in your game to look different.
"""


class UIStyle:
    def __init__(self, background_color=(60, 60, 70), border_color=(120, 120, 130),
                 border_width=2, text_color=(240, 240, 240), font_name=None,
                 font_size=20, hover_color=(80, 80, 95), pressed_color=(40, 40, 50)):
        self.background_color = background_color
        self.border_color = border_color
        self.border_width = border_width
        self.text_color = text_color
        self.font_name = font_name  # None = pygame's built-in default font
        self.font_size = font_size
        self.hover_color = hover_color      # UIButton, while the mouse is over it
        self.pressed_color = pressed_color  # UIButton, while being clicked

    @staticmethod
    def default():
        return UIStyle()
