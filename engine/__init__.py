"""The engine package: everything here is reusable and game-agnostic.

Nothing under `engine/` should ever import from `scenes/` or `scripts/` -
the engine must not know what a specific character, enemy, or collectible
in *your* game is. That knowledge belongs in those two packages instead.
"""
