"""UILayoutGroup: arranges a list of UI GameObjects in a vertical or
horizontal stack, repositioning them every frame.

This is a simple positioning helper, not a full layout container: attach it
to its own GameObject, add_item() every UI GameObject you want stacked, and it
keeps their positions lined up in a column (or row) starting at its own
*world* position. (Items are positioned in world space, so they may or may not
be children of the group's GameObject; anchored elements are better placed
with `anchor=` instead.)
"""
import warnings

from engine.components.component import Component
from engine.ui.ui_element import UIElement
from engine.utils.warnings import EngineWarning

_DIRECTIONS = {"vertical", "horizontal"}


class UILayoutGroup(Component):
    def __init__(self, direction="vertical", spacing=8):
        super().__init__()

        if direction not in _DIRECTIONS:
            warnings.warn(
                f"UILayoutGroup: unknown direction '{direction}', falling back to 'vertical'. "
                f"Valid directions: {sorted(_DIRECTIONS)}",
                EngineWarning,
                stacklevel=2,
            )
            direction = "vertical"

        self.direction = direction
        self.spacing = spacing
        self._items = []

    def add_item(self, game_object):
        self._items.append(game_object)
        return game_object

    def remove_item(self, game_object):
        if game_object in self._items:
            self._items.remove(game_object)

    def update(self, delta_time):
        origin_x, origin_y = self.game_object.transform.get_world_xy()
        cursor = 0.0

        for item in self._items:
            if not item.active:
                continue
            element = item.get_component(UIElement)
            if element is None:
                continue

            if self.direction == "vertical":
                item.transform.set_world_position(origin_x, origin_y + cursor)
                cursor += element.height + self.spacing
            else:
                item.transform.set_world_position(origin_x + cursor, origin_y)
                cursor += element.width + self.spacing
