"""Factory functions for building simple shape-based GameObjects without
touching Pygame's drawing calls yourself.

Each function draws the shape onto a new Surface, builds a GameObject with
a SpriteRenderer for it, and (for the solid shapes) attaches a matching
collider by default - similar to how a primitive comes with a fitting
collider already attached in engines like Unity. All of it is optional
(`add_collider=False`/`add_rigidbody=True` etc.) and every function just
returns the GameObject - none of them add it to a scene for you, so you
still call `scene.add_game_object(...)` yourself, same as building one by
hand.

Note on `create_circle`: its default collider is a bounding-box
*approximation* (a square around the circle) for consistency with the
other primitives and because it's the cheaper broad-phase shape - pass
`precise_collider=True` to get an actual `CircleCollider2D` instead,
which tests true distance-to-center rather than the bounding square (see
`engine/components/circle_collider2d.py`). Note CircleCollider2D is
overlap/trigger-only - Rigidbody2D doesn't resolve solid collisions
against it - so for a circle that needs to physically rest/bounce off
surfaces, keep the default bounding-box BoxCollider2D.

There's no `create_cube()` - this is a 2D engine, so the 2D equivalent
(`create_rectangle`/`create_square`) is what's provided.
"""
import pygame

from engine.components.box_collider2d import BoxCollider2D
from engine.components.circle_collider2d import CircleCollider2D
from engine.components.rigidbody2d import Rigidbody2D
from engine.components.sprite_renderer import SpriteRenderer
from engine.core.game_object import GameObject


def create_rectangle(x=0, y=0, width=50, height=50, color=(200, 200, 200),
                      name="Rectangle", add_collider=True, add_rigidbody=False,
                      border_radius=0, is_static=False, layer=0):
    """A filled rectangle GameObject. `is_static=True` marks terrain/walls that
    never move (skips physics and per-frame sync); `layer` is a collision layer
    name or index (see engine/physics/layers.py)."""
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.rect(surface, color, surface.get_rect(), border_radius=border_radius)

    go = GameObject(x=x, y=y, name=name, layer=layer)
    go.add_component(SpriteRenderer(sprite=surface))
    if add_collider:
        go.add_component(BoxCollider2D(size=(width, height), anchor="topleft"))
    if add_rigidbody:
        go.add_component(Rigidbody2D())
    go.is_static = is_static
    return go


def create_square(x=0, y=0, size=50, color=(200, 200, 200), name="Square",
                   add_collider=True, add_rigidbody=False, is_static=False, layer=0):
    """A filled square - a thin convenience wrapper over create_rectangle
    for the common case of width == height."""
    return create_rectangle(x=x, y=y, width=size, height=size, color=color,
                             name=name, add_collider=add_collider,
                             add_rigidbody=add_rigidbody, is_static=is_static, layer=layer)


def create_circle(x=0, y=0, radius=25, color=(200, 200, 200), name="Circle",
                   add_collider=True, add_rigidbody=False, precise_collider=False,
                   is_static=False, layer=0):
    """A filled circle GameObject.

    `precise_collider=True` attaches a true `CircleCollider2D` (exact
    distance-to-center overlap testing) instead of the default bounding-box
    `BoxCollider2D` approximation - see the module docstring for the
    trade-off (precise circles are trigger/overlap-only; Rigidbody2D can't
    solidly resolve against one yet).
    """
    diameter = radius * 2
    surface = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    pygame.draw.circle(surface, color, (radius, radius), radius)

    go = GameObject(x=x, y=y, name=name, layer=layer)
    go.add_component(SpriteRenderer(sprite=surface))
    if add_collider:
        if precise_collider:
            go.add_component(CircleCollider2D(radius=radius, anchor="topleft"))
        else:
            go.add_component(BoxCollider2D(size=(diameter, diameter), anchor="topleft"))
    if add_rigidbody:
        go.add_component(Rigidbody2D())
    go.is_static = is_static
    return go


def create_triangle(x=0, y=0, size=50, color=(200, 200, 200), name="Triangle",
                     add_collider=True, add_rigidbody=False, is_static=False, layer=0):
    """An upward-pointing triangle, inscribed in a `size` x `size` box.
    Collider is the bounding box - this engine has no polygon collider."""
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    points = [(size / 2, 0), (size, size), (0, size)]
    pygame.draw.polygon(surface, color, points)

    go = GameObject(x=x, y=y, name=name, layer=layer)
    go.add_component(SpriteRenderer(sprite=surface))
    if add_collider:
        go.add_component(BoxCollider2D(size=(size, size), anchor="topleft"))
    if add_rigidbody:
        go.add_component(Rigidbody2D())
    go.is_static = is_static
    return go


def create_line(x=0, y=0, length=100, thickness=4, color=(200, 200, 200),
                 name="Line", vertical=False, is_static=False, layer=0):
    """A straight line segment, drawn as a thin filled rectangle. No
    collider by default - lines are usually visual (dividers, rails), not
    solid obstacles. Pass the result through your own collider setup if
    you need one to be solid."""
    width, height = (thickness, length) if vertical else (length, thickness)
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill(color)

    go = GameObject(x=x, y=y, name=name, layer=layer)
    go.add_component(SpriteRenderer(sprite=surface))
    go.is_static = is_static
    return go
