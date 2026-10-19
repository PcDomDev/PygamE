"""UIElement: base class for everything drawn in the UI pass.

Screen-space by default: UI is drawn on top of the world, *after* everything
else, with no camera offset - the camera scrolling never moves a HUD. Two
placement modes:

  - Legacy / absolute (`anchor=None`, default): the GameObject's position is the
    element's top-left corner in screen pixels. If the GameObject is parented to
    another UI element, the position is relative to it (world = parent + local).

  - Anchored (`anchor="TopLeft" | "Center" | "BottomRight" | ...`): the element
    is pinned to that point of its *reference rectangle* - the nearest ancestor UI
    element's rect, or the whole screen - and the GameObject's position becomes an
    offset from the anchor. `pivot` picks which point *of the element* sits on the
    anchor (defaults to the anchor itself, so `anchor="BottomRight"` at (-10, -10)
    hugs the corner with a 10px margin, at any window size):

        hud = UIText("HP 100", anchor="TopLeft")           # at (10, 10) -> 10px margins
        score = UIText("0", anchor="TopRight", pivot="TopRight")
        menu = UIPanel(300, 200, anchor="Center")           # centered on screen

Anchor names are case/underscore-insensitive; see engine/utils/anchors.py.

World-space (`world_space=True`): the element lives in the *world* and is drawn
with the camera offset, e.g. a health bar floating above an enemy. Parent its
GameObject to the enemy and it follows (with physics interpolation). `pivot`
then says which point of the element sits on the object's position (default
"Center").

`visible` cascades: hiding a panel hides everything parented under it.
"""
import pygame

from engine.components.component import Component
from engine.core.game_time import Time
from engine.utils.anchors import ANCHOR_FRACTIONS, normalize_anchor


class UIElement(Component):
    def __init__(self, width=100, height=30, visible=True, draw_order=0,
                 anchor=None, pivot=None, world_space=False):
        super().__init__()
        self.width = width
        self.height = height
        self.visible = visible
        # Lower draws first (further back). Elements with equal draw_order draw
        # in the order they were added to the scene, parents before children.
        self.draw_order = draw_order
        self.world_space = world_space
        self._anchor = normalize_anchor(anchor) if anchor is not None else None
        if pivot is not None:
            self._pivot = normalize_anchor(pivot)
        elif self._anchor is not None:
            self._pivot = self._anchor
        else:
            self._pivot = "center" if world_space else "topleft"
        self._camera_offset = (0, 0)

    # -- placement --------------------------------------------------------------

    @property
    def anchor(self):
        return self._anchor

    @anchor.setter
    def anchor(self, value):
        self._anchor = normalize_anchor(value) if value is not None else None

    @property
    def pivot(self):
        return self._pivot

    @pivot.setter
    def pivot(self, value):
        self._pivot = normalize_anchor(value)

    @property
    def z_index(self):
        """Sort key for world-space elements (same scale as SpriteRenderer.z_index)."""
        return self.draw_order

    def _parent_element(self):
        parent = self.game_object.transform._parent
        while parent is not None:
            element = parent.game_object.get_component(UIElement)
            if element is not None:
                return element
            parent = parent._parent
        return None

    @staticmethod
    def _screen_rect():
        surface = pygame.display.get_surface()
        return surface.get_rect() if surface is not None else pygame.Rect(0, 0, 800, 600)

    @property
    def rect(self):
        """This element's rectangle in *screen* coordinates."""
        transform = self.game_object.transform

        if self.world_space:
            wx, wy = transform.get_render_xy(Time.alpha)
            fx, fy = ANCHOR_FRACTIONS[self._pivot]
            return pygame.Rect(round(wx - fx * self.width - self._camera_offset[0]),
                               round(wy - fy * self.height - self._camera_offset[1]),
                               self.width, self.height)

        if self._anchor is None:
            wx, wy = transform.get_world_xy()
            return pygame.Rect(round(wx), round(wy), self.width, self.height)

        parent = self._parent_element()
        ref = parent.rect if parent is not None else self._screen_rect()
        ax, ay = ANCHOR_FRACTIONS[self._anchor]
        px, py = ANCHOR_FRACTIONS[self._pivot]
        local = transform._local
        return pygame.Rect(round(ref.x + ax * ref.width + local.x - px * self.width),
                           round(ref.y + ay * ref.height + local.y - py * self.height),
                           self.width, self.height)

    def contains_point(self, point_x, point_y):
        return self.rect.collidepoint(point_x, point_y)

    @property
    def is_visible(self):
        """True if this element *and every UI ancestor* is visible."""
        if not self.visible:
            return False
        parent = self._parent_element()
        return parent is None or parent.is_visible

    # -- drawing ---------------------------------------------------------------

    def draw(self, screen):
        """Draw this element. Subclasses override; `self.rect` is where."""

    def draw_world(self, screen, offset_x, offset_y, alpha):
        # Called by the world pass for every UIElement; only world-space ones draw here.
        if not self.world_space or not self.is_visible:
            return None
        self._camera_offset = (offset_x, offset_y)
        self.draw(screen)
        return 1
