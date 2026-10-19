"""Data passed to physics callbacks."""


class Collision2D:
    """Argument of `on_collision_enter/stay/exit(collision)` component hooks.

    `collider` is the receiving side's collider, `other` the collider it
    touched. `normal` is the contact normal pointing away from `other` toward
    the receiver (e.g. (0, -1) when the receiver landed on top of `other`).
    """

    __slots__ = ("collider", "other", "normal")

    def __init__(self, collider, other, normal):
        self.collider = collider
        self.other = other
        self.normal = normal

    @property
    def game_object(self):
        """The GameObject that was touched."""
        return self.other.game_object

    def __repr__(self):
        return f"Collision2D(with={self.other.game_object.name!r}, normal={self.normal})"
