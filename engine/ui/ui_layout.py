"""UILayoutGroup: arranges a list of UI GameObjects in a vertical or
horizontal stack, repositioning them every frame.

This engine has no parent-child transform hierarchy, so this is not a
true layout container the way Unity's would be - it's a simpler
positioning helper. Attach it to its own GameObject, add_item() every UI
GameObject you want stacked, and it keeps their transform.position lined
up in a column (or row) relative to its own position.
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
        origin = self.game_object.transform.position
        cursor = 0.0

        for item in self._items:
            if not item.active:
                continue
            element = item.get_component(UIElement)
            if element is None:
                continue

            if self.direction == "vertical":
                item.transform.position.x = origin.x
                item.transform.position.y = origin.y + cursor
                cursor += element.height + self.spacing
            else:
                item.transform.position.x = origin.x + cursor
                item.transform.position.y = origin.y
                cursor += element.width + self.spacing
