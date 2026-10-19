import math

from engine.components.component import Component
from engine.core.game_time import Time
from engine.utils.vector2 import Vector2


class Camera(Component):
    """A virtual 2D camera.

    Design: the camera never touches its target's transform. Instead, it
    tracks its own `position` (the world point currently at the center of
    the screen) and the scene's render pass subtracts that from every sprite's
    world position before drawing. Moving the *view* rather than the *player*
    is what makes jumping look natural.

    Parameters:
      - `target`: the GameObject to follow (usually the player), or None.
      - `follow_speed`: how quickly the camera closes the distance to the
        target when smooth_follow is on. Higher = snappier/less lag.
      - `smooth_follow`: True to ease towards the target every frame; False
        to snap the camera exactly onto the target every frame ("hard follow").
      - `position`: optional starting world position; only matters before
        `start()` runs (which snaps immediately to the target, if any).

    The camera follows the target's *render* position - the same interpolated
    position its sprite is drawn at - so on a 144 Hz monitor the camera and the
    sprite move in lock-step instead of the camera stepping at the 60 Hz physics
    rate while the sprite glides.

    No target: the world behaves exactly as if there were no camera at all
    (`get_offset()` returns (0, 0), nothing scrolls).
    """

    update_order = 100  # after physics and gameplay, so it reads final, settled positions

    def __init__(self, target=None, follow_speed=5.0, smooth_follow=True, position=None):
        super().__init__()
        self.target = target
        self.follow_speed = follow_speed
        self.smooth_follow = smooth_follow
        self.position = position.copy() if position is not None else Vector2(0.0, 0.0)

    def _target_xy(self):
        return self.target.transform.get_render_xy(Time.alpha)

    def start(self):
        self.snap_to_target()

    def set_target(self, target, snap=True):
        """Switch which GameObject the camera follows. `snap=True` (default)
        re-centers immediately; `snap=False` eases into the new target."""
        self.target = target
        if snap:
            self.snap_to_target()

    def snap_to_target(self):
        """Instantly move onto the target's current position (no easing).
        Useful after a teleport/respawn."""
        if self.target is not None:
            x, y = self._target_xy()
            self.position = Vector2(x, y)

    def update(self, delta_time):
        if self.target is None:
            return  # No target: camera does not move, world renders unshifted.

        tx, ty = self._target_xy()
        if self.smooth_follow and self.follow_speed > 0:
            # Exponential ("smooth damp") interpolation: converges at the same
            # *rate* regardless of frame rate and can never overshoot.
            t = 1.0 - math.exp(-self.follow_speed * delta_time)
            self.position = self.position.lerp(Vector2(tx, ty), t)
        else:
            self.position = Vector2(tx, ty)

    def get_offset(self, screen_width, screen_height):
        """The world-space point that appears at the screen's top-left corner.
        Always (0, 0) when there's no target."""
        if self.target is None:
            return Vector2(0.0, 0.0)
        return Vector2(
            self.position.x - screen_width / 2,
            self.position.y - screen_height / 2,
        )

    def get_view_bounds(self, screen_width, screen_height):
        """(left, top, right, bottom) of the world region currently on screen."""
        offset = self.get_offset(screen_width, screen_height)
        return offset.x, offset.y, offset.x + screen_width, offset.y + screen_height

    def world_to_screen(self, world_pos, screen_width, screen_height):
        return world_pos - self.get_offset(screen_width, screen_height)

    def screen_to_world(self, screen_pos, screen_width, screen_height):
        return screen_pos + self.get_offset(screen_width, screen_height)
