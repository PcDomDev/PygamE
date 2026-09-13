# PygamE

A small, component-based 2D engine built on Pygame, in the style of
Unity's GameObject/Component model. Every object in the world is a
`GameObject` with a `Transform`; behaviour (rendering, physics, input,
animation, UI, audio, camera-following, ...) comes from attaching
`Component`s to it.

This document is the complete, file-by-file reference: for every file in
the engine it explains what the file is responsible for, walks through
every function/class it defines, and shows a working example. It's long
by design - read top to bottom once, then use it as a lookup afterward.

*(Русская версия: [README.ru.md](README.ru.md))*

## Table of contents

1. [Quick start](#quick-start)
2. [The big picture](#the-big-picture)
3. [Project map](#project-map)
4. [Part 1 - Foundations: `engine/utils/`](#part-1---foundations-engineutils)
5. [Part 2 - Component system core](#part-2---component-system-core)
6. [Part 3 - Rendering](#part-3---rendering)
7. [Part 4 - Physics and collision](#part-4---physics-and-collision)
8. [Part 5 - Animation](#part-5---animation)
9. [Part 6 - Input system](#part-6---input-system)
10. [Part 7 - Player movement](#part-7---player-movement)
11. [Part 8 - Camera](#part-8---camera)
12. [Part 9 - UI system](#part-9---ui-system)
13. [Part 10 - Audio](#part-10---audio)
14. [Part 11 - Primitives](#part-11---primitives)
15. [Part 12 - Managing the world: Scene and SceneManager](#part-12---managing-the-world-scene-and-scenemanager)
16. [Part 13 - Diagnostics: DebugManager](#part-13---diagnostics-debugmanager)
17. [Part 14 - The engine shell: Engine](#part-14---the-engine-shell-engine)
18. [Part 15 - Example content](#part-15---example-content)
19. [Part 16 - The entry point: main.py](#part-16---the-entry-point-mainpy)
20. [Performance](#performance)
21. [Anchors, in depth](#anchors-in-depth)
22. [Quick index](#quick-index)
23. [Cookbook - "I want to..."](#cookbook---i-want-to)
24. [What changed in this update](#what-changed-in-this-update)

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

Demo controls: **A/D** or **←/→** to move, **Space** to jump (double-jump
- press it again in mid-air), **F1** debug overlay, **F2** collider
outlines, **F3** world-space coordinate grid.

## The big picture

A **`GameObject`** is a named box that holds a list of **`Component`**s
and nothing else. It doesn't know how to draw itself, fall under gravity,
or respond to key presses - those behaviours come entirely from whichever
components are attached to it. A **`Scene`** holds a list of GameObjects
and drives them: every frame it calls `update()` on each one, resolves
trigger overlaps, then renders the world (offset by the active camera)
and the UI (always in raw screen space, on top). An **`Engine`** owns the
actual window and the loop that drives `Scene.update()`/`render()` every
frame.

```
Engine.run()
  └─ every frame:
       ├─ pump events, Input.update()
       ├─ Scene.update(delta_time)
       │    ├─ every active GameObject.update(delta_time)
       │    │    └─ every enabled Component.update(delta_time), in update_order
       │    └─ resolve trigger overlaps (via the spatial hash)
       └─ Scene.render(screen)
            ├─ world: every SpriteRenderer, offset by the active Camera, viewport-culled
            └─ UI: every UIElement, in raw screen space, always on top
```

If you keep that diagram in your head, every file below is one more
detail of one box in this picture.

## Project map

```
engine/                        the engine itself - reusable, game-agnostic
    __init__.py
    primitives.py                  create_rectangle/square/circle/triangle/line
    core/
        app.py                        Engine: window, clock, main loop
        game_object.py                 GameObject: a named bag of components
        scene.py                        Scene: update / collide / render / UI pass
        scene_manager.py                 SceneManager: owns named scenes
        debug_manager.py                  DebugManager: logging + F1/F2/F3 overlays
        spatial_hash.py                    SpatialHash: broad-phase collision index
    components/
        component.py                    Component base class (update_order)
        transform.py                     position, rotation, scale
        sprite_renderer.py                draws a sprite (anchor/rotation/scale aware)
        rigidbody2d.py                     gravity, drag, collision response
        collider2d.py                       shared base for the two collider shapes
        box_collider2d.py                    rectangular hitbox; solid or trigger
        circle_collider2d.py                  circular hitbox; trigger/overlap only
        animator.py                            frame-based sprite animation
        player_controller.py                    movement + jumping (incl. multi-jump)
        camera.py                                follows a target, offsets rendering
        audio_source.py                           plays a sound effect or music track
    input/
        key.py                          Key.* names for pygame key codes
        input_manager.py                 Input: pressed / just-pressed / mouse
    ui/
        ui_style.py                     shared colours/fonts for UI
        ui_element.py                    UIElement base class
        ui_panel.py, ui_text.py, ui_button.py   the 3 core UI widgets
        ui_layout.py                      UILayoutGroup (stacking)
    utils/
        vector2.py                      minimal 2D vector
        warnings.py                      EngineWarning category
        anchors.py                        shared anchor math (sprites + colliders agree)
        spritesheet_loader.py              loads a spritesheet + JSON atlas into an Animator

examples/                       DEMO content - not part of the engine
    example_scene.py               builds the demo: a character, a platform, a HUD
    scripts/
        reset_on_click.py             a reusable "reset my position" behaviour
        jumps_hud.py                    keeps a UIText in sync with jumps_remaining

main.py                        engine setup + camera init only, no game logic
requirements.txt
.gitignore
```

`engine/` never imports from `examples/` - it has no idea what a specific
character, platform, or button in *your* game is. Delete the entire
`examples/` folder and `engine/` still works completely on its own;
`main.py` is the only file that connects the two.

---

## Part 1 - Foundations: `engine/utils/`

Everything here has **zero dependencies on the rest of the engine** -
these sit at the bottom of the dependency graph.

### `engine/utils/vector2.py`

- **Responsibility:** A minimal 2D vector, used anywhere the engine would
  otherwise pass around two loose `x`/`y` floats.
- **Used by:** `Transform` (position, scale), `Rigidbody2D` (velocity),
  `Camera` (position/offset math), `Scene` (render offset).

```python
class Vector2:
    def __init__(self, x=0.0, y=0.0): ...
```

| Member | What it does |
|---|---|
| `copy()` | New, independent `Vector2` with the same x/y. |
| `as_tuple()` / `as_int_tuple()` | Plain `(x, y)`, or rounded to ints. |
| `Vector2.zero()` / `Vector2.one()` | `(0,0)` / `(1,1)` shorthands. |
| `length()` | Magnitude via `math.hypot`. |
| `normalized()` | Same direction, length 1 (returns `(0,0)` for a zero vector, no divide-by-zero). |
| `lerp(other, t)` | Linear interpolation, `t` clamped to `[0, 1]`. |

Operators: `+`, `-`, unary `-`, `*`/`/` by a scalar, `+=`, `-=`, `==`.

```python
position = Vector2(100, 200)
velocity = Vector2(50, 0)
position += velocity * (1 / 60)   # move right at 50 px/s for one frame
```

### `engine/utils/warnings.py`

- **Responsibility:** One custom warning category, `EngineWarning`, for
  catching misconfiguration *at construction time* (a bad anchor string,
  an unknown `movement_type`) via Python's standard `warnings` module -
  which prints the exact file/line the mistake was made on, immediately.
- **Used by:** `BoxCollider2D`, `CircleCollider2D`, `SpriteRenderer`
  (bad anchor names), `PlayerController` (unknown `movement_type`),
  `UILayoutGroup` (unknown `direction`).

This is deliberately separate from `DebugManager` (Part 13): a warning is
for a *static* mistake in your code, caught once, before the game even
runs; `DebugManager` is for *runtime* events worth showing on an in-game
overlay while the game is playing.

```python
class EngineWarning(UserWarning):
    """Raised (via warnings.warn) for engine-level misconfiguration."""
```

### `engine/utils/anchors.py`

- **Responsibility:** The **one shared implementation** of anchor math -
  used by `SpriteRenderer`, `BoxCollider2D`, and `CircleCollider2D`, so
  all three agree on what `"center"` or `"bottomleft"` means. See
  ["Anchors, in depth"](#anchors-in-depth) for the full story of why this
  file exists and what it fixed.

```python
VALID_ANCHORS = {
    "topleft", "midtop", "topright",
    "midleft", "center", "midright",
    "bottomleft", "midbottom", "bottomright",
}

def anchor_to_topleft_offset(anchor, width, height): ...
```

`anchor_to_topleft_offset(anchor, width, height)` returns `(dx, dy)` such
that `top_left = anchor_point + (dx, dy)`, for a shape of the given size.
Computed via a throwaway `pygame.Rect` at the origin - exact for integer
sizes on all 4 corner and 4 edge-midpoint anchors, and correct to within
pygame's own rounding for `"center"` on an odd dimension.

```python
from engine.utils.anchors import anchor_to_topleft_offset
dx, dy = anchor_to_topleft_offset("center", 40, 60)  # (-20, -30)
```

### `engine/utils/spritesheet_loader.py`

- **Responsibility:** Loads a sprite-sheet image plus its JSON atlas
  (e.g. exported by TexturePacker) directly into the
  `{name: [surface, ...]}` shape `Animator` expects.
- **Depends on:** `pygame` (image/subsurface), `DebugManager` (error
  logging).

```python
def load_spritesheet_animations(json_path, image_path): ...
```

Supports both common atlas shapes - a `"frames"` object keyed by
filename (`{"walk_00.png": {"frame": {...}}}`), or a `"frames"` array of
`{"filename": ..., "frame": {...}}` objects. Frame names are split into
`(animation_name, frame_index)` by stripping the file extension and any
trailing run of digits - `"walk_01.png"` → `("walk", 1)` - and each
animation's frames are then **sorted by that index**, not by whatever
order the JSON happens to list them in (plain alphabetical order would
sort `"walk_10"` before `"walk_2"` and silently scramble the animation).

```python
from engine.utils.spritesheet_loader import load_spritesheet_animations
from engine.components.animator import Animator

animations = load_spritesheet_animations("assets/hero.json", "assets/hero.png")
hero.add_component(Animator(animations=animations, default_animation="idle"))
```

Paths are used exactly as given (relative to the current working
directory, or absolute) - the same convention `pygame.image.load` itself
uses. Errors (missing file, malformed JSON, an atlas shape the loader
doesn't recognize) are logged via `DebugManager` with which path/step
failed, then re-raised - a missing asset is worth seeing immediately, not
silently continuing past with half a spritesheet loaded.

---

## Part 2 - Component system core

### `engine/components/component.py`

- **Responsibility:** The base class every behaviour inherits from -
  defines the `start()`/`update()` lifecycle and `update_order`.
- **Used by:** everything.

```python
class Component:
    update_order = 0
    def __init__(self): ...
    def start(self): ...
    def update(self, delta_time): ...
```

| Member | What it does |
|---|---|
| `update_order` (class attr, default `0`) | Before running `update()` each frame, `GameObject` sorts its components by this (ascending). See the table below for what the built-ins use. |
| `game_object` | Back-reference, set by `GameObject.add_component()`. |
| `enabled` | `True` by default; `GameObject.update()` skips `update()` entirely when `False`. |
| `start()` | Runs once, the moment this component's GameObject enters a running scene. Safe to call more than once (a private flag makes every call after the first a no-op). Override this (not `__init__`) to look up sibling components. |
| `update(delta_time)` | Runs every frame while enabled/active. `delta_time` is seconds since the last frame. |

**`update_order` reference table** (why the camera always sees the
frame's *final* positions, why physics runs before anything reacts to
it):

| Component | update_order |
|---|:---:|
| `Rigidbody2D` | -100 |
| `BoxCollider2D` / `CircleCollider2D` | -90 |
| *(gameplay code, UI, Animator, PlayerController)* | 0 |
| `Camera` | 100 |

```python
class SpinForever(Component):
    def __init__(self, degrees_per_second=90):
        super().__init__()
        self.degrees_per_second = degrees_per_second

    def update(self, delta_time):
        self.game_object.transform.rotation += self.degrees_per_second * delta_time
```

### `engine/components/transform.py`

- **Responsibility:** Position, rotation, scale - created automatically
  for every `GameObject`.

```python
class Transform(Component):
    def __init__(self, x=0.0, y=0.0, rotation=0.0, scale_x=1.0, scale_y=1.0): ...
```

| Member | Type | What it does |
|---|---|---|
| `position` | `Vector2` | World-space pixels. |
| `rotation` | `float` | Degrees, clockwise-positive. Rendered by `SpriteRenderer` (Part 3). |
| `scale` | `Vector2` | `(1,1)` = original size. Rendered by `SpriteRenderer`; does **not** affect collider size (call `set_size`/`set_radius` explicitly if you need that to match). |
| `translate(dx, dy)` | | Shorthand for `position.x += dx; position.y += dy`. |

`GameObject.x`/`.y` remain as aliases for `transform.position.x`/`.y`.

### `engine/core/game_object.py`

- **Responsibility:** A named container of components, plus the glue
  that runs `start()`/`update()` in a well-defined order.

```python
class GameObject:
    def __init__(self, x=0.0, y=0.0, name="GameObject"): ...
```

| Member | What it does |
|---|---|
| `transform` | Created automatically - always valid. |
| `active` (property) | `False` skips this object entirely: `update()`, and every `Scene.get_components()` query (so also rendering and collision). **Toggling it notifies the owning Scene** (`Scene._on_active_changed`), which keeps the component cache and spatial hash correct immediately - see [Performance](#performance). |
| `scene` | Set by `Scene.add_game_object()`. |
| `add_component(c)` / `get_component(cls)` / `get_components(cls)` / `remove_component(c)` | Standard component management; `add_component`/`remove_component` notify the scene to invalidate its component cache. |
| `start()` / `update(delta_time)` | Runs every component's `start()`/`update()`, sorted by `update_order` (cached, only re-sorted when the component list actually changes). |
| `x`, `y` | Aliases for `transform.position.x`/`.y`. |

```python
enemy = GameObject(x=300, y=100, name="Slime")
rb = enemy.add_component(Rigidbody2D(gravity=900, use_gravity=True))
enemy.add_component(SpriteRenderer(sprite=slime_image))
enemy.active = False   # instantly removed from update/render/collision, without deleting it
```

---

## Part 3 - Rendering

### `engine/components/sprite_renderer.py`

- **Responsibility:** Holds the image to draw, and (as of this update)
  where on that image the transform position points to.
- **Depends on:** `Component`, `engine.utils.anchors` (shared anchor math).
- **Used by:** `Scene._render_world()`.

```python
class SpriteRenderer(Component):
    def __init__(self, sprite=None, z_index=0, offset_y=0, anchor="topleft"): ...
```

| Member | What it does |
|---|---|
| `sprite` | A `pygame.Surface`, or `None` to render nothing. Always the *original*, unrotated/unscaled image - `get_transformed_sprite()` below returns the derived one. |
| `anchor` | Which point of the sprite sits at the transform position - the **same 9 named anchors and the same shared math** `BoxCollider2D`/`CircleCollider2D` use. Set it to the same value as your collider's `anchor` to keep the two visually aligned - see [Anchors, in depth](#anchors-in-depth). Invalid values warn and fall back to `"topleft"`. |
| `z_index` | Layer order, lower draws first. |
| `offset_y` | Only affects the render *sort key* (`position.y + offset_y`, for cheap depth faking), not the draw position. |
| `set_sprite(sprite)` | Replaces the sprite and invalidates the rotation/scale cache. |
| `get_anchor_offset()` | `(dx, dy)` from the transform position to the sprite's original top-left corner, per `anchor`. `(0,0)` if there's no sprite yet. |
| `get_transformed_sprite(rotation, scale_x, scale_y)` | The sprite rotated/scaled to match, **cached** by `(sprite id, rotation, scale)` so a static object isn't re-rotated/re-scaled every frame. Rotation is clockwise-positive (pygame's own `rotate()` is counter-clockwise-positive, hence the sign flip inside). |

`Scene._render_world()` (Part 12) uses `get_anchor_offset()` to find the
sprite's original center (the fixed point rotation/scaling pivots
around), then `get_transformed_sprite()` for the actual surface to blit -
you don't normally call either yourself unless you're writing custom
rendering.

```python
renderer = enemy.add_component(SpriteRenderer(sprite=slime_image, anchor="center"))
enemy.add_component(BoxCollider2D(size=slime_image.get_size(), anchor="center"))
# now both agree that (enemy.x, enemy.y) is the CENTER of the slime

enemy.transform.rotation = 45     # rendered, rotated around the sprite's center
enemy.transform.scale.x = 1.5     # rendered, 1.5x wide
```

---

## Part 4 - Physics and collision

Four files work together here. Read them in this order:
`collider2d.py` (the shared shape-agnostic base) → `box_collider2d.py` /
`circle_collider2d.py` (the two concrete shapes) → `rigidbody2d.py` (the
thing that actually moves and resolves collisions) →
`../core/spatial_hash.py` (what makes checking many objects fast).

### `engine/components/collider2d.py`

- **Responsibility:** Everything shared between `BoxCollider2D` and
  `CircleCollider2D` that doesn't depend on the actual shape - trigger
  state, the `on_trigger_enter/stay/exit` callback lists, overlap
  tracking, and safe dispatch.
- **Used by:** `BoxCollider2D`, `CircleCollider2D` (both inherit from
  it), `Scene` (queries `get_components(Collider2D)` to process triggers
  and to feed `DebugManager`'s outline drawing - one query catches both
  shapes).

```python
class Collider2D(Component):
    shape = None  # "box" or "circle" - set by subclasses
    def __init__(self, is_trigger=False): ...
```

| Member | What it does |
|---|---|
| `is_trigger` | `False` = solid (only `BoxCollider2D` is resolved as solid by `Rigidbody2D` - see below). `True` = overlap-only. |
| `on_trigger_enter` / `_stay` / `_exit` | Lists of `callback(trigger, other)`. Append to subscribe. |
| `overlapping_colliders` (property) | Read-only snapshot of what this trigger currently overlaps. |
| `overlaps(other)` | Abstract - each subclass implements its own precise shape-vs-shape test, dispatching on `other.shape` (a string) rather than `isinstance` checks, specifically so `box_collider2d.py` and `circle_collider2d.py` never need to import each other. |
| `check_trigger_events(other)` | Compares this frame's `overlaps()` result against last frame's state and fires the right callback list. Called by `Scene`, not normally by you. |
| `_sync_spatial_hash()` | Called by each subclass at the end of its own shape update - see [Performance](#performance). |

Two free functions live here too, shared by both shapes'
`overlaps()` implementations: `_circle_circle_overlap(...)` (distance
between centers vs. sum of radii) and `_circle_rect_overlap(...)`
(closest-point-on-rect-to-circle-center, standard circle-vs-AABB test).

### `engine/components/box_collider2d.py`

- **Responsibility:** A rectangular hitbox.
- **Depends on:** `Collider2D`, `SpriteRenderer` (auto-sizing),
  `engine.utils.anchors`.
- **Used by:** `Rigidbody2D` (the only shape it resolves solid collisions
  against), example content, gameplay scripts.

```python
class BoxCollider2D(Collider2D):
    def __init__(self, size=None, offset_x=0, offset_y=0, anchor="topleft", is_trigger=False): ...
```

**Sizing:** pass `size=(w, h)` explicitly when you can. If omitted, it's
measured *once* from the sprite at `start()` and then **locked** - it
never changes again automatically, even if the sprite later changes size
(an `Animator` swapping frames). This is deliberate: a collider that kept
re-measuring the live sprite every frame is exactly what caused a
reported landing-jitter bug in an earlier version (see
["What changed"](#what-changed-in-this-update)) - two animation frames
just one pixel apart in height would make the hitbox visibly pop between
sizes at every animation transition. Call `set_size(w, h)` for a
deliberate resize (e.g. a crouch).

| Member | What it does |
|---|---|
| `rect` | Current `pygame.Rect`, pixel-quantized (pygame rounds every coordinate). |
| `anchor` | Same 9 names as `SpriteRenderer` - see [Anchors, in depth](#anchors-in-depth). Invalid values warn and fall back to `"topleft"`. |
| `set_size(w, h)` | Explicitly (re)lock the size. |
| `snap_left_to` / `snap_right_to` / `snap_top_to` / `snap_bottom_to(coord)` | Move the owning Transform so this edge sits exactly at `coord`, using the *exact float* transform position rather than the already-rounded `.rect`. This is what `Rigidbody2D` calls to resolve a collision - see why exactness here matters in Part 4's Rigidbody2D section below. |
| `overlaps(other)` | `rect.colliderect(other.rect)` for another box; the shared circle-rect test for a circle. |

```python
player.add_component(BoxCollider2D(size=(32, 48), anchor="topleft"))
coin_collider = coin.add_component(BoxCollider2D(is_trigger=True))
coin_collider.on_trigger_enter.append(lambda trigger, other: print("touched!"))
```

### `engine/components/circle_collider2d.py`

- **Responsibility:** A circular hitbox with *precise* circle-vs-circle
  and circle-vs-box overlap testing - unlike `create_circle()`'s default
  bounding-box approximation (Part 11), this tests true distance-to-center.
- **Scope - read this before using one:** **overlap/trigger detection
  only.** `Rigidbody2D` only looks for a `BoxCollider2D` to resolve solid
  collisions against; a `CircleCollider2D` can still move (gravity/velocity
  apply to its Transform normally) but won't physically push or be pushed
  by anything. For a coin, sensor, or detection radius (almost always
  circular, almost always a trigger) that's exactly what you want. For a
  solid rolling ball that needs to physically bounce/rest, this engine
  doesn't implement that yet - it's a natural, documented extension point
  (see the end of this section).

```python
class CircleCollider2D(Collider2D):
    def __init__(self, radius=None, offset_x=0, offset_y=0, anchor="topleft", is_trigger=False): ...
```

| Member | What it does |
|---|---|
| `radius` (property) | Read-only; set via constructor or `set_radius()`. |
| `center_x`, `center_y` | The circle's actual center in world space (computed from the transform position + anchor + offset - see below). |
| `rect` | A bounding-box `pygame.Rect` around the circle - used for broad-phase spatial queries and `DebugManager`'s outline; **not** what `overlaps()` tests against. |
| `anchor` | Same 9 names, applied to the circle's `(diameter, diameter)` bounding square. Default `"topleft"` matches `BoxCollider2D`/`SpriteRenderer`'s default, so a default circle collider centers correctly under a default (also `"topleft"`) `SpriteRenderer` showing a circle drawn centered in its own surface - see [Anchors, in depth](#anchors-in-depth) for exactly why this matters and what it fixes. |
| `set_radius(r)` | Explicitly (re)lock the radius, same idea as `BoxCollider2D.set_size()`. |
| `overlaps(other)` | Precise circle-circle or circle-rect test, dispatching on `other.shape`. |

```python
sensor_go = GameObject(x=200, y=200, name="PickupRadius")
sensor = sensor_go.add_component(CircleCollider2D(radius=80, is_trigger=True))
sensor.on_trigger_enter.append(lambda t, o: print("something wandered into range"))
```

*Extending solid circle physics:* `Rigidbody2D._solid_colliders_near()`
(next section) filters to `isinstance(c, BoxCollider2D)` - teaching it to
also resolve against a `CircleCollider2D` (closest-point circle-vs-box
resolution, or true circle-vs-circle for two round bodies) is the natural
next step for a game that needs physically-rolling balls; it's kept out
of this pass specifically to avoid rushing new collision-resolution math
into the exact area that was hardest to get right the first time (see
["What changed"](#what-changed-in-this-update)).

### `engine/components/rigidbody2d.py`

- **Responsibility:** Gravity + drag + AABB collision response.
- **Depends on:** `Collider2D`/`BoxCollider2D`, `DebugManager`
  (a one-time warning if there's no collider), `Vector2`.
- **Used by:** anything that needs to fall, move under velocity, or
  physically collide.

```python
class Rigidbody2D(Component):
    GROUND_PROBE_DISTANCE = 4
    def __init__(self, gravity=500, gravity_scale=1.0, drag=0.0, mass=1.0,
                 use_gravity=True, is_kinematic=False, terminal_velocity=1000): ...
```

**The physics step, every frame:** apply gravity to vertical velocity →
clamp to `terminal_velocity` → apply `drag` to horizontal velocity → move
X, resolve X collisions → move Y, resolve Y collisions. Resolving one
axis fully before the other is a standard AABB simplification that avoids
ambiguous diagonal-corner cases.

| Member | What it does |
|---|---|
| `velocity` | `Vector2`, px/s. |
| `velocity_x`, `velocity_y` | Back-compat float aliases. |
| `is_grounded` | `True` while resting on something solid. Stable (doesn't flicker frame to frame) - see `GROUND_PROBE_DISTANCE` below. |
| `is_kinematic` | Moves under its own velocity, ignores gravity/forces, never gets pushed by others - for moving platforms. |
| `add_impulse(ix, iy)` | Instant: `Δv = impulse / mass`. |
| `add_force(fx, fy, delta_time)` | Continuous: `Δv = (force/mass) * delta_time` - call every frame. |
| `stop()` | Zeroes velocity. |

**Why collision correction is *exact* (not approximate):** `.rect` is a
`pygame.Rect`, which rounds every coordinate to the nearest int. The
naive approach - compute `overlap = collider.rect.bottom - other.rect.top`
(an int), then subtract it from the object's *float* position - looks
exact but isn't: the rounding done when building `.rect` throws away a
fraction of a pixel that doesn't cancel back out, and across many frames
this becomes visible jitter. `_resolve_collisions_x/y` instead call
`collider.snap_bottom_to`/`snap_top_to`/`snap_left_to`/`snap_right_to`,
which recompute the corrected position directly from the exact float
transform position and the *other* collider's exact edge - bypassing that
rounding loss entirely. `.rect` is still used for the initial "is there
an overlap at all" test (a yes/no question where quantization doesn't
matter), never for the correction math.

**Why `is_grounded` doesn't flicker:** gravity nudges a resting body down
a fraction of a pixel every single frame (that's what re-triggers the
"still touching" check), and whether that fraction rounds `.rect` back to
"still touching" or "juuust clear" flips essentially every other frame -
without help, this used to make `is_grounded` (and anything that reads
it, like which animation to play) flicker every frame at rest.
`_probe_for_ground()` checks a few pixels below the collider
(`GROUND_PROBE_DISTANCE`, default 4px) whenever there's no *direct*
overlap this frame, so a resting body reads as grounded continuously.

**`_solid_colliders_near(rect)`** is the method that changed most for
performance in this update - see [Performance](#performance) for why it
now queries the scene's `SpatialHash` instead of scanning every collider
in the scene, and why that's safe (never stale within a frame, never
misses a genuine overlap).

```python
rb = player.add_component(Rigidbody2D(gravity=900, use_gravity=True, drag=3.0))
if rb.is_grounded:
    rb.add_impulse(0, -500)                    # a jump
def apply_wind(delta_time):
    rb.add_force(200, 0, delta_time)           # call every frame for a sustained push
```

### `engine/core/spatial_hash.py`

- **Responsibility:** A uniform grid for fast "what's near this rect"
  broad-phase queries - see [Performance](#performance) for the full
  story of why this exists and the benchmark numbers.
- **Used by:** `Scene` (owns one per scene), `Collider2D` (registers
  itself as its shape updates), `Rigidbody2D` (queries it instead of
  scanning every collider).

```python
class SpatialHash:
    def __init__(self, cell_size=128): ...
    def update(self, collider): ...   # (re)insert to match its current .rect
    def remove(self, collider): ...
    def query(self, rect): ...        # broad-phase candidate set near rect
    def clear(self): ...
```

`query(rect)` returns colliders sharing a grid cell with `rect` - a
*candidate* set that may include a few false positives (never a false
negative), which callers always confirm with an exact `overlaps()` or
`.rect.colliderect()` check afterward. You won't normally call this
directly - `Rigidbody2D` and `Scene._process_triggers()` do it for you.

---

## Part 5 - Animation

### `engine/components/animator.py`

- **Responsibility:** Cycles a `SpriteRenderer`'s sprite through a list
  of frames over time.
- **Used by:** `PlayerController` (calls `play()` every frame with
  whichever animation matches the current state).

```python
class Animator(Component):
    def __init__(self, animations=None, default_animation=None, frame_duration=0.1): ...
```

`animations` is `{"idle": [surf, ...], "jump": [surf, ...]}` - exactly
what `load_spritesheet_animations()` (Part 1) returns.

| Member | What it does |
|---|---|
| `play(name, loop=True, reverse=False)` | **Safe to call every single frame** with the intended animation - repeated calls with the same, still-playing name are a no-op past updating `loop`/`reverse`. Only resets to frame 0 when the name actually changes, or the previous playback had finished. (An earlier version reset on *every* call regardless, which meant an animation driven this way - the only way `PlayerController` ever drives one - could never advance past frame 0.) |
| `pause()` | Stops advancing, keeps `frame_index` where it is. |
| `stop()` | Stops and resets to frame 0. |
| `is_playing`, `frame_index`, `current_animation` | Read-only-in-practice state. |

```python
anim = player.add_component(Animator(
    animations={"idle": [idle_frame], "walk_right": [w1, w2, w3, w4]},
    default_animation="idle", frame_duration=0.12,
))
anim.play("walk_right")   # call every frame while walking - keeps advancing normally
```

---

## Part 6 - Input system

### `engine/input/key.py`

- **Responsibility:** Friendly names for pygame key codes, and
  `normalize_key()`, which turns any of them into the underlying int.

```python
Key.W          # attribute access
"w"            # case-insensitive string
pygame.K_w     # raw pygame constant - Key.W literally *is* this same int
```

`Key` covers letters, digits (as `NUM_0`..`NUM_9` - `Key.0` isn't legal
Python syntax, but the string form `"0"` works directly), arrows, common
editing/whitespace keys, modifiers, and F1-F12. `normalize_key(key)`
accepts any of the three forms above; for a string it checks a small
alias table (`"space"`, `"left"`, `"shift"`, ...) first, then falls back
to `pygame.key.key_code(name)` - so any key name pygame itself
recognizes works even if it's not in the alias table. Raises `ValueError`
for anything unrecognized, so a typo'd key name fails immediately rather
than a keybind silently never firing.

### `engine/input/input_manager.py`

- **Responsibility:** Keyboard and mouse state, with "just pressed this
  frame" edge detection on top of pygame's raw "currently held" state.
- **Used by:** `PlayerController`, `UIButton`, anything that needs input.

```python
class Input:
    def update(self): ...   # called once per frame by Engine, before Scene.update()
```

Same dual-access pattern as `DebugManager` - works from anywhere:

```python
from engine.input.input_manager import Input
from engine.input.key import Key

Input.is_pressed(Key.W)             # held down right now
Input.is_just_pressed(Key.SPACE)    # true only on the exact press frame
Input.is_just_released(Key.SPACE)

Input.mouse_position()              # (x, y) in screen pixels
Input.is_mouse_pressed(0)           # 0=left, 1=middle, 2=right
Input.is_mouse_just_pressed(0)
Input.is_mouse_just_released(0)
```

`Engine.run()` calls `self.input.update()` every frame, right after
pumping pygame's event queue and before `Scene.update()` - so whatever a
component reads during its own `update()` reflects that frame's state.
If you drive `Scene.update()` yourself outside of `Engine.run()` (e.g. in
a test), you need to call `Input.instance().update()` yourself too, for
the same reason.

---

## Part 7 - Player movement

### `engine/components/player_controller.py`

- **Responsibility:** Turns input into movement - top-down or platformer
  - and (if an `Animator` is present) picks which animation should play.
- **Depends on:** `Input`/`Key` (Part 6), `Animator`, `Rigidbody2D` (both
  optional - see below).

```python
class PlayerController(Component):
    def __init__(self, speed=200, jump_force=350, movement_type="top_down",
                 keybinds=None, anim_map=None,
                 coyote_time=0.1, jump_buffer_time=0.1, max_jumps=1): ...
```

**Modes:** `"top_down"` (4/8-directional, no gravity - normalizes
diagonal speed to match axis speed) or `"platformer"` (horizontal run +
gravity-driven jump via `Rigidbody2D`).

**Multi-jump / double jump:** `max_jumps` is how many times the character
can jump before touching ground again - `1` (default) is a normal single
jump, `2` a double jump, and so on. The *first* jump in a chain still
respects `coyote_time` (a grace window after leaving a platform); every
jump after the first is available immediately while airborne, since at
that point the player is deliberately using an extra jump, not
accidentally walking off a ledge. The count refills the instant
`is_grounded` becomes true. Read `controller.jumps_remaining` for a UI
readout (see `examples/scripts/jumps_hud.py`, Part 15).

**Jump buffering:** `jump_buffer_time` - a jump pressed slightly *before*
landing still fires the instant the character touches down.

**`keybinds`** accepts `Key.*`/raw `pygame.K_*`/strings interchangeably
(defaults to WASD + arrows + Space):

```python
character.add_component(PlayerController(
    speed=200, jump_force=500, movement_type="platformer", max_jumps=2,
    keybinds={"left": ["a", Key.LEFT], "right": ["d", Key.RIGHT], "jump": [Key.SPACE]},
))
```

**Works without a Rigidbody2D or Animator** - both are optional; without
a rigidbody, movement falls back to moving the transform directly (and
jumping does nothing, with a one-time warning logged if you're in
`"platformer"` mode); without an animator, the animation-selection calls
are simply skipped.

**Extending it** - subclass and override a hook rather than the whole
class:

| Hook | Called |
|---|---|
| `_on_jump()` | The instant any jump fires. |
| `_can_jump()` / `_wants_to_jump()` | To change what counts as "allowed to jump" - e.g. a wall-jump ability. |
| `_play_platformer_animation()` / `_play_top_down_animation()` | To add animation states. |
| `_read_move_axis()` | To change how input maps to a direction (a gamepad, etc). |

```python
class DoubleJumpWithDash(PlayerController):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.can_dash = True

    def _on_jump(self):
        self.can_dash = True   # refill a dash every time you jump, say
```

---

## Part 8 - Camera

### `engine/components/camera.py`

- **Responsibility:** Tracks a virtual viewpoint and produces the offset
  `Scene.render()` subtracts from every sprite's world position, so the
  world scrolls around whatever it's following.

```python
class Camera(Component):
    def __init__(self, target=None, follow_speed=5.0, smooth_follow=True, position=None): ...
```

| Member | What it does |
|---|---|
| `target` | `GameObject` to follow, or `None` (static world - see below). |
| `follow_speed` | Higher = snappier, when `smooth_follow=True`. |
| `smooth_follow` | `True`: eases towards the target every frame (see the math below). `False`: snaps exactly onto it every frame. |
| `set_target(target, snap=True)` | Switch targets; `snap=True` re-centers instantly. |
| `snap_to_target()` | Instant re-center on the current target (e.g. after a teleport). |
| `get_offset(screen_w, screen_h)` | The world point that lands at the screen's top-left. **Always exactly `(0, 0)` when `target is None`** - not "whatever position defaults to," an explicit, unconditional zero. |

**The camera never moves its target** - it tracks its own `position`, and
rendering subtracts the resulting offset from *every* sprite's world
position (the target included). This is what makes jumping look natural:
the player's physics are completely undisturbed by the camera.

**Smooth-follow math** uses exponential ("smooth damp") interpolation:

```python
t = 1.0 - math.exp(-follow_speed * delta_time)
position = position.lerp(target_position, t)
```

instead of the more obvious `lerp(position, target, follow_speed * dt)`.
The naive version's effective smoothing strength depends on frame rate -
at a low enough frame rate, `follow_speed * dt` can exceed `1.0` and the
camera overshoots, then corrects the other way: visible shake, entirely
from the camera math. The exponential form converges at the same *rate*
regardless of frame rate and can't overshoot, at any frame rate.

```python
camera_go = GameObject(name="Main Camera")
camera = camera_go.add_component(Camera(target=character, follow_speed=6.0))
scene.add_game_object(camera_go)
scene.set_active_camera(camera)
```

---

## Part 9 - UI system

Six small files. A UI element's position comes from its `GameObject`'s
`Transform`, same as everything else - it's just interpreted as **screen
pixels**, not world coordinates, and drawn in its own pass after the
world, unaffected by the camera.

### `engine/ui/ui_style.py`

- **Responsibility:** A shared bundle of colours/font so you don't repeat
  five arguments on every panel/text/button.

```python
class UIStyle:
    def __init__(self, background_color=(60,60,70), border_color=(120,120,130),
                 border_width=2, text_color=(240,240,240), font_name=None,
                 font_size=20, hover_color=(80,80,95), pressed_color=(40,40,50)): ...
```

Not a full theming engine - just enough to have one obvious place to
change if every button in your game should look different.

### `engine/ui/ui_element.py`

- **Responsibility:** Base class for every UI widget.

```python
class UIElement(Component):
    def __init__(self, width=100, height=30, visible=True, draw_order=0): ...
```

| Member | What it does |
|---|---|
| `rect` (property) | Current screen-space `pygame.Rect`, from the transform position (top-left) and `width`/`height`. |
| `contains_point(x, y)` | Hit-test, used for hover/click. |
| `draw_order` | Order **among UI elements specifically** (not `update_order` - drawing is a separate pass). Lower draws first/behind. |
| `draw(screen)` | Override in a subclass - called by `Scene._render_ui()` for every visible element. |

### `engine/ui/ui_panel.py`

```python
class UIPanel(UIElement):
    def __init__(self, width=200, height=100, style=None, **kwargs): ...
```

A plain rectangular background, optionally bordered.

### `engine/ui/ui_text.py`

```python
class UIText(UIElement):
    def __init__(self, text="", style=None, align="left", width=None, height=None, **kwargs): ...
```

Renders a string; `set_text(text)` to update it. `align`:
`"left"`/`"center"`/`"right"` (horizontal only - vertical is always
centered in `height`). Width/height default to the rendered text's
measured size if not given.

### `engine/ui/ui_button.py`

```python
class UIButton(UIElement):
    def __init__(self, text="Button", width=140, height=40, style=None, **kwargs): ...
```

| Member | What it does |
|---|---|
| `is_hovered`, `is_pressed` | Live state, updated from `Input` every frame. |
| `on_click` | List of `callback(button)` - append to subscribe, same pattern as `Collider2D.on_trigger_enter`. Fires on **press-then-release while still hovering** - the standard button gesture; dragging off before releasing cancels it. |

```python
button = button_go.add_component(UIButton(text="Start", width=150, height=36))
button.on_click.append(lambda b: print("clicked!"))
```

### `engine/ui/ui_layout.py`

```python
class UILayoutGroup(Component):
    def __init__(self, direction="vertical", spacing=8): ...
```

`add_item(game_object)` / `remove_item(game_object)` manage a list of UI
GameObjects; every frame, `update()` repositions each one's
`transform.position` in a stack relative to the layout's own position.
This engine has no parent-child transform hierarchy, so this is a
positioning *helper*, not true nesting - but it's enough for a simple
menu or HUD list.

```python
layout = layout_go.add_component(UILayoutGroup(direction="vertical", spacing=10))
layout.add_item(button_a_go)
layout.add_item(button_b_go)   # positioned below button_a automatically, every frame
```

---

## Part 10 - Audio

### `engine/components/audio_source.py`

- **Responsibility:** Plays a sound effect or a looping track - one
  component type for both, the way Unity's `AudioSource` covers both
  cases.
- **Depends on:** `pygame.mixer` (already initialized by `pygame.init()`,
  which `Engine.__init__` calls - no extra setup needed).

**Why pygame.mixer and not a separate audio library:** it already covers
what a typical 2D game needs - sound effects, looping music, per-source
volume, play/pause/stop - so adding another dependency would be extra
complexity for no real new capability. If your game needs something
`pygame.mixer` genuinely can't do, this is the one file in the engine
that touches audio at all, making it the natural place to swap in
something else (see `requirements.txt`, which documents this choice).

```python
class AudioSource(Component):
    def __init__(self, path=None, volume=1.0, loop=False, play_on_start=False): ...
```

| Member | What it does |
|---|---|
| `load(path)` | Loads (or replaces) the sound. Failures (missing file, bad format, no audio device) are logged via `DebugManager`, not raised - a missing sound shouldn't crash the game. |
| `play()` | Starts from the beginning; safe with nothing loaded (warns) or already playing (restarts). |
| `stop()` / `pause()` / `resume()` | As named. |
| `set_volume(v)` | 0.0-1.0. |
| `is_playing` (property) | Whether the underlying channel is still busy. |

```python
coin_sound = coin.add_component(AudioSource(path="assets/sfx/coin.wav", volume=0.6))
coin_sound.play()

music = GameObject(name="Music").add_component(
    AudioSource(path="assets/music/theme.ogg", loop=True, play_on_start=True)
)
```

---

## Part 11 - Primitives

### `engine/primitives.py`

- **Responsibility:** Factory functions that build a ready-to-use
  `GameObject` for a simple shape, without touching Pygame's drawing
  calls yourself.

```python
create_rectangle(x=0, y=0, width=50, height=50, color=(200,200,200),
                  name="Rectangle", add_collider=True, add_rigidbody=False, border_radius=0)
create_square(x=0, y=0, size=50, color=(200,200,200), name="Square", ...)
create_circle(x=0, y=0, radius=25, color=(200,200,200), name="Circle",
              add_collider=True, add_rigidbody=False, precise_collider=False)
create_triangle(x=0, y=0, size=50, color=(200,200,200), name="Triangle", ...)
create_line(x=0, y=0, length=100, thickness=4, color=(200,200,200), vertical=False)
```

Each returns a `GameObject` with a `SpriteRenderer`, and (for the solid
shapes, unless `add_collider=False`) a matching collider - by default a
`BoxCollider2D` bounding box, even for `create_circle`/`create_triangle`
(this engine has no polygon collider, and a box is the cheaper default
for broad-phase). Pass `precise_collider=True` to `create_circle` for a
true `CircleCollider2D` instead (Part 4) - trigger/overlap-only, see that
section's scope note. `create_line` has no collider by default (lines are
usually visual dividers/rails, not obstacles). None of these add the
result to a scene for you.

There's no `create_cube()` - this is a 2D engine, so the 2D equivalent
(`create_rectangle`/`create_square`) is what's provided.

```python
platform = create_rectangle(x=50, y=450, width=400, height=40, color=(90,90,100))
scene.add_game_object(platform)

coin = create_circle(x=200, y=300, radius=12, color=(230,190,90),
                      precise_collider=True, add_collider=True)
coin.get_component(CircleCollider2D).is_trigger = True
scene.add_game_object(coin)
```

---

## Part 12 - Managing the world: Scene and SceneManager

### `engine/core/scene.py`

- **Responsibility:** Owns a list of GameObjects; updates, collides, and
  renders them. Also owns the performance-critical indexes: the
  component-type cache and the `SpatialHash` - see
  [Performance](#performance) for the full story.

```python
class Scene:
    def __init__(self, name="Scene"): ...
```

| Member | What it does |
|---|---|
| `game_objects` | Every object in this scene, in insertion order. |
| `active_camera` | Whichever `Camera`'s offset applies during rendering; `None` = raw world coordinates. |
| `spatial_hash` | A `SpatialHash`, one per scene. |
| `add_game_object(go)` | Sets `go.scene`, appends, calls `go.start()`, invalidates the component cache. |
| `remove_game_object(go)` | Removes it, and cleans up its colliders' spatial-hash entries. |
| `find_game_object(name)` | First object with a matching `.name`, or `None`. |
| `set_active_camera(camera)` | |
| `get_components(cls)` | Every component of `cls` (or a subclass) across every *active* object - see [Performance](#performance) for why this is now indexed rather than a linear scan. |
| `update(delta_time)` | Updates every active object, then `_process_triggers()`. |
| `render(screen)` | `_render_world()` then `_render_ui()`. |

`_process_triggers()` queries `spatial_hash` for broad-phase candidates
near each trigger, **unioned with whatever that trigger was already
overlapping last frame** - the union specifically guarantees
`on_trigger_exit` still fires even if something moved far enough in one
frame (a teleport) to leave the trigger's spatial neighborhood entirely,
which a broad-phase-only query could otherwise miss forever (see the test
for this exact scenario in the test suite this update was validated
against).

`_render_world()` computes the camera offset, then for each
`SpriteRenderer`: finds its anchor-adjusted original center, **culls it
if that center (plus half its original size) doesn't reach the screen at
all**, and otherwise fetches the transformed (rotated/scaled) sprite and
blits it. `_render_ui()` draws every visible `UIElement`, sorted by
`draw_order`, in raw screen space.

### `engine/core/scene_manager.py`

- **Responsibility:** Owns every registered `Scene` by name, tracks which
  is active.

```python
class SceneManager:
    def add_scene(self, name, scene): ...
    def set_active(self, name): ...   # logs an error (not a crash) for an unknown name
    def get_scene(self, name): ...
    def update(self, delta_time): ...
    def render(self, screen): ...
```

`Engine` owns one; `Engine.load_scene(name, scene)` is a convenience for
the common "register and immediately activate" case.

---

## Part 13 - Diagnostics: DebugManager

### `engine/core/debug_manager.py`

- **Responsibility:** Logging (`log_info`/`log_warning`/`log_error`), plus
  three independent on-screen overlays: the FPS/log panel (**F1**),
  collider outlines (**F2**), and a world-space coordinate grid (**F3**).

Two equivalent access patterns, same as everywhere else in the engine
that needs to be reachable without threading a reference through every
component:

```python
DebugManager.log_warning("...")     # from anywhere
engine.debug.log_warning("...")     # via the instance Engine created
```

```python
class DebugManager:
    def __init__(self, history_size=200, overlay_lines=8, print_to_console=True, grid_size=100): ...
```

| Member | What it does |
|---|---|
| `log_info`/`log_warning`/`log_error(msg, source=None)` | Records a timestamped entry (kept in a bounded ring buffer) and prints it unless `print_to_console=False`. |
| `toggle_overlay()` / `toggle_colliders()` / `toggle_grid()` | What F1/F2/F3 call. |
| `grid_size` | World-space pixels between grid lines (F3), default 100. |
| `draw_overlay(screen, scene=None)` | FPS, scene name/object count, and recent log lines, color-coded by level. |
| `draw_colliders(screen, scene, camera=None)` | Outlines every `Collider2D` in the scene - a rectangle for `BoxCollider2D`, an actual circle for `CircleCollider2D` (dispatches on `.shape`, so both draw correctly from one call) - green for solid, red for trigger. |
| `draw_grid(screen, camera=None)` | Vertical/horizontal lines every `grid_size` world pixels, each labelled with its world coordinate; the `x=0`/`y=0` axes are highlighted so the origin is easy to spot. Only draws the range actually visible on screen, however far the camera has scrolled. |

```python
DebugManager.log_info("Level loaded")
# F1/F2/F3 are already wired up by Engine - press them while the game runs.
```

---

## Part 14 - The engine shell: Engine

### `engine/core/app.py`

- **Responsibility:** The window, the clock, the main loop. The only
  engine file `main.py` needs to import directly.

```python
class Engine:
    MAX_DELTA_TIME = 0.05
    def __init__(self, width=1280, height=720, title="Pygame Engine",
                 fps=60, background_color=(30, 30, 35)): ...
```

**The loop, every frame:** measure elapsed time (`clock.tick`), clamp it
to `MAX_DELTA_TIME` → pump events → `Input.update()` →
`debug.update()` → `Scene.update(delta_time)` → clear the screen →
`debug.draw_grid()` → `Scene.render()` → `debug.draw_colliders()` →
`debug.draw_overlay()` → flip.

**Why the clamp:** a debugger pause or a window-drag stall could hand the
next frame a huge raw `delta_time` - enough to tunnel a fast body clean
through a thin wall, or apply a massive single burst of gravity. Clamping
to 50ms means physics never takes a step more dangerous than "20 FPS
worth of movement," no matter how long the real stall was.

| Member | What it does |
|---|---|
| `screen`, `clock`, `scene_manager`, `debug`, `input` | The engine's owned subsystems. |
| `active_scene` (property) | `scene_manager.active_scene`. |
| `load_scene(name, scene)` | Registers and immediately activates. |
| `run()` | Blocks, running the loop until the window closes or `quit()` is called. |
| `quit()` | Stops the loop after the current frame. |

Keys: **F1** overlay, **F2** colliders, **F3** grid (all via
`_handle_events()`, which also handles the window's close button).

```python
engine = Engine(width=1280, height=720, title="My Game", fps=60)
engine.load_scene("main", my_scene)
engine.run()
```

---

## Part 15 - Example content

Everything here is demonstration, not engine code - `engine/` never
imports from `examples/`, and deleting this whole folder leaves a fully
working engine with nothing to run yet.

### `examples/example_scene.py`

- **Responsibility:** `build_example_scene()` - builds the bundled demo:
  a double-jump-enabled character (a colored square from
  `create_square`), a platform (`create_rectangle`), a purely decorative
  circle (`create_circle`), and a small HUD (a jump counter + a reset
  button) built from the UI system.

The character's collider is given an **explicit** size
(`create_square` passes it through automatically) rather than
auto-measured - the recommended pattern from Part 4, since it means the
hitbox can never change shape later if an `Animator` were added.

```python
def build_example_scene():
    scene = Scene()
    character = create_square(x=100, y=100, size=48, color=(90,160,230), name="Character")
    character.add_component(Rigidbody2D(gravity=900, use_gravity=True, drag=3.0))
    controller = character.add_component(PlayerController(
        speed=200, jump_force=500, movement_type="platformer", max_jumps=2))
    character.add_component(ResetOnClick())
    scene.add_game_object(character)
    # ... platform, decoration, HUD ...
    return scene
```

Write more functions like this one (in this file, or new files under
`examples/`) for more levels - `main.py` just calls whichever one it
wants.

### `examples/scripts/reset_on_click.py`

- **Responsibility:** `ResetOnClick` - attach to any GameObject;
  remembers its position at `start()`, exposes `reset_position()` to snap
  back to it (and zero any `Rigidbody2D` velocity). Wire a `UIButton`'s
  `on_click` to it for an instant "restart" button.

```python
class ResetOnClick(Component):
    def start(self): ...           # captures the starting position
    def reset_position(self, _button=None): ...   # accepts an optional arg so
                                                     # it works directly as an on_click callback
```

### `examples/scripts/jumps_hud.py`

- **Responsibility:** `JumpsHUD` - keeps a `UIText` label in sync with a
  `PlayerController`'s `jumps_remaining`, every frame. A small example of
  a script that reads from one component and writes to another without
  either needing to know the other exists.

```python
class JumpsHUD(Component):
    def __init__(self, controller, label): ...
    def update(self, delta_time):
        self.label.set_text(f"Jumps: {self.controller.jumps_remaining}/{self.controller.max_jumps}")
```

---

## Part 16 - The entry point: main.py

```python
from engine.core.app import Engine
from engine.components.camera import Camera
from engine.core.game_object import GameObject
from examples.example_scene import build_example_scene


def main():
    engine = Engine(width=1920, height=1080, title="PygamE", fps=60)

    scene = build_example_scene()
    engine.load_scene("main", scene)

    character = scene.find_game_object("Character")
    camera_object = GameObject(name="Main Camera")
    camera = camera_object.add_component(Camera(target=character, follow_speed=6.0, smooth_follow=True))
    scene.add_game_object(camera_object)
    scene.set_active_camera(camera)

    engine.run()


if __name__ == "__main__":
    main()
```

That's the whole file. If you want to change what the demo does:

- **Different level layout** → edit/replace `examples/example_scene.py`, not this file.
- **Different gameplay scripts** → edit `examples/scripts/`, not this file.
- **Window size/title/fps** → the `Engine(...)` call right here.
- **Camera feel** → `follow_speed` in the `Camera(...)` call; `smooth_follow=False` for zero lag; drop the camera lines entirely (or `target=None`) for a static, unshifted world.

---

## Performance

### What was slow, and why

Before this update, checking collisions worked like this: every
`Rigidbody2D`, on every axis, every frame, asked the `Scene` for *every
solid collider in the entire scene* (`Scene.get_components(BoxCollider2D)`,
which itself scanned every GameObject). For `n` objects, that's roughly
`n` rigidbodies × 2 axes × an `O(n)` scan = **O(n²)** work per frame -
fine for a handful of objects, clearly frame-rate-dropping once a scene
reached a few hundred, exactly matching "it lags once I add a lot of
objects."

### What changed

1. **`Scene.get_components()` is now indexed**, not a linear scan. Every
   component is cached under its own exact class; a query walks the
   (small) set of *distinct classes* present in the scene, not every
   object. A scene with a thousand objects that all share a handful of
   component classes is just as fast to query as one with ten objects.
   The cache is invalidated (a cheap dirty flag, not a rebuild) whenever
   a component or GameObject is added/removed, or a GameObject's `active`
   flag changes - see `GameObject.active`'s property setter and
   `Scene._on_active_changed()` in Part 2/Part 12.

2. **`SpatialHash`** (Part 4) buckets colliders into fixed-size cells
   (default 128px). `Rigidbody2D` and trigger processing now query "what's
   near this specific rect" instead of "give me everything" - for
   reasonably spread-out objects, this turns collision broad-phase from
   `O(n²)` into roughly `O(n)` overall. It's kept up to date
   *incrementally* (each collider re-registers itself the moment its own
   shape/position updates, and skips the update entirely if its bounding
   box hasn't actually changed since the last time - free for anything at
   rest) rather than rebuilt once per frame, specifically so it's never
   stale *within* a single frame: if object B already moved earlier this
   frame, object A's query later in the same frame correctly sees B's new
   position, not a snapshot from before the frame started.

3. **Viewport culling**: `Scene._render_world()` skips any sprite whose
   (anchor-adjusted, pre-rotation) bounding box doesn't reach the screen
   at all, before doing any of the more expensive rotate/scale/blit work.
   A scene with thousands of off-screen objects doesn't pay for drawing
   them.

### Measured numbers

All measured on the same machine (results will vary with yours, but the
*shape* of the improvement - roughly linear rather than quadratic - is
what matters).

**Worst case: every object is a fully independent, actively-falling
`Rigidbody2D`** (an extreme scenario - even professional physics engines
need object "sleeping" to stay fast here):

| Objects (all dynamic) | ms/frame |
|---:|---:|
| 50 | 0.49 |
| 300 | 5.00 |
| 600 | 10.61 |
| 1000 | 18.36 |

**Realistic mix: a few dozen active dynamic objects (player + enemies)
plus thousands of static scenery/platform objects** (no `Rigidbody2D` at
all on the static ones - the common case for most of a level's geometry):

| Static objects | Dynamic objects | ms/frame |
|---:|---:|---:|
| 200 | 10 | 0.31 |
| 1000 | 20 | 1.28 |
| 5000 | 30 | 5.44 |

A 60 FPS frame has a 16.67ms budget. The realistic scenario has enormous
headroom even at 5000 objects; the "everything is simultaneously falling"
worst case is the kind of load that would strain almost any 2D physics
implementation without further work (object sleeping - skipping
simulation entirely for bodies that have been at rest for N consecutive
frames, waking them only when disturbed - is the standard next step for
anyone who genuinely needs thousands of *simultaneously active* dynamic
bodies; it's a meaningful enough feature, with its own correctness
subtleties around waking neighbours, that it's left as a documented
extension rather than rushed into this pass).

### If your game still lags

- Give static geometry (platforms, walls, scenery) **no `Rigidbody2D` at
  all** - a bare `BoxCollider2D` is far cheaper, and is all a static
  object needs to be collided against.
- Check `SpatialHash`'s `cell_size` (default 128, set via
  `Scene().spatial_hash.cell_size` right after creating the scene) isn't
  badly mismatched to your object sizes - cells much larger than your
  objects mean more candidates per query than necessary; cells much
  smaller mean an object spans (and must be checked against) more cells.
- Profile before guessing further - `cProfile`/`pstats` on `Scene.update()`
  will point at whatever's actually slow in *your* scene.

---

## Anchors, in depth

### The bug report this section is about

*"This whole topleft/topright/center/bottom thing feels a bit
imprecise."* Investigating this turned up a real design gap - not a math
error.

### What was actually wrong

`BoxCollider2D`'s anchor math itself was (and is) exact - verified for
all 9 anchors against hand-computed expected positions. The real problem:
**`SpriteRenderer` had no anchor concept at all** and always drew from
the transform position as a top-left corner, full stop. So the moment you
gave a collider any anchor other than `"topleft"` (very reasonably -
`"center"` is a completely natural choice for a lot of objects), the
collider would be positioned correctly while the sprite kept drawing as
if nothing had changed - a visible mismatch between where the hitbox
actually was and where the sprite appeared, that got *worse* the further
the chosen anchor was from `"topleft"`.

The same gap existed for the new `CircleCollider2D` in its first draft: it
treated the transform position as the circle's center directly, with no
anchor concept, which put it out of alignment with a `SpriteRenderer`
showing a circle drawn centered in its own (default-anchored) surface.

### The fix

One function, `anchor_to_topleft_offset()` (`engine/utils/anchors.py`,
Part 1), is now the **single, shared implementation** every anchor-aware
class calls:

- `SpriteRenderer` gained an `anchor` parameter (default `"topleft"`,
  matching the old behaviour exactly - no regression for existing code).
- `CircleCollider2D` gained an `anchor` parameter too (default
  `"topleft"`, applied to its `(diameter, diameter)` bounding square).

Set the **same** anchor on a `SpriteRenderer` and its collider, and they
now agree exactly:

```python
go.add_component(SpriteRenderer(sprite=img, anchor="center"))
go.add_component(BoxCollider2D(size=img.get_size(), anchor="center"))
# (go.x, go.y) is now the CENTER of both the sprite and its hitbox
```

With the shared default (`"topleft"` on both), a circle sprite drawn
centered in its own surface and a default `CircleCollider2D` line up with
zero extra offset math - which is exactly the scenario this section
opened with.

### If it still looks "not quite right"

Two things this fix does **not** address, because they aren't anchor
bugs:

- **Sprite padding.** If your source art has transparent space around the
  actual visible character (very common with hand-exported sprite
  sheets), the collider - sized to the *full image*, padding included -
  will extend visibly past the art. This isn't a mismatch between sprite
  and collider; it's the true size of the image you gave it. Either trim
  the art, or pass an explicit `size=(w, h)` smaller than the full image.
- **Scale.** `Transform.scale` is rendered (Part 3) but does **not**
  resize a collider - visually scaling an object doesn't change its
  hitbox. Call `set_size()`/`set_radius()` explicitly if the two need to
  track each other.

---

## Quick index

| Symbol | Lives in |
|---|---|
| `Animator.play(name, loop, reverse)` | `engine/components/animator.py` |
| `AudioSource.play() / load(path) / set_volume(v)` | `engine/components/audio_source.py` |
| `BoxCollider2D.set_size(w,h)` / `snap_*_to(coord)` | `engine/components/box_collider2d.py` |
| `Camera.get_offset(w,h)` / `set_target(t, snap)` | `engine/components/camera.py` |
| `CircleCollider2D.set_radius(r)` | `engine/components/circle_collider2d.py` |
| `Collider2D.overlaps(other)` / `on_trigger_enter` | `engine/components/collider2d.py` |
| `DebugManager.toggle_overlay/colliders/grid()` | `engine/core/debug_manager.py` |
| `Engine.load_scene(name, scene)` / `run()` | `engine/core/app.py` |
| `GameObject.add_component(c)` / `.active` | `engine/core/game_object.py` |
| `Input.is_pressed / is_just_pressed / mouse_*` | `engine/input/input_manager.py` |
| `Key.*` / `normalize_key(key)` | `engine/input/key.py` |
| `PlayerController.jumps_remaining` / `_on_jump()` | `engine/components/player_controller.py` |
| `Rigidbody2D.add_impulse / add_force` | `engine/components/rigidbody2d.py` |
| `Scene.get_components(cls)` / `find_game_object(name)` | `engine/core/scene.py` |
| `SpatialHash.query(rect)` | `engine/core/spatial_hash.py` |
| `SpriteRenderer.get_anchor_offset()` | `engine/components/sprite_renderer.py` |
| `Transform.translate(dx,dy)` | `engine/components/transform.py` |
| `UIButton.on_click` | `engine/ui/ui_button.py` |
| `UILayoutGroup.add_item(go)` | `engine/ui/ui_layout.py` |
| `Vector2.lerp(other, t)` | `engine/utils/vector2.py` |
| `anchor_to_topleft_offset(anchor,w,h)` | `engine/utils/anchors.py` |
| `create_rectangle/square/circle/triangle/line` | `engine/primitives.py` |
| `load_spritesheet_animations(json, img)` | `engine/utils/spritesheet_loader.py` |

## Cookbook - "I want to..."

| I want to... | Go to |
|---|---|
| Add a new object to a level | `examples/example_scene.py` (or your own scene file) - build a `GameObject`, `add_component(...)`, `scene.add_game_object(...)`. |
| Give the player a new ability | Subclass `PlayerController`, override a hook (Part 7). |
| Make the camera snappier/laggier, or turn it off | `follow_speed` in `main.py`'s `Camera(...)` call; `target=None` for no camera. |
| Add a coin/pickup | New file under `examples/scripts/`, modeled on `reset_on_click.py`: subclass `Component`, subscribe to a trigger's `on_trigger_enter`. |
| Fix "my hitbox doesn't match my sprite" | Set the **same** `anchor` on the `SpriteRenderer` and the collider - see [Anchors, in depth](#anchors-in-depth). |
| Use a precise round hitbox instead of a bounding box | `CircleCollider2D` (Part 4), or `create_circle(precise_collider=True)`. |
| Play a sound or music | `AudioSource` (Part 10). |
| Load a full sprite-sheet animation | `load_spritesheet_animations()` (Part 1) → `Animator(animations=...)`. |
| See collider outlines / a coordinate grid while playing | **F2** / **F3** - built in, nothing to wire up. |
| My game lags with lots of objects | Read [Performance](#performance) - check whether static geometry has an unnecessary `Rigidbody2D`. |
| Add a second level | New `build_*_scene()` function, then `engine.load_scene("name", build_it())` / `scene_manager.set_active("name")`. |
| Add a UI menu | `UIPanel` + `UIText` + `UIButton`, optionally `UILayoutGroup` to stack them (Part 9). |

## What changed in this update

- **Performance**: indexed component lookup, a `SpatialHash` broad-phase
  for collisions/triggers, and viewport culling for rendering - see
  [Performance](#performance) for the mechanism and measured numbers.
- **Anchors fixed**: `SpriteRenderer` and `CircleCollider2D` now support
  the same `anchor` system `BoxCollider2D` already had, sharing one
  implementation (`engine/utils/anchors.py`) - see
  [Anchors, in depth](#anchors-in-depth) for what was actually wrong and
  why.
- **F3 debug grid**, alongside the existing F1 (overlay) and F2
  (colliders).
- **`CircleCollider2D`** - precise circle-vs-circle/circle-vs-box overlap
  testing (trigger/overlap-only; see its scope note in Part 4).
- **`AudioSource`** - sound effects and looping music via `pygame.mixer`;
  see `requirements.txt` for why no extra audio dependency was added.
- **`load_spritesheet_animations()`** - a spritesheet + JSON atlas loader
  feeding directly into `Animator`, supporting both common atlas JSON
  shapes and correctly ordering frames by their numeric index rather than
  JSON declaration order.
- **Multi-jump**: `PlayerController(max_jumps=N)` for double/triple jump.
- **Restructured folders**: engine internals moved under `engine/core/`;
  the demo moved out of the engine entirely into `examples/` (with its
  own `examples/scripts/`) to make the engine/content boundary a physical
  folder boundary, not just a convention. `engine/` never imports from
  `examples/` - delete the folder and the engine still works.
- **Removed** the earlier demo's specific "Player"/"Coin" objects and
  assets entirely; the example now uses `engine.primitives` exclusively
  (no external image files anywhere in the project).
- Documentation consolidated into this one file (+ its Russian
  translation) rather than spread across several.
