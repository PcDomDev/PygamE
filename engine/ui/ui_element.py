"""Base class for every UI component (UIPanel, UIText, UIButton, ...)."""
import pygame

from engine.components.component import Component


class UIElement(Component):
    """A UIElement's position comes from its GameObject's Transform, same
    as everything else in the engine - but for UI, that position is
    interpreted as SCREEN space (pixels from the window's top-left corner),
    not world space. UI draws in its own pass, after the world and after
    the camera offset has already been applied to everything else, so a
    UIElement always stays in the same place on screen no matter where the
    camera is looking.

    A plain UIElement with no subclass behaviour draws nothing - use
    UIPanel, UIText, or UIButton, or subclass this and override draw().
    """

    def __init__(self, width=100, height=30, visible=True, draw_order=0):
        super().__init__()
        self.width = width
        self.height = height
        self.visible = visible
        # Among UI elements specifically (not update_order - drawing here
        # is a separate pass from the physics/gameplay update loop).
        # Lower draws first / behind.
        self.draw_order = draw_order

    @property
    def rect(self):
        """Current screen-space rect, from the owning transform's position
        (top-left corner) and this element's width/height."""
        pos = self.game_object.transform.position
        return pygame.Rect(round(pos.x), round(pos.y), self.width, self.height)

    def contains_point(self, point_x, point_y):
        return self.rect.collidepoint(round(point_x), round(point_y))

    def draw(self, screen):
        """Override in a subclass. Called once per frame, only while
        `visible`, by Scene's UI render pass - after the world has been
        drawn, in screen space, never offset by the camera."""
        pass
