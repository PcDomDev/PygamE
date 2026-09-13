from engine.components.component import Component
from engine.utils.vector2 import Vector2


class Transform(Component):
    """Position, rotation, and scale. Every GameObject gets exactly one of
    these automatically (see GameObject.__init__) - you never need to add
    it yourself.

    - `position` is a Vector2, in world-space pixels.
    - `rotation` is a float in degrees (0 = unrotated). Nothing in the base
      engine reads this yet (SpriteRenderer blits axis-aligned), but it's
      here so rotation is a well-defined property of every object rather
      than something each new component has to invent its own convention
      for. A rotated SpriteRenderer is a natural next extension - see
      docs/ARCHITECTURE.md.
    - `scale` is a Vector2 (x, y), 1.0 = original size.

    `GameObject.x` / `GameObject.y` remain as thin convenience aliases for
    `transform.position.x` / `.y`, so existing code that used the old flat
    attributes keeps working - but `transform` is the canonical source of
    truth, and new code should prefer it.
    """

    def __init__(self, x=0.0, y=0.0, rotation=0.0, scale_x=1.0, scale_y=1.0):
        super().__init__()
        self.position = Vector2(x, y)
        self.rotation = rotation
        self.scale = Vector2(scale_x, scale_y)

    def translate(self, dx, dy):
        self.position.x += dx
        self.position.y += dy

    def __repr__(self):
        return f"Transform(pos={self.position}, rot={self.rotation:.1f}, scale={self.scale})"
