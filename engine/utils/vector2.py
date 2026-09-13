"""A minimal 2D vector used throughout the engine for positions, velocities,
and camera math.

Kept intentionally small: this is not meant to be a full math library, just
enough to stop the engine from passing raw (x, y) float pairs around and
losing track of which number means what.
"""

import math


class Vector2:
    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=0.0):
        self.x = x
        self.y = y

    # -- construction / conversion -----------------------------------------

    def copy(self):
        return Vector2(self.x, self.y)

    def as_tuple(self):
        return (self.x, self.y)

    def as_int_tuple(self):
        return (round(self.x), round(self.y))

    @staticmethod
    def zero():
        return Vector2(0.0, 0.0)

    @staticmethod
    def one():
        return Vector2(1.0, 1.0)

    # -- operators ------------------------------------------------------------

    def __add__(self, other):
        return Vector2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vector2(self.x - other.x, self.y - other.y)

    def __neg__(self):
        return Vector2(-self.x, -self.y)

    def __mul__(self, scalar):
        return Vector2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar):
        return Vector2(self.x / scalar, self.y / scalar)

    def __iadd__(self, other):
        self.x += other.x
        self.y += other.y
        return self

    def __isub__(self, other):
        self.x -= other.x
        self.y -= other.y
        return self

    def __eq__(self, other):
        if not isinstance(other, Vector2):
            return NotImplemented
        return self.x == other.x and self.y == other.y

    def __repr__(self):
        return f"Vector2({self.x:.3f}, {self.y:.3f})"

    # -- utility ---------------------------------------------------------------

    def length(self):
        return math.hypot(self.x, self.y)

    def normalized(self):
        length = self.length()
        if length == 0:
            return Vector2(0.0, 0.0)
        return Vector2(self.x / length, self.y / length)

    def lerp(self, other, t):
        """Linearly interpolate towards `other`. t is clamped to [0, 1]."""
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        return Vector2(self.x + (other.x - self.x) * t, self.y + (other.y - self.y) * t)
