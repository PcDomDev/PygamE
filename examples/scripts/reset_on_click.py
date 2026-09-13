"""ResetOnClick: attach to any GameObject; remembers its starting position
and exposes reset_position() to snap back to it - wire a UIButton's
on_click list to reset_position to use it as a simple "restart" button.

Lives in scripts/, not engine/components/, for the same reason as
everything else here: it's a small piece of game behaviour, not a
generic engine capability.
"""
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D


class ResetOnClick(Component):
    def start(self):
        self._start_position = self.game_object.transform.position.copy()

    def reset_position(self, _button=None):
        """Signature accepts an optional argument so it can be used
        directly as a UIButton.on_click callback (which calls back with
        the button itself) or called with no arguments from anywhere else."""
        self.game_object.transform.position = self._start_position.copy()
        rigidbody = self.game_object.get_component(Rigidbody2D)
        if rigidbody:
            rigidbody.stop()
