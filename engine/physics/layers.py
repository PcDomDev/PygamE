"""Collision layers and masks.

Every collider has a `layer` (0..31, "what am I") and a `mask` (a 32-bit set
of layers it collides with, "what do I hit"). Two colliders interact only if
each one's mask includes the other's layer, so a bullet on the "player_bullet"
layer can be told to ignore the player entirely - and the physics world never
even runs the exact overlap test for those pairs.

    CollisionLayers.register("player", 1)
    CollisionLayers.register("enemy", 2)
    CollisionLayers.register("ground", 3)

    player.layer = "player"
    player_collider.mask = CollisionLayers.mask("ground", "enemy")

By default an object is on layer 0 ("default") and collides with everything.
"""


class CollisionLayers:
    MAX_LAYERS = 32
    ALL = 0xFFFFFFFF
    NONE = 0

    _names = {"default": 0}

    @classmethod
    def register(cls, name, index):
        """Give layer `index` (0..31) a name usable anywhere a layer is accepted."""
        if not isinstance(index, int) or not 0 <= index < cls.MAX_LAYERS:
            raise ValueError(f"Layer index must be an int in 0..{cls.MAX_LAYERS - 1}, got {index!r}")
        cls._names[str(name).lower()] = index
        return index

    @classmethod
    def index(cls, layer):
        """Resolve a layer name or index to a validated index."""
        if isinstance(layer, str):
            try:
                return cls._names[layer.lower()]
            except KeyError:
                raise ValueError(f"Unknown collision layer '{layer}'. Register it with "
                                 f"CollisionLayers.register(name, index).") from None
        if isinstance(layer, bool) or not isinstance(layer, int) or not 0 <= layer < cls.MAX_LAYERS:
            raise ValueError(f"Layer must be a name or an int in 0..{cls.MAX_LAYERS - 1}, got {layer!r}")
        return layer

    @classmethod
    def mask(cls, *layers):
        """A bitmask containing the given layers (names or indices)."""
        bits = 0
        for layer in layers:
            bits |= 1 << cls.index(layer)
        return bits

    @classmethod
    def name_of(cls, index):
        for name, i in cls._names.items():
            if i == index:
                return name
        return str(index)

    @classmethod
    def reset(cls):
        cls._names = {"default": 0}
