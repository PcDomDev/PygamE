"""Canvas: the root of a UI tree. Covers the whole screen, draws nothing itself,
and gives you one place to show/hide or reorder a group of elements.

    pause = GameObject(name="PauseMenu")
    canvas = pause.add_component(Canvas())
    panel_go = GameObject(0, 0, parent=pause)
    panel_go.add_component(UIPanel(300, 200, anchor="Center"))
    ...
    canvas.visible = False          # hides the panel and everything inside it

Every UIElement is screen-space and camera-independent even without a Canvas;
a Canvas simply adds the grouping. Children anchor to it exactly like to the
screen.
"""
from engine.ui.ui_element import UIElement


class Canvas(UIElement):
    def __init__(self, sort_order=0, visible=True):
        super().__init__(width=0, height=0, visible=visible, draw_order=sort_order)

    @property
    def rect(self):
        screen = self._screen_rect()
        return screen

    @property
    def width(self):
        return self._screen_rect().width

    @width.setter
    def width(self, value):
        pass

    @property
    def height(self):
        return self._screen_rect().height

    @height.setter
    def height(self, value):
        pass
