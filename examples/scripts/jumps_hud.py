"""JumpsHUD: keeps a UIText label showing how many jumps a
PlayerController has left before it needs to touch the ground again.

A small example of a script that *reads* from one component
(PlayerController) and *writes* to another (UIText) every frame -
demonstrating how gameplay, physics, and UI compose without any of
engine/components/player_controller.py, engine/ui/, or each other
needing to know the others exist.
"""
from engine.components.component import Component


class JumpsHUD(Component):
    def __init__(self, controller, label):
        super().__init__()
        self.controller = controller
        self.label = label

    def update(self, delta_time):
        self.label.set_text(f"Jumps: {self.controller.jumps_remaining}/{self.controller.max_jumps}")
