import math

from engine.components.component import Component
from engine.utils.vector2 import Vector2


class Camera(Component):
    """A virtual 2D camera.

    Design: the camera never touches its target's transform. Instead, it
    tracks its own `position` (the world point currently at the center of
    the screen) and Scene.render() subtracts that from every sprite's world
    position before drawing. Moving the *view* rather than the *player* is
    what makes jumping look natural - the player's own physics are
    completely undisturbed by the camera, and what you see on screen is
    just "the world, shifted."

    Parameters:
      - `target`: the GameObject to follow (usually the player), or None.
      - `follow_speed`: how quickly the camera closes the distance to the
        target when smooth_follow is on. Higher = snappier/less lag.
      - `smooth_follow`: True to ease towards the target every frame; False
        to snap the camera exactly onto the target's position every frame
        ("hard follow").
      - `position`: optional starting world position; only matters before
        `start()` runs (which snaps immediately to the target, if any, so
        the camera doesn't visibly fly in from wherever it started).

    No target: per the spec, the world should behave exactly as if there
    were no camera at all. `get_offset()` returns (0, 0) whenever `target`
    is None, so rendering falls back to raw, unshifted world coordinates -
    nothing scrolls, and the player (or anything else) moves independently.
    """

    update_order = 100  # after physics and gameplay, so it reads final, settled positions

    def __init__(self, target=None, follow_speed=5.0, smooth_follow=True, position=None):
        super().__init__()
        self.target = target
        self.follow_speed = follow_speed
        self.smooth_follow = smooth_follow
        self.position = position.copy() if position is not None else Vector2(0.0, 0.0)

    def start(self):
        self.snap_to_target()

    def set_target(self, target, snap=True):
        """Switch which GameObject the camera follows. `snap=True` (default)
        re-centers immediately; `snap=False` eases into the new target from
        wherever the camera currently is."""
        self.target = target
        if snap:
            self.snap_to_target()

    def snap_to_target(self):
        """Instantly move the camera onto the target's current position
        (no easing). Useful after a teleport/respawn."""
        if self.target is not None:
            self.position = self.target.transform.position.copy()

    def update(self, delta_time):
        if self.target is None:
            return  # No target: camera does not move, world renders unshifted.

        target_pos = self.target.transform.position

        if self.smooth_follow and self.follow_speed > 0:
            # Exponential ("smooth damp") interpolation instead of a naive
            # `lerp(pos, target, follow_speed * dt)`. The naive version's
            # effective smoothing changes with framerate - at low FPS,
            # `follow_speed * dt` can exceed 1 and overshoot the target,
            # which reads as camera shake. This formulation converges at the
            # same *rate* regardless of frame rate, so it can't overshoot.
            t = 1.0 - math.exp(-self.follow_speed * delta_time)
            self.position = self.position.lerp(target_pos, t)
        else:
            self.position = target_pos.copy()

    def get_offset(self, screen_width, screen_height):
        """The world-space point that will appear at the screen's top-left
        corner. Scene.render() subtracts this from every sprite's world
        position. Always (0, 0) when there's no target, so the world renders
        exactly as it would with no camera at all."""
        if self.target is None:
            return Vector2(0.0, 0.0)
        return Vector2(
            self.position.x - screen_width / 2,
            self.position.y - screen_height / 2,
        )

    def world_to_screen(self, world_pos, screen_width, screen_height):
        return world_pos - self.get_offset(screen_width, screen_height)
