# PygamE — 2D Engine (ECS Framework)

> **PygamE** is a compact 2D engine and framework built on **Pygame** with a Unity-style component architecture (ECS: `GameObject` + `Component`) for building 2D games and interactive applications. Out of the box: deterministic fixed-timestep physics (swept AABB, collision layers and masks, collision/trigger callbacks), a transform hierarchy with render interpolation, screen-space UI with anchors, a pooled particle system, tilemap baking, a camera, animation, audio with crossfading and positional sound, and static services (`Input`, `EventBus`, `PlayerPrefs`, `Debug`). Architectural advantages: physics never depends on the frame rate, rendering and simulation only pay for what's visible and what's actually moving, scenes can be switched safely mid-frame, and the only dependency is Pygame.

## Table of Contents

1. [Overview and Architectural Principles](#1-overview-and-architectural-principles)
2. [Requirements and Installation](#2-requirements-and-installation)
3. [Quick Start](#3-quick-start)
4. [Engine Framework and Lifecycle](#4-engine-framework-and-lifecycle)
   - 4.1. [Engine and the Main Loop](#41-engine-and-the-main-loop)
   - 4.2. [Scene Management (Scene and SceneManager)](#42-scene-management-scene-and-scenemanager)
   - 4.3. [GameObject and the Component Model](#43-gameobject-and-the-component-model)
   - 4.4. [The Transform Hierarchy](#44-the-transform-hierarchy)
5. [Physics System](#5-physics-system)
   - 5.1. [Rigidbody2D](#51-rigidbody2d)
   - 5.2. [Colliders (BoxCollider2D, CircleCollider2D)](#52-colliders-boxcollider2d-circlecollider2d)
   - 5.3. [Collision Layers and Masks](#53-collision-layers-and-masks)
6. [Input System](#6-input-system)
7. [User Interface (UI) System](#7-user-interface-ui-system)
   - 7.1. [Canvas and Screen-Space UI](#71-canvas-and-screen-space-ui)
   - 7.2. [UI Elements (UIText, UIButton, UIPanel, UIHealthBar)](#72-ui-elements-uitext-uibutton-uipanel-uihealthbar)
   - 7.3. [UI Anchors and Pivots](#73-ui-anchors-and-pivots)
8. [Particle System](#8-particle-system)
9. [Graphics, Animation, and Rendering](#9-graphics-animation-and-rendering)
   - 9.1. [SpriteRenderer and Sprite Anchors](#91-spriterenderer-and-sprite-anchors)
   - 9.2. [Camera](#92-camera)
   - 9.3. [Animation and Spritesheets (Animator)](#93-animation-and-spritesheets-animator)
   - 9.4. [Tilemap Optimization (Baking)](#94-tilemap-optimization-baking)
10. [Static Services and Utilities](#10-static-services-and-utilities)

## 1. Overview and Architectural Principles

PygamE is built around one idea: **the world is made of objects, and an object's behaviour is made of components you attach to it**. A `GameObject` can't draw itself, fall, or react to a keypress — all of that is done by components you attach to it.

| ECS role | What it is in PygamE | Responsibility |
| :--- | :--- | :--- |
| **Entity** | `GameObject` | A named container: a `Transform`, a list of components, the `active` / `is_static` / `layer` flags, and a parent-child hierarchy. |
| **Component** | `Component` and its subclasses: `SpriteRenderer`, `Rigidbody2D`, `BoxCollider2D`, `Animator`, `PlayerController`, `Camera`, `ParticleSystem`, `UIText`, etc. | Data and behaviour. Your own gameplay code is components too (`class Enemy(Component)`). |
| **System** | `PhysicsWorld` and `RenderSystem` (created by every `Scene`), plus the static services `Input`, `AudioManager`, `EventBus`, etc. | Cross-cutting logic over many components: physics, rendering, audio, events. |
| **Scene** | `Scene` | Owns the objects and the systems. Its indexes (by component type, by update order) are maintained incrementally. |
| **Engine** | `Engine` | The window, the clock, and the main loop. |

> **On terminology.** "ECS" in PygamE means a Unity-style component model (a component holds both data and behaviour), not a data-oriented ECS with bare data and separate systems.

### Architectural Principles

1. **Two clocks.** Physics runs in `fixed_update` at a fixed timestep (60 Hz by default); gameplay, animation, and the camera run in `update` with a variable `dt`. Under a frame-rate drop, physics runs several steps back to back instead of "stretching" a single one: the result depends only on the *number of steps*, never on the frame rate.
2. **Render interpolation.** Between physics steps, body positions are interpolated (`Time.alpha`), so motion stays smooth on 144 Hz+ monitors.
3. **Global update order.** `Component.update_order` applies across the whole scene, not just within one object: physics (−100) → colliders (−90) → gameplay (0) → camera (100). The camera always sees the frame's final positions.
4. **Pay only for what's used.** The scene only calls hooks that are actually *overridden*; static objects (`is_static=True`) skip physics and recomputation entirely; only sprites visible to the camera are drawn; tilemaps bake down to a handful of blits.
5. **Safe mid-frame.** `GameObject.destroy()`, `Scene.remove_game_object()`, and `SceneManager.change_scene()` called from `update`, a collision callback, or a button click are applied at the end of the current phase — the iteration loop never breaks.
6. **Static services.** `Input`, `Time`, `EventBus`, `AudioManager`, `PlayerPrefs`, `Debug`, `SceneManager`, and `CollisionLayers` are reachable from anywhere without a reference to `Engine`.
7. **Predictable coordinates.** Units are pixels, the Y axis points down, and angles are in degrees, clockwise.

### The Engine's Frame

```text
Engine.run()
 └─ every frame:
     ├─ pygame events → Input; debug hotkeys (F1–F4)
     ├─ SceneManager.update(dt) → Scene.tick(dt)
     │    ├─ 0…N times: Scene.fixed_update(1/60)
     │    │     ├─ Component.fixed_update()   (apply forces)
     │    │     └─ PhysicsWorld.step()        (move → contacts → callbacks)
     │    ├─ Scene.update(dt)                 (Component.update() in update_order)
     │    └─ deferred destroys and scene changes
     ├─ AudioManager.update(dt)               (fades, volume)
     └─ draw: background → Scene.draw() [world through the camera → UI on top] → debug overlays → flip
```

### Key Features

- **Physics:** fixed timestep, swept-AABB with no tunneling or jitter, gravity / acceleration / friction / drag / mass, collision layers and masks, `enter` / `stay` / `exit` events for both collisions and triggers. → [Section 5](#5-physics-system)
- **Scenes and objects:** `start` / `update` / `fixed_update` / `draw` / `destroy` lifecycle, a cached transform hierarchy (`is_dirty`), deferred destruction. → [Section 4](#4-engine-framework-and-lifecycle)
- **Rendering:** camera-based culling, a spatial grid, tilemap baking, a cache of rotated/scaled sprites, skipping off-screen animation. → [Section 9](#9-graphics-animation-and-rendering)
- **UI:** a screen-space Canvas, `UIText` / `UIButton` / `UIPanel` / `UIHealthBar`, nine anchors and pivots, world-space UI. → [Section 7](#7-user-interface-ui-system)
- **Particles:** an `ObjectPool`-backed emitter, colour gradients, scaling, fading. → [Section 8](#8-particle-system)
- **Services:** `Input` with string key names, `EventBus` (global and per-object), `ObjectPool`, `PlayerPrefs`, `AudioManager`, `Debug`. → [Section 10](#10-static-services-and-utilities)

---

## 2. Requirements and Installation

**Requirements**

| Component | Version |
| :--- | :--- |
| Python | 3.8+ (the engine doesn't use syntax newer than 3.8; tested on 3.12) |
| pygame | 2.x (tested on 2.6.1) |
| Other dependencies | none |

**Installation**

```bash
git clone https://github.com/PcDomDev/PygamE.git PygamE
cd PygamE

python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux / macOS: source .venv/bin/activate

pip install -r requirements.txt     # or simply: pip install pygame
```

**Project Structure**

```text
engine/                    the engine itself — no dependency on your game
├── core/                    app.py (Engine) · scene.py · scene_manager.py · game_object.py
│                            game_time.py (Time) · event_bus.py · object_pool.py
│                            player_prefs.py · spatial_hash.py · debug_manager.py
├── components/              transform · sprite_renderer · animator · camera · rigidbody2d
│                            collider2d / box_collider2d / circle_collider2d
│                            particle_system · audio_source · player_controller · component
├── physics/                 physics_world.py · layers.py · collision.py
├── rendering/               render_system.py · surface_cache.py · tilemap.py
├── input/                   input_manager.py (Input) · key.py (Key)
├── ui/                      ui_element · canvas · ui_text · ui_button · ui_panel
│                            ui_health_bar · ui_layout · ui_style
├── audio/                   audio_manager.py
├── utils/                   vector2 · anchors · fonts · spritesheet_loader · warnings
└── primitives.py            create_rectangle / square / circle / triangle / line factories
tests/                     test_engine.py — headless tests · benchmark.py — measurements
examples/                  showcase.py — a demo level exercising every system
main.py                    your game's entry point
requirements.txt
```

Imports always go from the project root: `from engine.core.app import Engine`. `engine/` knows nothing about your game — your game's code lives outside it.

### Verifying the Install (Smoke Test)

The script below opens no window and needs no sound card (it uses SDL's "dummy" drivers): it creates a scene, drops a body onto a floor, and checks that physics did its job. Save it as `smoke_test.py` in the **project root** and run it.

```python
# smoke_test.py — verify the PygamE install without a window or a sound card
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")   # no window
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # no sound

import pygame

from engine.components.box_collider2d import BoxCollider2D
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.game_object import GameObject
from engine.core.scene import Scene

pygame.init()
pygame.display.set_mode((320, 240))

scene = Scene("smoke")

floor = GameObject(0, 200, name="Floor", is_static=True)
floor.add_component(BoxCollider2D(size=(320, 40)))
scene.add_game_object(floor)

ball = GameObject(100, 0, name="Ball")
ball.add_component(BoxCollider2D(size=(20, 20)))
body = ball.add_component(Rigidbody2D())
scene.add_game_object(ball)

for _ in range(180):                 # 3 seconds of simulation at 60 fps
    scene.tick(1 / 60)

assert body.is_grounded, "the body should have landed on the floor"
assert abs(ball.transform.world_y - 180) < 1e-6, ball.transform.world_y   # floor top 200 − height 20
print("PygamE is working: the body landed at y =", ball.transform.world_y)
```

```bash
python smoke_test.py                     # expect the line "PygamE is working: ..."
python -m unittest discover tests        # the full test suite; expect "OK"
python examples/showcase.py              # a playable demo (opens a window)
python examples/showcase.py --headless 300 shot.png   # the same, headless, with a screenshot
```

If `smoke_test.py` finishes without error, the install is correct: Python, pygame, and the engine are working together.

---

## 3. Quick Start

A minimal game: a platformer with a double jump, coins, a camera, and a score counter. Save it as `main.py` in the project root.

```python
# main.py
import pygame

from engine.components.camera import Camera
from engine.components.circle_collider2d import CircleCollider2D
from engine.components.player_controller import PlayerController
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.app import Engine
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.primitives import create_circle, create_rectangle, create_square
from engine.ui.ui_text import UIText


class GameScene(Scene):
    def start(self):
        super().start()                       # required: starts everything already added
        self.score = 0

        # Ground and platform — static: they skip physics and never get recomputed
        self.add_game_object(create_rectangle(-1000, 500, 3000, 60, color=(96, 72, 48),
                                              name="Ground", is_static=True))
        self.add_game_object(create_rectangle(420, 380, 180, 24, color=(120, 90, 60),
                                              name="Platform", is_static=True))

        # The player: a body with gravity + controls
        player = create_square(100, 300, size=40, color=(70, 130, 230), name="Player",
                               add_rigidbody=True)
        player.get_component(Rigidbody2D).gravity = 900
        player.add_component(PlayerController(speed=240, jump_force=460,
                                              movement_type="platformer", max_jumps=2))
        self.add_game_object(player)

        # Coins — triggers: passable, but they report the touch
        for x, y in ((300, 460), (470, 340), (540, 340), (700, 460)):
            coin = create_circle(x, y, radius=12, color=(255, 210, 60), name="Coin",
                                 precise_collider=True, is_static=True)
            collider = coin.get_component(CircleCollider2D)
            collider.is_trigger = True
            collider.on_trigger_enter.append(self.on_coin_touched)
            self.add_game_object(coin)

        # The camera follows the player
        camera_object = GameObject(name="Camera")
        camera = camera_object.add_component(Camera(target=player, follow_speed=6))
        self.add_game_object(camera_object)
        self.set_active_camera(camera)

        # HUD: an anchor pins the text to a screen corner
        hud = GameObject(12, 12, name="HUD")
        self.score_text = hud.add_component(UIText("Coins: 0", anchor="TopLeft"))
        self.add_game_object(hud)

    def on_coin_touched(self, coin_collider, other_collider):
        if other_collider.game_object.name == "Player":
            coin_collider.game_object.destroy()     # safe to call right inside the callback
            self.score += 1
            self.score_text.set_text(f"Coins: {self.score}")


def main():
    engine = Engine(1280, 720, "PygamE — Quick Start", fps=144,
                    background_color=(120, 172, 226))
    engine.change_scene(GameScene)            # creates the scene, calls start()
    engine.run()


if __name__ == "__main__":
    main()
```

```bash
python main.py
```

**Controls:** `A` / `D` or `←` / `→` to move, `Space` to jump (a second time in mid-air), `Esc` closes the window if you handle it yourself (see [Input](#6-input-system)). **Debug:** `F1` stats, `F2` colliders, `F3` world grid, `F4` log console.

What just happened:

1. `Engine` opened the window and started the main loop ([4.1](#41-engine-and-the-main-loop)).
2. `change_scene(GameScene)` created the scene and called `start()`, where we built the world out of `GameObject`s ([4.2](#42-scene-management-scene-and-scenemanager), [4.3](#43-gameobject-and-the-component-model)).
3. Physics runs at a fixed timestep, and `PlayerController` reads input every frame ([5.1](#51-rigidbody2d), [Input](#6-input-system)).
4. A coin is a static trigger: the callback fires on touch ([5.2](#52-colliders-boxcollider2d-circlecollider2d)).
5. The camera follows the player while the HUD stays put — UI is drawn in screen coordinates ([9.2](#92-camera), [7.1](#71-canvas-and-screen-space-ui)).

---

## 4. Engine Framework and Lifecycle

### 4.1. Engine and the Main Loop

**Description:** `Engine` owns the window, the clock, and the main loop — the only class `main.py` needs. Every frame it feeds events to `Input`, handles the debug hotkeys, calls `SceneManager.update()` (fixed physics steps, then the variable `update`), updates audio, and draws the scene. Physics never depends on the frame rate: `fps` only limits how often the screen is redrawn, while `fixed_fps` sets the physics rate. On exit, `Engine` destroys the active scene (running every `on_destroy`), stops audio, saves any unsaved `PlayerPrefs`, and shuts pygame down.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Engine(...)` | `width: int = 1280, height: int = 720, title: str = "Pygame Engine", fps: int = 60, background_color: tuple = (30, 30, 35), fixed_fps: int = 60, vsync: bool = False, resizable: bool = False, debug: bool = True` | Creates the window and subsystems. `fps=0` means uncapped frame rate; `fixed_fps` is the physics rate in Hz; `vsync=True` requests vertical sync (enables the `SCALED` flag); `resizable` allows resizing the window; `debug=False` disables all debug hotkeys and overlays (a release build). |
| `run()` | — | The blocking main loop. Exits when the window closes or `quit()` is called. Call it last: `engine.run()`. |
| `quit()` | — | Stops the loop after the current frame: `engine.quit()`. |
| `load_scene(name, scene)` | `name: str, scene: Scene` | Registers a ready-made scene instance under a name and makes it active right away; the previous scene, if any, stays alive (see [4.2](#42-scene-management-scene-and-scenemanager)). |
| `change_scene(target, *args, **kwargs)` | `target: a Scene class, instance, or name` | Destroys the current scene and starts a new one: `engine.change_scene(Level1, difficulty=2)`. Wraps `SceneManager.change_scene`. |
| `active_scene` | `Scene or None` (property) | The current active scene. |
| `screen` | `pygame.Surface` | The window's surface. |
| `clock` | `pygame.time.Clock` | The main loop's clock. |
| `input` / `debug` / `audio` | `Input` / `DebugManager` / `AudioManager` | The subsystems the engine owns (the same instances as the static services). |
| `scene_manager` | `SceneManager` | The static scene manager (the class itself). |
| `width`, `height`, `fps`, `background_color`, `running` | `int`, `int`, `int`, `tuple`, `bool` | Window parameters and the loop's running flag. |
| `Engine.MAX_DELTA_TIME` | `float = 0.05` | The upper bound on the variable `dt` passed to `update` (a guard against a spike after a debugger pause). Doesn't affect physics — that has its own limits: `Time.max_frame_time` and `Time.max_fixed_steps`. |

#### Usage Example

```python
import pygame

from engine.core.app import Engine
from engine.core.debug_manager import Debug
from engine.core.scene import Scene


class DemoScene(Scene):
    def start(self):
        super().start()
        self.elapsed = 0.0
        Debug.log("Scene started")

    def update(self, delta_time):
        super().update(delta_time)          # without super(), components never update
        self.elapsed += delta_time
        if self.elapsed > 3.0:              # close the window after 3 seconds
            pygame.event.post(pygame.event.Event(pygame.QUIT))


def main():
    engine = Engine(
        width=1280, height=720, title="Demo",
        fps=0,                # uncapped frame rate (or vsync=True)
        fixed_fps=60,         # physics always runs at 60 steps per second
        resizable=True,
        debug=True,           # F1–F4 work; False for a release build
    )
    engine.change_scene(DemoScene)
    engine.run()


if __name__ == "__main__":
    main()
```

### 4.2. Scene Management (Scene and SceneManager)

**Description:** `Scene` is a collection of `GameObject`s plus the systems that drive them: `physics` (`PhysicsWorld`) and `render_system` (`RenderSystem`). Lifecycle hooks: `start()` (once, on load), `update(dt)` (every frame), `fixed_update(dt)` (every physics step), `draw(screen)`, and `destroy()` (on exit). The base `update` / `fixed_update` / `draw` **are what run your components**, so a subclass must always call `super()`. `SceneManager` is a static manager: `SceneManager.change_scene(Level1Scene)` destroys the current scene (`destroy()` releases the objects, subscriptions, and physics/render structures — the old scene is then garbage-collected) and starts the new one (`start()`). If a switch is requested *during a frame* (a button click, a collision callback), it's deferred to the end of that frame; at any other time (program startup, tests) it happens immediately.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Scene(name)` | `name: str = "Scene"` | Creates an empty scene. The default name is replaced by the class name when loaded through `SceneManager`. |
| `start()` | — | Hook: called once, on load. Build your world here and call `super().start()`. |
| `update(delta_time)` | `delta_time: float` | Hook: the variable step; runs component `update` in `update_order`, then applies deferred removals. |
| `fixed_update(fixed_delta_time)` | `fixed_delta_time: float` | Hook: one physics step — component `fixed_update` first, then `physics.step()` and the collision callbacks. |
| `draw(screen)` | `screen: pygame.Surface` | Hook: draws the world through the camera, then the UI. `render(screen)` is the old name; it forwards here. |
| `destroy()` | — | Hook: destroys every object and clears the scene's systems. Called by the manager when leaving the scene. |
| `add_game_object(go)` | `go: GameObject` | Adds the object **along with its children** and starts it right away: `scene.add_game_object(player)`. |
| `remove_game_object(go)` | `go: GameObject` | Takes the object out of the scene without destroying it. Inside the loop, this is deferred to the end of the phase. |
| `destroy_game_object(go)` | `go: GameObject` | Destroys the object (`on_destroy`, children, subscriptions). `go.destroy()` does the same. |
| `find_game_object(name)` | `name: str` | The first object with that name, or `None`. |
| `find_game_objects_with_tag(tag)` | `tag: str` | The list of objects with that tag. |
| `get_components(component_type)` | `component_type: type` | Every live component of that type (subclasses included) on an active object — a fresh list, safe to iterate: `scene.get_components(UIButton)`. |
| `get_component(component_type)` | `component_type: type` | The first component of that type, or `None`. |
| `set_active_camera(camera)` | `camera: Camera` | Sets which camera the world is drawn through. The `active_camera` property returns it. |
| `screen_to_world(pos)` / `world_to_screen(pos)` | `pos: tuple or Vector2` | Coordinate conversion through the active camera: `scene.screen_to_world(Input.mouse_position())`. |
| `tick(frame_dt)` | `frame_dt: float` | Simulates one frame with no window: accumulates time, runs 0…N `fixed_update` steps, then `update`. For tests and tools. Returns how many physics steps ran. |
| `game_objects`, `physics`, `render_system` | `list`, `PhysicsWorld`, `RenderSystem` | The scene's object list and its systems. |
| `entity_count`, `active_entity_count`, `draw_calls` | `int` | Total objects, active objects, and draw calls in the last frame. |
| `is_started`, `is_destroyed`, `name` | `bool`, `bool`, `str` | Lifecycle state and the scene's name. |
| `SceneManager.change_scene(...)` | `target, *args, immediate: bool = None, destroy_previous: bool = True, **kwargs` | Switches scenes: `target` is a `Scene` class, instance, or registered name; `*args` / `**kwargs` go to the class constructor. Returns the new scene, or `None` if the switch was deferred to the end of the frame. `immediate=True/False` forces one behaviour or the other. |
| `SceneManager.register(name, scene_or_class)` | `name: str, scene_or_class: Scene or type` | Registers a scene or class: `SceneManager.register("menu", MenuScene)`, then `change_scene("menu")` creates a fresh instance every time. |
| `SceneManager.add_scene(name, scene)` / `set_active(name)` | `name: str, scene: Scene` | The legacy API: register and switch **without** destroying the previous scene (its state is preserved; `start()` runs only the first time it's activated). |
| `SceneManager.get_scene(name)` / `remove_scene(name)` | `name: str` | Get a registered instance / forget it and destroy it. |
| `SceneManager.active_scene` | `Scene or None` | The active scene. |
| `SceneManager.shutdown()` / `reset()` | — | Destroy the active scene (called by `Engine` on exit) / forget everything (tests). |

#### Usage Example

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.core.scene_manager import SceneManager
from engine.ui.ui_button import UIButton
from engine.ui.ui_text import UIText


class MenuScene(Scene):
    def start(self):
        super().start()
        title = GameObject(0, -80, name="Title")
        title.add_component(UIText("My Game", anchor="Center"))
        self.add_game_object(title)

        play = GameObject(0, 0, name="PlayButton")
        button = play.add_component(UIButton("Play", 200, 48, anchor="Center"))
        # The click happens inside a frame — the scene change applies at its end
        button.on_click.append(lambda _button: SceneManager.change_scene(LevelScene, level=1))
        self.add_game_object(play)


class LevelScene(Scene):
    def __init__(self, level=1):
        super().__init__(f"Level{level}")
        self.level = level

    def start(self):
        super().start()
        print(f"Level {self.level} loaded")

    def destroy(self):
        print(f"Level {self.level} unloaded")
        super().destroy()


SceneManager.register("menu", MenuScene)     # by name: a fresh instance every time
SceneManager.change_scene("menu")            # before the loop starts — happens immediately
SceneManager.change_scene(LevelScene, level=2)   # unloads the menu, loads level 2
# In a real game, Engine.run() drives frames; here, one frame by hand:
SceneManager.update(1 / 60)
```

### 4.3. GameObject and the Component Model

**Description:** `GameObject` is a container with a mandatory `Transform`; behaviour is added through components (`add_component`). Components subclass `Component` and override only the hooks they need — the scene calls **only the overridden ones**, so an unused hook costs nothing. Object flags: `active` (an inactive object isn't updated, doesn't take part in physics, and isn't drawn — neither are any of its children; see `active_in_hierarchy`), `is_static` (the object will never move: it skips physics and recomputation, and its collider and sprite are registered once; to move such an object, set `is_static = False` first), and `layer` (the collision layer). `update_order` sets the order components run in, **globally across the whole scene**.

| Component | `update_order` |
| :--- | :---: |
| `Rigidbody2D` | −100 |
| `BoxCollider2D` / `CircleCollider2D` | −90 |
| your gameplay, `Animator`, `PlayerController`, UI | 0 |
| `Camera` | 100 |

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `GameObject(...)` | `x: float = 0.0, y: float = 0.0, name: str = "GameObject", layer: int or str = 0, tag: str = None, is_static: bool = False, parent: GameObject = None` | Creates an object with a `Transform` at `(x, y)`. `parent` immediately attaches it to a parent. |
| `add_component(component)` | `component: Component` | Attaches a component and returns it: `body = go.add_component(Rigidbody2D())`. If the object is already in a scene, the component starts right away. |
| `get_component(cls)` / `get_components(cls)` / `has_component(cls)` | `cls: type` | The first component of that type (or `None`) / a list of all of them / whether it exists. Look up siblings in `start()`, not `__init__`. |
| `remove_component(component)` | `component: Component` | Detaches a component (its `on_destroy` runs). The `Transform` can't be removed. |
| `transform` | `Transform` | Always present — no need to check for `None`. |
| `name`, `tag` | `str`, `str` | Name and tag for lookups (`scene.find_game_object("Player")`). |
| `active` / `active_in_hierarchy` | `bool` | The object's own flag / "active and every ancestor is too". |
| `is_static` | `bool` | Will never move — see the description above. |
| `layer` | `int or str` | The collision layer, inherited by default by its colliders: `go.layer = "enemy"` (see [5.3](#53-collision-layers-and-masks)). |
| `parent` / `children` | `GameObject or None` / `list` | The hierarchy; `children` is the list of children. |
| `set_parent(parent, keep_world_position=False)` | `parent: GameObject or None, keep_world_position: bool` | Changes the parent (details in [4.4](#44-the-transform-hierarchy)). `add_child(child)` and `find_child(name)` are shortcuts. |
| `x`, `y` | `float` | Aliases for the local position: `go.x += 5`. |
| `scene` | `Scene or None` | The scene the object is currently in. |
| `events` | `EventDispatcher` | The object's private event bus (see [EventBus](#eventbus)): `go.events.emit("hit", damage=5)`. `clear_events()` drops its subscriptions. |
| `destroy()` | — | Destroys the object and its children. Deferred to the end of the phase inside the loop, so it's safe to call from callbacks. Runs `on_destroy` on every component. |
| `despawn()` | — | Returns the object to its pool (if it came from a `GameObjectPool`), otherwise calls `destroy()`. |
| `Component.start()` | — | Hook: once, on entering a scene. Look up sibling components here. |
| `Component.update(delta_time)` | `delta_time: float` | Hook: every frame, variable step. Input, animation, visual logic. |
| `Component.fixed_update(fixed_delta_time)` | `fixed_delta_time: float` | Hook: every physics step, **before** the physics step itself — the place for `add_force`. |
| `Component.draw_world(screen, offset_x, offset_y, alpha)` | `screen: Surface, offset_x: int, offset_y: int, alpha: float` | Hook: custom world-space drawing (particles, baked layers). Return the number of blits (or `None`). |
| `Component.on_destroy()` | — | Hook: when the object is destroyed or the component removed — release resources here. |
| `on_collision_enter/stay/exit(collision)` | `collision: Collision2D` | Optional handler methods for physics, on any component (see [5.2](#52-colliders-boxcollider2d-circlecollider2d)). |
| `on_trigger_enter/stay/exit(other)` | `other: Collider2D` | The same, for triggers. |
| `game_object`, `transform`, `events` | — | The owning object, its `Transform`, and its event bus (shortcuts). |
| `enabled` | `bool` | `False` — the component receives no `update` / `fixed_update`. |
| `update_order`, `updates_when_static` | `int = 0`, `bool = True` | Run order (table above). `updates_when_static = False` skips the component on static objects. |

#### Usage Example

```python
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.primitives import create_square


class Spinner(Component):
    """Rotation is a visual effect, so it belongs in update (every frame)."""

    def __init__(self, degrees_per_second=90):
        super().__init__()
        self.degrees_per_second = degrees_per_second

    def update(self, delta_time):
        self.game_object.transform.rotation += self.degrees_per_second * delta_time


class Thruster(Component):
    """Forces are applied in fixed_update — right before the physics step."""

    def start(self):
        self.body = self.game_object.get_component(Rigidbody2D)   # look up siblings in start()

    def fixed_update(self, fixed_delta_time):
        self.body.add_force(0, -1200)       # upward thrust, stronger than gravity (500 px/s²)


class SelfDestruct(Component):
    def __init__(self, seconds):
        super().__init__()
        self.left = seconds

    def update(self, delta_time):
        self.left -= delta_time
        if self.left <= 0:
            self.game_object.destroy()      # deferred to the end of the phase — safe

    def on_destroy(self):
        print(f"{self.game_object.name} destroyed")


scene = Scene("components")
rocket = create_square(200, 300, size=30, name="Rocket", add_rigidbody=True)
rocket.tag = "projectile"
rocket.add_component(Thruster())
rocket.add_component(Spinner(180))
rocket.add_component(SelfDestruct(2.0))
scene.add_game_object(rocket)

for _ in range(150):                         # 2.5 seconds of simulation
    scene.tick(1 / 60)
assert scene.find_game_object("Rocket") is None      # self-destructed
```

### 4.4. The Transform Hierarchy

**Description:** Every `GameObject` gets a `Transform` automatically, holding its position, rotation, and scale. Values come in two flavours: **local** (relative to the parent — this is what's actually stored) and **world** (the result of composing the whole parent chain). `position` is an alias for `local_position`; for an object with no parent, local and world are identical, so code written before you introduce a hierarchy keeps working unchanged. Rotation is in degrees, clockwise (Y points down). World values are cached behind an `is_dirty` flag: changing a transform marks it and its subtree dirty, and reading a world value only recomputes it if it's dirty — an unmoving hierarchy recomputes nothing at all. Even in-place edits (`position.x += 5`) are tracked. For physics bodies, `get_render_xy(alpha)` gives a smoothed position between two physics steps; children are built from the parent's *smoothed* position, so a weapon held by a player never lags behind.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Transform(...)` | `x: float = 0.0, y: float = 0.0, rotation: float = 0.0, scale_x: float = 1.0, scale_y: float = 1.0` | Created automatically inside `GameObject`. |
| `position` / `local_position` | `Vector2` | The local position; supports in-place edits: `t.position.x += 10`. |
| `rotation` / `local_rotation` | `float` | The local rotation, in degrees. |
| `scale` / `local_scale` | `Vector2` (a number is also accepted) | The local scale: `t.scale = 2`. Colliders don't scale with it. |
| `world_position` | `Vector2` (a copy), assignable | The world position. Editing the copy does nothing — assign instead: `t.world_position = Vector2(0, 0)`. |
| `world_rotation`, `world_scale` | `float`, `Vector2` | World rotation and scale (read-only). |
| `world_x`, `world_y`, `get_world_xy()` | `float`, `float`, `tuple` | Fast reads of the world position with no copy. |
| `set_world_position(x, y)` | `x: float, y: float` | Sets the world position (recomputes the local one). |
| `translate(dx, dy)` | `dx: float, dy: float` | Moves in the parent's space. |
| `teleport(x, y)` | `x: float, y: float` | Moves without interpolation, so smoothing never "stretches" the jump. |
| `parent` | `Transform or None` | The parent (assigning calls `set_parent`). |
| `set_parent(parent, keep_world_position=False)` | `parent: Transform, GameObject or None, keep_world_position: bool` | Changes the parent. By default the local offset is kept; `keep_world_position=True` leaves the object where it is in the world. A cycle (a parent that's also a descendant) raises `ValueError`. |
| `detach(keep_world_position=True)` | `keep_world_position: bool` | Detaches from the parent. |
| `children`, `child_count`, `root`, `depth` | `tuple`, `int`, `Transform`, `int` | Navigating the hierarchy. |
| `transform_point(x, y)` / `inverse_transform_point(x, y)` | `x: float, y: float` | A point from local space to world space and back: `t.transform_point(30, 0)`. |
| `is_dirty`, `world_version` | `bool`, `int` | The world-value cache: is it stale, and how many times has it recomputed. |
| `interpolate` | `bool` | Enables smoothing between physics steps (`Rigidbody2D` turns it on by itself). |
| `get_render_xy(alpha)` / `render_position` | `alpha: float` | The position to draw at, with interpolation; `render_position` uses `Time.alpha`. |
| `reset_interpolation()` | — | "Previous position := current": the next frame is drawn exactly where the object stands. |

#### Usage Example

```python
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square
from engine.utils.vector2 import Vector2

scene = Scene("hierarchy")

player = create_square(200, 300, size=40, name="Player", add_rigidbody=True)
sword = create_rectangle(0, 0, 30, 8, color=(220, 220, 230), name="Sword", add_collider=False)

sword.set_parent(player)                  # the sword is a child of the player
sword.transform.position.x = 40           # 40 px to the player's right (local space)
sword.transform.rotation = -30            # rotation relative to the parent
scene.add_game_object(player)             # a child joins the scene along with its parent

print(sword.transform.get_world_xy())     # (240.0, 300.0): parent + offset
player.transform.position.x += 100        # the player moved — the sword follows
print(sword.transform.get_world_xy())     # (340.0, 300.0)

world = sword.transform.world_position    # a copy: editing it does nothing
sword.transform.world_position = Vector2(500, 100)   # this does work (world coordinates)

sword.set_parent(None, keep_world_position=True)     # detach without moving it in the world
player.transform.teleport(500, 100)       # move without smoothing
```

---

## 5. Physics System

PygamE's physics is `Rigidbody2D` (motion) + colliders (shape) + `PhysicsWorld` (the system every scene creates). Everything happens in `fixed_update`, at `Time.fixed_delta_time` intervals (1/60 s by default). One step's order: component `fixed_update` → refreshing colliders moved by scripts → simulating every body → finding contacts → callbacks (`exit`, then `enter`, then `stay`). The broad phase is a uniform grid (`SpatialHash`): static colliders register once, and only moving colliders trigger queries.

### 5.1. Rigidbody2D

**Description:** The component that moves an object: velocity, acceleration, gravity, drag, friction, and mass. Movement is resolved **one axis at a time with a swept scan (swept AABB)**: the body travels exactly up to the nearest obstacle and stops flush against it. That means no tunneling at any speed, no jitter on landing, and a stable `is_grounded` (resting on a surface is a zero-gap contact). A body that starts a step inside a solid (spawned there, or teleported) is pushed out along the axis of least penetration. Order within a step: forces, acceleration, and gravity → drag (`exp(-drag·dt)` on both axes) → ground friction (`friction · |gravity|` px/s² horizontally) → the fall-speed cap → depenetration → move on X → move on Y. Units are pixels and seconds.

> **Limitations.** Solid obstacles can only be `BoxCollider2D` (circles work only as triggers). Bodies treat each other as immovable walls (no impulse transfer). Kinematic platforms don't "carry" bodies standing on them. Put `Rigidbody2D` on root objects: on a child it works in the parent's local space (the engine logs a warning).

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Rigidbody2D(...)` | `gravity: float = 500, gravity_scale: float = 1.0, drag: float = 0.0, mass: float = 1.0, use_gravity: bool = True, is_kinematic: bool = False, terminal_velocity: float = 1000, friction: float = 0.0, acceleration: tuple or Vector2 = None, interpolate: bool = True` | Creates a body. `gravity` (px/s²) and `gravity_scale` control the fall; `drag` is air resistance (1/s); `friction` is the ground-friction coefficient; `mass` divides forces and impulses; `terminal_velocity` caps fall speed; `acceleration` is a constant acceleration (wind, thrust); `is_kinematic` means it only moves by `velocity`, doesn't resolve collisions, but still fires events; `interpolate` gives smooth rendering between steps. All parameters are also available as attributes. |
| `velocity` | `Vector2` | Velocity in px/s. Editable directly: `body.velocity.x = 200`. `velocity_x` / `velocity_y` are scalar aliases. |
| `acceleration` | `Vector2` | Constant acceleration in px/s². |
| `is_grounded` | `bool` | `True` if the body is resting on something below it (updated every step). |
| `collider` | `BoxCollider2D or None` | Found in `start()`; without one, gravity still applies but nothing collides (a warning is logged). |
| `add_impulse(impulse_x, impulse_y)` | `impulse_x: float, impulse_y: float` | An instant change in velocity: `Δv = impulse / mass`. A jump, a knockback: `body.add_impulse(0, -400)`. |
| `add_force(force_x, force_y, delta_time=None)` | `force_x: float, force_y: float, delta_time: float = None` | The force accumulates and is applied on the **next** physics step, then cleared — call it every `fixed_update` for a sustained push. With `delta_time`, the legacy behaviour applies: `v += F / m · dt` immediately. |
| `stop()` | — | Zeroes velocity and any accumulated forces. |
| `teleport(x, y)` | `x: float, y: float` | Moves to a world point without smoothing, and stops the body. |
| `on_spawn()` / `on_despawn()` | `**kwargs` / — | Hooks for `GameObjectPool`: the body stops itself when handed out from the pool and when returned to it. |

#### Usage Example

```python
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square

scene = Scene("physics")
scene.add_game_object(create_rectangle(0, 400, 800, 40, name="Floor", is_static=True))

# A crate with friction: it slides and comes to a stop
crate = create_square(100, 300, size=40, name="Crate", add_rigidbody=True)
crate_body = crate.get_component(Rigidbody2D)
crate_body.friction = 0.6        # decelerates by 0.6 · gravity px/s² while grounded
crate_body.mass = 2.0
scene.add_game_object(crate)

# A kinematic platform: driven by velocity, passes through everything, ignores gravity
platform = create_rectangle(300, 250, 120, 16, name="Platform", add_rigidbody=True)
platform_body = platform.get_component(Rigidbody2D)
platform_body.is_kinematic = True
platform_body.velocity.x = 60
scene.add_game_object(platform)

for _ in range(60):                        # one second of falling
    scene.tick(1 / 60)
assert crate_body.is_grounded              # resting on the floor

crate_body.add_impulse(400, 0)             # a push to the right: velocity += 400 / mass
for _ in range(120):
    scene.tick(1 / 60)
print(crate_body.velocity.x)               # 0.0 — friction brought the crate to a stop

crate_body.teleport(100, 100)              # move it back up without "smearing" across frames
```

### 5.2. Colliders (BoxCollider2D, CircleCollider2D)

**Description:** A collider defines an object's shape for collisions (solid) or for touch detection (a trigger, `is_trigger=True`). `BoxCollider2D` is a rectangle, the only shape `Rigidbody2D` resolves as solid. `CircleCollider2D` does an exact distance-to-center test (circle-circle and circle-box), but works **for overlap and triggers only** — there is no solid circle. Geometry is stored as exact floating-point values (`bounds`); `rect` is just a rounded `pygame.Rect` for drawing and legacy code. **Sizing:** it's best to pass `size=(w, h)` explicitly; otherwise it's measured once from the sprite in `start()` and then *locked* — changing an animation frame doesn't resize the hitbox (for a deliberate resize, like crouching, use `set_size`). **Anchor** (`anchor`) uses the same nine names as `SpriteRenderer`: give a sprite and its collider the same anchor to keep the hitbox lined up with the picture (see [9.1](#91-spriterenderer-and-sprite-anchors)).

**Events.** A solid touching a solid produces collision events if at least one side has a `Rigidbody2D`; anything crossing a trigger produces trigger events. There are two ways to receive them, both work at once and for either side:

- **Handler methods** on any component of either object: `on_collision_enter/stay/exit(self, collision)` and `on_trigger_enter/stay/exit(self, other)`;
- **Callback lists** on the collider: `collider.on_trigger_enter.append(fn)`, with signature `fn(my_collider, other_collider)`.

If an object is deactivated, removed, or destroyed while touching another, the other side receives `exit`. Exceptions inside handlers are logged, never raised; destroying objects from inside a handler is safe.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `BoxCollider2D(...)` | `size: tuple = None, offset_x: float = 0, offset_y: float = 0, anchor: str = "topleft", is_trigger: bool = False, layer: int or str = None, mask: int or a list of layers = None` | A rectangle. `size=None` measures from the sprite (once, in `start()`); `offset_x/offset_y` shift the hitbox; `layer=None` uses the object's layer; `mask=None` collides with every layer. |
| `CircleCollider2D(...)` | `radius: float = None, offset_x: float = 0, offset_y: float = 0, anchor: str = "topleft", is_trigger: bool = False, layer: int or str = None, mask: int or a list of layers = None` | A circle (overlap and triggers only). `radius=None` is half the sprite's longer side. The anchor applies to a `(diameter, diameter)` square. |
| `is_trigger` | `bool` | `True` makes it a sensor with no physical reaction: `collider.is_trigger = True`. |
| `layer`, `mask` | `int`, `int` | The collision layer and mask (see [5.3](#53-collision-layers-and-masks)). |
| `bounds` | `tuple` (property) | The exact world-space `(left, top, right, bottom)`. |
| `rect` | `pygame.Rect` (property) | A rounded bounding rectangle — for drawing and debugging, never for physics. |
| `is_static` | `bool` (property) | Whether the collider sits on a static object. |
| `overlaps(other)` | `other: Collider2D` | An exact shape-overlap test: `zone.overlaps(hero_collider)`. |
| `can_collide_with(other)` | `other: Collider2D` | Whether the pair interacts under the layer/mask rules (each mask must allow the other's layer). |
| `contact_normal(other)` | `other: Collider2D` | The unit normal `(nx, ny)` from `other` to this collider. |
| `overlapping_colliders` | `frozenset` (property) | What this collider was touching on the last physics step. |
| `on_trigger_enter/stay/exit` | `a list of fn(collider, other)` | Trigger callbacks: entering / staying (every step) / leaving. |
| `on_collision_enter/stay/exit` | `a list of fn(collider, other)` | Collision callbacks (needs a `Rigidbody2D` on at least one side). |
| `Collision2D` | `collider, other, normal, game_object` | The argument passed to `on_collision_*(collision)`: `collision.other` is the other collider, `collision.game_object` its object, and `collision.normal` the contact normal from the other object toward this one (`(0, −1)` means "I was supported from below"). |
| `BoxCollider2D.size` / `set_size(width, height)` | `width: float, height: float` | The current size / a deliberate resize that locks the new size in place. |
| `BoxCollider2D.snap_left_to(x)`, `snap_right_to(x)`, `snap_top_to(y)`, `snap_bottom_to(y)` | `x: float` / `y: float` | Shifts the `Transform` so that edge of the hitbox lands exactly at that world coordinate. |
| `CircleCollider2D.radius` / `set_radius(radius)` | `radius: float` | The radius (read-only) / a deliberate resize. `center_x`, `center_y` give the circle's world-space center. |
| `scene.physics.query_point(x, y, mask, include_triggers)` | `x: float, y: float, mask: int = CollisionLayers.ALL, include_triggers: bool = True` | Colliders at a point: `scene.physics.query_point(210, 360)`. |
| `scene.physics.query_rect(rect, ...)` / `query_bounds(left, top, right, bottom, ...)` | `rect: pygame.Rect` / `left, top, right, bottom: float` (plus the same `mask`, `include_triggers`) | Colliders overlapping an area. |

#### Usage Example

```python
from engine.components.circle_collider2d import CircleCollider2D
from engine.components.box_collider2d import BoxCollider2D
from engine.components.component import Component
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square


class DamageZone(Component):
    """Handler methods: on any component of either of the two objects."""

    def on_trigger_enter(self, other):                # other — the collider that entered
        print(f"{other.game_object.name} entered the zone")

    def on_trigger_exit(self, other):
        print(f"{other.game_object.name} left the zone")


class LandingLogger(Component):
    def on_collision_enter(self, collision):          # collision — a Collision2D
        if collision.normal.y < -0.5:                 # supported from below
            print("landed on", collision.game_object.name)


scene = Scene("colliders")
scene.add_game_object(create_rectangle(0, 400, 800, 40, name="Floor", is_static=True))

zone = GameObject(200, 340, name="Zone", is_static=True)
zone_collider = zone.add_component(BoxCollider2D(size=(120, 60), is_trigger=True))
zone.add_component(DamageZone())
# The other way: a callback list, signature (my_collider, other_collider)
zone_collider.on_trigger_enter.append(lambda me, other: print("callback list:", other.game_object.name))
scene.add_game_object(zone)

hero = create_square(240, 100, size=40, name="Hero", add_rigidbody=True)
hero.add_component(LandingLogger())
scene.add_game_object(hero)

sensor = GameObject(600, 300, name="Sensor", is_static=True)
sensor.add_component(CircleCollider2D(radius=80, is_trigger=True))   # a circular detection zone
scene.add_game_object(sensor)

for _ in range(120):                                  # the hero falls through the zone and lands
    scene.tick(1 / 60)

hero_box = hero.get_component(BoxCollider2D)
print(hero_box.bounds)                                # exact bounds (240, 360, 280, 400)
print(hero_box.overlaps(zone_collider))               # True: the hero is standing in the zone
print([c.game_object.name for c in scene.physics.query_point(250, 380)])   # Zone and Hero
```

### 5.3. Collision Layers and Masks

**Description:** Every collider has a **layer** (`layer`, a number 0–31 or a name — "what I am") and a **mask** (`mask`, a set of layers — "what I collide with"). Two colliders interact only if **each** mask allows the other's layer. Non-matching pairs are rejected before the exact overlap test even runs, which makes layer separation the cheapest way to speed up physics. By default every object sits on layer 0 (`"default"`) and collides with everything. A collider inherits `layer` from its object unless it has its own. Layers get names through `CollisionLayers.register`.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `CollisionLayers.register(name, index)` | `name: str, index: int` | Names a layer (0–31; case doesn't matter): `CollisionLayers.register("enemy", 2)`. |
| `CollisionLayers.index(layer)` | `layer: int or str` | Validates and resolves a name or number to a layer index; an unknown name raises `ValueError`. |
| `CollisionLayers.mask(*layers)` | `*layers: int or str` | A mask made of the given layers: `CollisionLayers.mask("ground", "enemy")`. |
| `CollisionLayers.name_of(index)` | `index: int` | The layer's name (or the number as a string, if it has none). |
| `CollisionLayers.reset()` | — | Resets the name registry (only `"default"` remains). |
| `CollisionLayers.ALL` / `NONE` / `MAX_LAYERS` | `int` | The "every layer" mask (`0xFFFFFFFF`) / "no layers" / the layer count (32). |
| `GameObject.layer` | `int or str` | The object's layer: `go.layer = "player"`. |
| `Collider2D.layer` / `Collider2D.mask` | `int` / `int` | A specific collider's layer and mask (`mask` can also be set in the constructor). |
| `Collider2D.can_collide_with(other)` | `other: Collider2D` | Checks a pair against the layer/mask rules. |
| `mask` in `scene.physics.query_*` calls | `int` | Restricts a query to the given layers. |

#### Usage Example

```python
from engine.components.box_collider2d import BoxCollider2D
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.physics.layers import CollisionLayers

CollisionLayers.register("player", 1)
CollisionLayers.register("enemy", 2)
CollisionLayers.register("bullet", 3)
CollisionLayers.register("ground", 4)

scene = Scene("layers")

# The player collides with the ground and enemies — but not its own bullets
player = GameObject(100, 100, name="Player", layer="player")
player_box = player.add_component(BoxCollider2D(
    size=(32, 48), mask=CollisionLayers.mask("ground", "enemy")))

# The player's bullet (a trigger): hits enemies and the ground, ignores the player and other bullets
bullet = GameObject(140, 110, name="Bullet", layer="bullet")
bullet_box = bullet.add_component(BoxCollider2D(
    size=(8, 8), is_trigger=True, mask=CollisionLayers.mask("enemy", "ground")))

enemy = GameObject(300, 100, name="Enemy", layer="enemy")
enemy_box = enemy.add_component(BoxCollider2D(size=(32, 32)))

for go in (player, bullet, enemy):
    scene.add_game_object(go)

print(player_box.can_collide_with(bullet_box))   # False — this pair doesn't interact
print(bullet_box.can_collide_with(enemy_box))    # True — "bullet" sees "enemy", and "enemy"'s default mask sees everyone

enemy.layer = "ground"                           # the layer can be changed on the fly
print(CollisionLayers.name_of(enemy.layer))      # ground
```

---

## 6. Input System

**Description:** `Input` is a static service, reachable from any component without a reference to `Engine`. Keys are given as strings (`"space"`, `"w"`, `"left_shift"`, `"mouse_left"`), `Key.*` constants, or raw `pygame.K_*` codes; a typo in a key name raises `ValueError` immediately rather than silently doing nothing. The system is event-driven: `Engine` feeds it every pygame event, so a press shorter than one frame is never lost, and losing window focus releases every held key. **Inside `fixed_update`, the "pressed"/"released" edges are read from a separate set that's consumed after each physics step** — so every press is seen by exactly one physics step, whether a frame runs two steps or none. For ordinary gameplay logic, reading input in `update()` is still preferable.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Input.is_key_down(key)` | `key: str, int, or Key` | `True` while the key is held: `Input.is_key_down("d")`. |
| `Input.is_key_pressed(key)` | `key: str, int, or Key` | `True` only on the frame (or physics step) the key went down. |
| `Input.is_key_up(key)` | `key: str, int, or Key` | `True` only on the frame it was released. |
| `Input.get_axis(negative, positive)` | `negative: str, positive: str` | `-1`, `0`, or `1` from a pair of keys: `Input.get_axis("a", "d")`. |
| `Input.mouse_position()` | — | `(x, y)` in screen pixels. |
| `Input.mouse_world_position()` | — | The cursor's position in world coordinates through the scene's active camera (or `None` if there is no scene). |
| `Input.mouse_delta()` | — | How far the mouse moved since the last frame `(dx, dy)`. |
| `Input.mouse_scroll()` / `mouse_scroll_x()` | — | This frame's wheel scroll (vertical / horizontal). |
| `Input.is_mouse_pressed(button=0)` / `is_mouse_just_pressed(button)` / `is_mouse_just_released(button)` | `button: int` (0 — left, 1 — middle, 2 — right) | The legacy numeric mouse-button API. |
| `Input.is_pressed(key)` / `is_just_pressed(key)` / `is_just_released(key)` | `key: str, int, or Key` | Legacy names: `is_pressed` = `is_key_down`, `is_just_pressed` = `is_key_pressed`, `is_just_released` = `is_key_up`. |
| `Key.*` | — | Named constants: `Key.W`, `Key.SPACE`, `Key.LEFT`, `Key.F1`, and so on — the same as the strings, with IDE autocomplete. |
| `Input.inject_key(key, down=True)` / `inject_mouse_position(x, y)` / `inject_scroll(y, x=0)` | — | Simulates input without real pygame events — handy for tests and bots. |

#### Usage Example

```python
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D
from engine.input.input_manager import Input
from engine.input.key import Key


class TopDownMover(Component):
    def __init__(self, speed=220):
        super().__init__()
        self.speed = speed

    def start(self):
        self.body = self.game_object.get_component(Rigidbody2D)

    def update(self, delta_time):
        x = Input.get_axis("a", "d")               # -1 / 0 / 1 from string key names
        y = Input.get_axis(Key.W, Key.S)            # the same, but through Key.*
        self.body.velocity.x = x * self.speed
        self.body.velocity.y = y * self.speed

        if Input.is_key_pressed("space"):           # only on the frame it was pressed
            print("jump!")

        if Input.is_mouse_just_pressed(0):           # left mouse button
            target = Input.mouse_world_position()
            print("clicked in world space:", target)
```

---

## 7. User Interface (UI) System

### 7.1. Canvas and Screen-Space UI

**Description:** UI elements (`UIText`, `UIButton`, `UIPanel`, `UIHealthBar`) are components on a `GameObject`, just like everything else. By default they're drawn in **screen coordinates** — after the world, on top of it, with no camera offset, so the HUD never "drifts" while the view scrolls. `Canvas` is an optional root element: it draws nothing itself, but `canvas.visible = False` hides every UI element attached to it as a parent. An element can also be made **world-space** (`world_space=True`) — then it's drawn together with the world through the camera (a health bar floating over an enemy, say): make the UI element's object a child of the one you want it to follow.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `UIElement(...)` | `width: int = 100, height: int = 30, visible: bool = True, draw_order: int = 0, anchor: str = None, pivot: str = None, world_space: bool = False` | The base class for every UI element; see the anchor parameters in [7.3](#73-ui-anchors-and-pivots). |
| `Canvas(...)` | `sort_order: int = 0, visible: bool = True` | A root UI container element; it isn't drawn itself. `visible = False` hides every child at once. |
| `visible` | `bool` | Whether the element is shown. |
| `is_visible` | `bool` (property) | Whether the element is shown, **accounting for** the visibility of every UI ancestor. |
| `draw_order` | `int` | Draw order among screen elements (lower draws earlier/behind); ties keep insertion order. |
| `world_space` | `bool` | `True` draws the element in the world through the camera, instead of in screen coordinates. |
| `rect` | `pygame.Rect` (property) | The element's current rectangle in screen coordinates (for a world-space element, camera-adjusted). |
| `contains_point(point_x, point_y)` | `point_x: float, point_y: float` | Whether a point falls inside the element's rectangle: `panel.contains_point(*Input.mouse_position())`. |
| `draw(screen)` | `screen: pygame.Surface` | The drawing hook — specific widgets override it. |

#### Usage Example

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.ui.canvas import Canvas
from engine.ui.ui_health_bar import UIHealthBar
from engine.ui.ui_text import UIText


class HUDScene(Scene):
    def start(self):
        super().start()
        hud = GameObject(name="HUD")
        self.canvas = hud.add_component(Canvas())      # one shared visibility switch
        self.add_game_object(hud)

        label = GameObject(12, 12, name="ScoreLabel", parent=hud)
        self.score_text = label.add_component(UIText("Score: 0", anchor="TopLeft"))

        bar = GameObject(12, 42, name="HealthBar", parent=hud)
        bar.add_component(UIHealthBar(220, 20, max_value=100, anchor="TopLeft"))

    def update(self, delta_time):
        super().update(delta_time)
        from engine.input.input_manager import Input
        if Input.is_key_pressed("h"):
            self.canvas.visible = not self.canvas.visible   # hide/show the whole HUD at once
```

### 7.2. UI Elements (UIText, UIButton, UIPanel, UIHealthBar)

**Description:** Four ready-made widgets. `UIText` draws a string (its rendered surface is cached, so redrawing unchanged text doesn't re-render it). `UIButton` is a rectangle with a label and a list of `on_click` callbacks, reacting to hover and left-click. `UIPanel` is a plain rectangular background, often used as a backdrop for other elements. `UIHealthBar` is a fillable bar (health, stamina, a progress meter) with optional smoothing and a "damage trail" (`trail_color`) that catches up to the current value. Colours and the font default to `UIStyle.default()`.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `UIText(...)` | `text: str = "", style: UIStyle = None, align: str = "left", width: int = None, height: int = None, **kwargs` | `**kwargs` are the common `UIElement` parameters (`anchor`, `pivot`, `world_space`, etc.). `align` is `"left"`, `"center"`, or `"right"`. Width/height default to the text's measured size. |
| `UIText.text` / `set_text(text)` | `text: str` | The current text / changing it: `label.set_text("Done")`. |
| `UIButton(...)` | `text: str = "Button", width: int = 140, height: int = 40, style: UIStyle = None, **kwargs` | A button with a label. |
| `UIButton.on_click` | `a list of fn(button)` | Click callbacks: `button.on_click.append(lambda b: print("clicked"))`. |
| `UIButton.is_hovered` / `is_pressed` | `bool` | Whether the mouse is over it / whether it's currently pressed. |
| `UIPanel(...)` | `width: int = 200, height: int = 100, style: UIStyle = None, **kwargs` | A rectangular backdrop. |
| `UIHealthBar(...)` | `width: int = 200, height: int = 20, max_value: float = 100.0, value: float = None, fill_color: tuple = (80,200,90), low_color: tuple = (215,65,65), low_threshold: float = 0.3, trail_color: tuple = None, smooth_speed: float = 0.0, show_text: bool = False, **kwargs` | `low_color` kicks in at `ratio <= low_threshold`; `smooth_speed > 0` glides the fill (fraction per second) instead of jumping instantly; `show_text` draws `"hp/max"` over the bar. |
| `UIHealthBar.value` / `set_value(v)` | `float` | The current value. |
| `UIHealthBar.set_max_value(max_value, keep_ratio=False)` | `max_value: float, keep_ratio: bool` | Changes the maximum; `keep_ratio=True` preserves the fill fraction. |
| `UIHealthBar.bind(getter)` | `getter: a callable with no arguments` | Reads the value from a function every frame: `bar.bind(lambda: player_health.hp)`. |
| `UIHealthBar.ratio` / `displayed_ratio` | `float` (properties) | The true fill fraction / the one actually drawn (with smoothing applied). |
| `UIStyle(...)` / `UIStyle.default()` | `background_color, border_color, border_width, text_color, font_name, font_size, hover_color, pressed_color` | The shared colour and font set for widgets; `default()` is the factory for the default style. |

#### Usage Example

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.ui.canvas import Canvas
from engine.ui.ui_button import UIButton
from engine.ui.ui_health_bar import UIHealthBar
from engine.ui.ui_panel import UIPanel
from engine.ui.ui_style import UIStyle
from engine.ui.ui_text import UIText


class PauseMenuScene(Scene):
    def start(self):
        super().start()
        hud = GameObject(name="PauseMenu")
        hud.add_component(Canvas())
        self.add_game_object(hud)

        panel = GameObject(0, 0, name="Panel", parent=hud)
        panel.add_component(UIPanel(320, 200, anchor="Center",
                                    style=UIStyle(background_color=(25, 25, 35, 220))))

        title = GameObject(0, -60, name="Title", parent=hud)
        title.add_component(UIText("Paused", anchor="Center", align="center"))

        health = GameObject(-140, -10, name="Health", parent=hud)
        bar = health.add_component(UIHealthBar(280, 24, max_value=100, value=65,
                                               anchor="Center", show_text=True,
                                               smooth_speed=2.0, trail_color=(220, 90, 90)))

        resume = GameObject(0, 40, name="Resume", parent=hud)
        button = resume.add_component(UIButton("Resume", 180, 44, anchor="Center"))
        button.on_click.append(lambda b: print("resuming the game"))

        bar.value = 40    # the bar will smoothly "catch up" to the new value via smooth_speed
```

### 7.3. UI Anchors and Pivots

**Description:** Nine named anchors — `TopLeft`, `TopCenter`, `TopRight`, `MiddleLeft`, `Center`, `MiddleRight`, `BottomLeft`, `BottomCenter`, `BottomRight` (case and underscores don't matter: `"top_left"`, `"topleft"`, `"MidTop"` are all understood). With no anchor (`anchor=None`, the default), a `GameObject`'s position is the element's top-left corner in screen pixels; with a UI-element parent, it's relative to that parent's rectangle. With an anchor, the object's position becomes an **offset from the anchor point** of the reference rectangle: the nearest UI ancestor, or the screen if there is none. `pivot` decides which point *of the element itself* sits on that anchor point (it defaults to the anchor), so `anchor="BottomRight"` with an offset of `(-10, -10)` gives a 10-pixel margin from the corner at any window size.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `UIElement(anchor=..., pivot=...)` | `anchor: str = None, pivot: str = None` | `anchor` is which point of the reference rectangle the element is pinned to; `pivot` is which point of the element sits there (defaults to `anchor`). |
| `UIElement.anchor` / `.pivot` | `str or None` | Can be changed after creation: `element.anchor = "BottomRight"`. |
| `normalize_anchor(name)` | `name: str` | Turns any spelling into the canonical name; an unknown one raises `ValueError`. |
| `VALID_ANCHORS` | `set[str]` | The nine canonical lowercase, space-free names: `{"topleft", "midtop", ...}`. |
| `anchor_to_topleft_offset(anchor, width, height)` | `anchor: str, width: float, height: float` | `(dx, dy)` from the anchor point to the top-left corner of a rectangle that size — the same math `SpriteRenderer` and the colliders use ([9.1](#91-spriterenderer-and-sprite-anchors)). |

#### Usage Example

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.ui.ui_button import UIButton
from engine.ui.ui_text import UIText

scene = Scene("anchors")

# Pinned to screen corners — independent of window size
top_left = GameObject(10, 10, name="TopLeft")
top_left.add_component(UIText("Top-left", anchor="TopLeft"))
scene.add_game_object(top_left)

bottom_right = GameObject(-10, -10, name="BottomRight")   # negative values = margin from the corner
bottom_right.add_component(UIText("Bottom-right", anchor="BottomRight", pivot="BottomRight"))
scene.add_game_object(bottom_right)

centered = GameObject(0, 0, name="CenterButton")
centered.add_component(UIButton("Centered", 160, 40, anchor="Center"))   # pivot defaults to anchor
scene.add_game_object(centered)

# Nesting: a child element anchors relative to its parent, not the screen
panel = GameObject(0, 0, name="Panel")
panel.add_component(UIButton("Placeholder", 300, 200, anchor="Center"))
scene.add_game_object(panel)

corner_label = GameObject(-8, -8, name="PanelCorner", parent=panel)
corner_label.add_component(UIText("v1.0", anchor="BottomRight", pivot="BottomRight"))
```

---

## 8. Particle System

**Description:** `ParticleSystem` is a lightweight emitter for dust, sparks, explosions, and trails. Particles are not `GameObject`s — they're compact structs recycled through an `ObjectPool` (see [10](#10-static-services-and-utilities)): once warmed up, continuous emission allocates no memory and creates no garbage for the collector. Particles don't take part in collisions. Colour, size, and fade are pure functions of a particle's age (0…1 from birth to death), so the system pre-renders a small set of ready-made surfaces once (`lut_steps` of them) and draws a particle by picking the right one plus one batched blit — never "particle by particle" drawing. `color_stops` gives a gradient across several colours; `world_space=True` (the default) leaves particles where they were emitted even if the emitter moves on (an explosion, a trail); `world_space=False` makes particles ride along with the emitter (a torch's flame).

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `ParticleSystem(...)` | `emission_rate: float = 0.0, lifetime: tuple = (0.5, 1.0), speed: tuple = (50.0, 100.0), direction: float = -90.0, spread: float = 360.0, gravity: float = 0.0, drag: float = 0.0, start_size: float = 6, end_size: float = None, start_color: tuple = (255,255,255), end_color: tuple = None, color_stops: list = None, start_alpha: int = 255, end_alpha: int = 0, shape: str = "circle", sprite: pygame.Surface = None, additive: bool = False, max_particles: int = 500, world_space: bool = True, z_index: int = 10, offset: tuple = (0.0, 0.0), spawn_radius: float = 0.0, duration: float = None, loop: bool = True, play_on_start: bool = True, lut_steps: int = 24, seed: int = None` | `direction`/`spread` are angles in degrees (0 = right, "−90" = up, clockwise); `additive=True` gives additive blending (fire, sparks); `shape` is `"circle"` or `"square"`, or pass `sprite` for a custom shape; `duration`/`loop` make emission finite or endless. |
| `play()` / `stop(clear=False)` | — / `clear: bool` | Start continuous emission (`emission_rate`) / stop it (`clear=True` also removes the live particles immediately). |
| `burst(count)` / `emit(count)` | `count: int` | Emit `count` particles at once (an explosion, a splash) — `emit` is an alias for `burst`. |
| `clear()` | — | Removes every current particle immediately. |
| `is_playing` | `bool` (property) | Whether continuous emission is running. |
| `particle_count` | `int` (property) | How many particles are alive right now. |
| `invalidate()` | — | Rebuild the colour/size/alpha lookup table after changing those parameters at runtime. |
| `pool` | `ObjectPool` (property) | The pool the particle structs are drawn from. |

#### Usage Example

```python
from engine.components.particle_system import ParticleSystem
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("particles")

# A one-off burst of sparks (additive blending, a yellow → orange → dark red gradient)
sparks_go = GameObject(400, 300, name="Sparks")
sparks = sparks_go.add_component(ParticleSystem(
    play_on_start=False, lifetime=(0.3, 0.6), speed=(120, 260), direction=-90, spread=180,
    gravity=500, start_size=8, end_size=1,
    color_stops=[(255, 246, 170), (255, 150, 40), (120, 40, 20)],
    additive=True, max_particles=200, seed=1,
))
scene.add_game_object(sparks_go)
sparks.burst(24)

# Continuous smoke from a torch: rides along with the object (world_space=False)
torch_go = GameObject(200, 250, name="TorchSmoke")
smoke = torch_go.add_component(ParticleSystem(
    emission_rate=15, lifetime=(0.8, 1.4), speed=(20, 40), direction=-90, spread=30,
    gravity=-40, start_size=4, end_size=14, color_stops=[(200, 200, 200), (90, 90, 90)],
    start_alpha=160, end_alpha=0, world_space=False, play_on_start=True,
))
scene.add_game_object(torch_go)

for _ in range(60):
    scene.tick(1 / 60)
print("live smoke particles:", smoke.particle_count)
```

---

## 9. Graphics, Animation, and Rendering

### 9.1. SpriteRenderer and Sprite Anchors

**Description:** `SpriteRenderer` draws a `pygame.Surface` at the object's world position, applying the `Transform`'s world rotation and scale. `anchor` uses the same nine names as the colliders (see [7.3](#73-ui-anchors-and-pivots) and [5.2](#52-colliders-boxcollider2d-circlecollider2d)): give a sprite and its collider the same anchor so the hitbox and the picture line up. `z_index` decides the layer order (lower is farther back/earlier); within the same `z_index`, objects sort by `world_y + offset_y`, giving a cheap depth trick for platformers and top-down views. A sprite is converted to the display format on first draw (`convert()`/`convert_alpha()`), and rotated/scaled variants come from a shared cache (see [10](#10-static-services-and-utilities)) — a static object is never recomputed every frame. Objects the camera can see are decided by bounds culling (see [9.4](#94-tilemap-optimization-baking)), so sprites off-screen aren't drawn at all.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `SpriteRenderer(...)` | `sprite: pygame.Surface = None, z_index: int = 0, offset_y: float = 0, anchor: str = "topleft", convert: bool = True` | `convert=False` disables auto-conversion to the display format (if the surface is already prepared by hand). |
| `sprite` / `set_sprite(sprite)` | `pygame.Surface` | The current sprite / replacing it (used by `Animator`, see [9.3](#93-animation-and-spritesheets-animator)). |
| `anchor` | `str` | One of the nine anchor names; an invalid value logs a warning and falls back to `"topleft"`. |
| `z_index` | `int` | The layer order. |
| `offset_y` | `float` | Only affects the depth sort key (`world_y + offset_y`), not the drawn position. |
| `is_visible` | `bool` (property) | Whether the sprite was drawn in the last couple of frames — used by `Animator` to skip off-screen animation. |
| `get_anchor_offset()` | — | `(dx, dy)` from the object's position to the sprite's original top-left corner, per the anchor. |
| `get_transformed_sprite(rotation, scale_x, scale_y)` | `rotation: float, scale_x: float, scale_y: float` | The rotated/scaled sprite from the shared cache. |
| `get_placement(world_x, world_y, rotation, scale_x, scale_y)` | — | The final surface and top-left corner for the blit, accounting for anchor, rotation, and scale — used internally by the render system. |

#### Usage Example

```python
import pygame

from engine.components.box_collider2d import BoxCollider2D
from engine.components.sprite_renderer import SpriteRenderer
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("sprites")

sprite = pygame.Surface((48, 64), pygame.SRCALPHA)
pygame.draw.rect(sprite, (90, 160, 230), sprite.get_rect(), border_radius=8)

enemy = GameObject(300, 200, name="Enemy")
# The same anchor on the sprite and the collider — they always line up visually
enemy.add_component(SpriteRenderer(sprite=sprite, anchor="center", z_index=1))
enemy.add_component(BoxCollider2D(size=sprite.get_size(), anchor="center"))
scene.add_game_object(enemy)

enemy.transform.rotation = 15      # drawn rotated around the sprite's center
enemy.transform.scale = 1.5        # drawn 1.5x larger
```

### 9.2. Camera

**Description:** `Camera` follows a `target` without touching its `Transform` — instead, the camera keeps its own world point, which the render pass subtracts from every sprite's position when drawing. This is what gives a jump its natural feel: the "view" moves, not the object itself. `smooth_follow=True` (the default) eases toward the target at a rate of `follow_speed` (exponential smoothing — independent of the frame rate and never overshoots the target); `smooth_follow=False` snaps the camera exactly onto the target every frame. The camera reads the target's **smoothed** (interpolated) position, so on high-refresh-rate monitors the camera and the target's sprite move in lockstep, with no lag between them. With no target (`target=None`), the world is drawn with no offset at all — as if there were no camera.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Camera(...)` | `target: GameObject = None, follow_speed: float = 5.0, smooth_follow: bool = True, position: Vector2 = None` | `follow_speed` — the higher it is, the "snappier" the follow; `position` sets a starting point (only matters until `start()` runs, which centers on the target immediately). |
| `target` | `GameObject or None` | The current follow target. |
| `set_target(target, snap=True)` | `target: GameObject, snap: bool` | Switches targets; `snap=True` jumps to it immediately, `False` eases in. |
| `snap_to_target()` | — | Instantly moves onto the target's current position (useful after a teleport or respawn). |
| `position` | `Vector2` | The current world point that will be centered on screen. |
| `get_offset(screen_width, screen_height)` | `screen_width: int, screen_height: int` | The world point that lands in the screen's top-left corner; `(0, 0)` if there's no target. |
| `get_view_bounds(screen_width, screen_height)` | `screen_width: int, screen_height: int` | `(left, top, right, bottom)` of the world area currently on screen. |
| `world_to_screen(world_pos, w, h)` / `screen_to_world(screen_pos, w, h)` | `Vector2, int, int` | Manual coordinate conversion (usually `Scene.world_to_screen`/`screen_to_world` is more convenient, see [4.2](#42-scene-management-scene-and-scenemanager)). |

#### Usage Example

```python
from engine.components.camera import Camera
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.primitives import create_square

scene = Scene("camera")
player = create_square(100, 100, size=40, name="Player", add_rigidbody=True)
scene.add_game_object(player)

camera_go = GameObject(name="MainCamera")
camera = camera_go.add_component(Camera(target=player, follow_speed=6, smooth_follow=True))
scene.add_game_object(camera_go)
scene.set_active_camera(camera)          # without this call, the world is drawn with no offset

player.transform.position.x += 500       # the player teleported far away
camera.snap_to_target()                  # the camera catches up instantly, no swoop

visible_left, visible_top, visible_right, visible_bottom = camera.get_view_bounds(1280, 720)
print(f"currently visible from x={visible_left:.0f} to x={visible_right:.0f}")
```

### 9.3. Animation and Spritesheets (Animator)

**Description:** `Animator` switches a `SpriteRenderer`'s frames over time. Playback is tied to real time (`dt * speed`), not the frame rate. `play(name)` is designed to be called safely **every single frame** with the "intended" animation: calling it again with the same name doesn't reset it to frame 0, and a non-looping (`loop=False`) animation that has played through stays on its last frame even if `play()` keeps being called. `force_restart=True` forces a restart from frame 0. If a looping animation hasn't been drawn in the last couple of frames (the object is off-screen), it simply **doesn't tick** — a hundred off-screen enemies cost nothing. Non-looping animations and ones with `on_finished` subscribers always tick, so gameplay logic ("the attack animation finished") still fires even off-screen. `load_spritesheet_animations()` builds a set of animations straight from a spritesheet plus a JSON atlas (the `"hash"` and `"array"` formats, as used by TexturePacker), sorting frames by the numeric index in the filename rather than alphabetically (otherwise `"walk_10"` would sort before `"walk_2"`).

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Animator(...)` | `animations: dict = None, default_animation: str = None, frame_duration: float = 0.1, speed: float = 1.0, cull_offscreen: bool = True` | `animations` is a dict `{"name": [surface, surface, ...]}`. |
| `play(anim_name=None, loop=True, reverse=False, force_restart=False)` | `anim_name: str, loop: bool, reverse: bool, force_restart: bool` | Safe to call every frame — see the description above. |
| `pause()` / `stop()` | — | Stop on the current frame / stop and reset to the first frame. |
| `has_animation(anim_name)` | `anim_name: str` | Whether that animation exists in the dictionary — useful for falling back to a default. |
| `set_animations(animations)` | `animations: dict` | Replaces the whole animation set (frames are converted once). |
| `is_playing`, `current_animation`, `frame_index` | `bool`, `str`, `int` | The player's current state. |
| `on_finished` | `a list of fn(animator, anim_name)` | Fires once, when a non-looping animation reaches its last frame. |
| `load_spritesheet_animations(json_path, image_path, generate_flipped=True)` | `json_path: str, image_path: str, generate_flipped: bool` | Returns `{name: [surface, ...]}` for `Animator`. `generate_flipped=True` also creates a mirrored version of every animation with an `_` prefix (e.g. `"idle"` → `"_idle"`). |

#### Usage Example

```python
import pygame

from engine.components.animator import Animator
from engine.components.sprite_renderer import SpriteRenderer
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.utils.spritesheet_loader import load_spritesheet_animations


def make_frame(color):
    surface = pygame.Surface((32, 32), pygame.SRCALPHA)
    pygame.draw.rect(surface, color, surface.get_rect())
    return surface


scene = Scene("animation")
hero = GameObject(150, 150, name="Hero")
hero.add_component(SpriteRenderer(sprite=make_frame((90, 160, 230))))

# Option 1: an animation built from ready-made frames (Surfaces) by hand
idle_frames = [make_frame((90, 160, 230)), make_frame((100, 170, 240))]
animator = hero.add_component(Animator({"idle": idle_frames}, default_animation="idle",
                                       frame_duration=0.2))
scene.add_game_object(hero)

animator.play("idle")            # safe to call this every frame in update()

# Option 2: an animation built from a spritesheet + JSON atlas (given assets/hero.png/.json)
# animations = load_spritesheet_animations("assets/hero.json", "assets/hero.png")
# hero.get_component(Animator).set_animations(animations)
```

### 9.4. Tilemap Optimization (Baking)

**Description:** Drawing thousands of static tiles is thousands of `blit()` calls every frame, forever. Baking draws them **once**, at level load, onto a large surface (or several "chunk" surfaces, for a huge map); every frame after that costs one blit per visible chunk — usually one to four. `bake_tilemap()` builds a static `GameObject` straight from a grid of tile IDs and a `{id: surface}` dictionary. `bake_static_sprites()` bakes the static, non-animated `SpriteRenderer`s **already added** to the scene, and disables the original components (colliders and gameplay scripts on the same objects keep working as usual). Translucent sprites are baked in premultiplied-alpha space, so overlapping translucency matches pixel-for-pixel drawing to within rounding. Baked pixels are "frozen" (they never move or animate) and share a single layer at their `z_index`.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `bake_tilemap(grid, tileset, tile_size, origin=(0,0), z_index=-100, chunk_size=None, opaque=False, background=(0,0,0), name="BakedTilemap")` | `grid: list[list[int]], tileset: dict or list, tile_size: int or tuple, origin: tuple, z_index: int, chunk_size: int, opaque: bool, name: str` | Builds a static `GameObject` with a baked layer from a grid of tile IDs (`None`/`-1` is an empty cell). Returns the object — add it to the scene yourself. |
| `bake_static_sprites(scene, chunk_size=None, z_range=None, opaque=False, name_prefix="Baked")` | `scene: Scene, chunk_size: int, z_range: tuple, opaque: bool` | Bakes every eligible static sprite already in the scene, one layer per `z_index`. Returns the list of new layer objects. |
| `BakedLayer(z_index=-100, chunk_size=None, opaque=False, background=(0,0,0))` | — | The baked-layer component (usually created through the functions above, not directly). |
| `BakedLayer.bake(items)` | `items: a list of (surface, x, y)` | Bakes an arbitrary set of images at given world coordinates. |
| `BakedLayer.chunk_count` | `int` (property) | How many chunk surfaces were actually created (only where something is drawn). |
| `BakedLayer.premultiplied_supported()` | — (static method) | Whether exact translucency blending is available on this pygame build. |

#### Usage Example

```python
import pygame

from engine.core.scene import Scene
from engine.primitives import create_square
from engine.rendering.tilemap import BakedLayer, bake_static_sprites, bake_tilemap


def tile(color):
    surface = pygame.Surface((32, 32))
    surface.fill(color)
    return surface


scene = Scene("tilemap")

# Option 1: directly from a grid of tile IDs
grid = [
    [1, 1, 1, 1, 1],
    [1, None, None, None, 1],   # None is an empty cell (-1 also works; NOT 0 — 0 is an ordinary id)
    [1, 1, 1, 1, 1],
]
tileset = {1: tile((110, 80, 50))}
ground = bake_tilemap(grid, tileset, tile_size=32, origin=(0, 300), z_index=-50)
scene.add_game_object(ground)
print("tiles baked:", ground.get_component(BakedLayer).item_count)

# Option 2: bake what's already sitting in the scene as ordinary static sprites
for i in range(200):
    deco = create_square(i * 34, 500, size=30, color=(70, 130, 70), name=f"Grass{i}",
                         add_collider=False, is_static=True)
    scene.add_game_object(deco)

layers = bake_static_sprites(scene)      # hundreds of grass blits -> a handful of chunk blits
print("baked layers created:", len(layers))
```

---

## 10. Static Services and Utilities

Every service in this section is reachable from anywhere in your code — just import the class, no reference to `Engine` or `Scene` needed.

### Time

**Description:** The engine's global clock. `fixed_delta_time` is the length of one physics step (1/60 s by default, changed through `Engine(fixed_fps=...)` or `Time.set_fixed_rate(hz)`); `alpha` is the fraction (0…1) of progress between the last two physics steps, used by render interpolation (see [4.4](#44-the-transform-hierarchy)); `time_scale = 0` pauses the game (gravity and gameplay both stop).

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Time.delta_time` / `unscaled_delta_time` | `float` | The variable frame step, scaled by `time_scale` and unscaled. |
| `Time.fixed_delta_time` | `float` | The length of one physics step. |
| `Time.time` / `unscaled_time` / `fixed_time` | `float` | Accumulated game time. |
| `Time.time_scale` | `float` | A multiplier on the whole game's speed; `0` pauses it. |
| `Time.alpha` | `float` | 0…1 between physics steps — for interpolation. |
| `Time.frame_count` / `fixed_frame_count` | `int` | Frame and physics-step counters. |
| `Time.set_fixed_rate(hz)` | `hz: float` | Changes the physics rate: `Time.set_fixed_rate(120)`. |
| `Time.reset()` | — | Resets every value to its default (used in tests). |

#### Usage Example

```python
from engine.core.game_time import Time

Time.time_scale = 0.0     # pause: physics and update() keep being called, but dt = 0
Time.time_scale = 0.5     # half speed
print(f"frame #{Time.frame_count}, physics step {Time.fixed_delta_time * 1000:.2f} ms")
```

### EventBus

**Description:** A global publish/subscribe bus, plus a separate bus on every `GameObject` (`go.events`) — an object's own events never reach global subscribers, and vice versa. `owner=` ties a subscription to an owner (`Scene`, `GameObject`): when it's destroyed, `Scene.destroy()`/`GameObject.destroy()` automatically drop every one of its subscriptions, removing the need to unsubscribe by hand and preventing leaks. An exception inside a handler is logged through `Debug`, and the remaining handlers still run.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `EventBus.subscribe(event, callback, owner=None, once=False, priority=0, weak=False)` | `event: str, callback: callable, owner: any object, once: bool, priority: int, weak: bool` | Subscribes to a global event; `weak=True` holds the callback by a weak reference (a destroyed listener unsubscribes itself). |
| `EventBus.emit(event, *args, **kwargs)` | `event: str, *args, **kwargs` | Notifies subscribers: `EventBus.emit("game_over", score=120)`. |
| `EventBus.unsubscribe(event, callback)` / `unsubscribe_owner(owner)` | — | Unsubscribes one callback / every subscription belonging to a given owner, at once. |
| `EventBus.once(event, callback, **kwargs)` | — | Fires once, then unsubscribes itself. |
| `EventBus.has_listeners(event)` / `listener_count(event=None)` | — | Whether there are any subscribers / how many. |
| `go.events` | `EventDispatcher` | An object's private bus: `player.events.subscribe("jumped", hud.on_jump)`. |

#### Usage Example

```python
from engine.core.event_bus import EventBus
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("events")
EventBus.subscribe("coin_collected", lambda amount: print(f"+{amount} points"), owner=scene)

player = GameObject(name="Player")
scene.add_game_object(player)
player.events.subscribe("jumped", lambda height: print(f"jumped {height} px"))

EventBus.emit("coin_collected", amount=10)      # the global subscriber hears this
player.events.emit("jumped", height=64)         # only this object's subscriber hears it

scene.destroy()          # scene's subscription to "coin_collected" is dropped automatically
```

### ObjectPool and GameObjectPool

**Description:** Reusing objects instead of constantly creating and discarding them — this avoids garbage-collector stutter from frequent spawning (bullets, particles, floating text). `ObjectPool` is a generic pool for any factory-built object; `GameObjectPool` specializes it for `GameObject`s inside a particular `Scene`: idle objects stay in the scene but disabled (`active=False`), so spawning is just flipping a flag, with no change to the scene's own lists. Components can implement `on_spawn(**kwargs)` / `on_despawn()` to reset their own state (`Rigidbody2D` stops itself automatically).

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `ObjectPool(factory, on_spawn=None, on_despawn=None, initial_size=0, max_size=None, name="ObjectPool")` | `factory: a callable with no arguments` | A generic pool. `initial_size` is how many to create up front ("warming up"). |
| `GameObjectPool(scene, factory, initial_size=0, max_size=None, name="GameObjectPool", clear_events_on_despawn=False)` | `scene: Scene, factory: a callable returning a ready-made GameObject` | A pool of objects for one scene. |
| `spawn(*args, **kwargs)` (`ObjectPool`) / `spawn(x=None, y=None, **kwargs)` (`GameObjectPool`) | — | Hands out an object from the pool (or creates a new one, if none are free); `None` if `max_size` is reached. `**kwargs` are passed to components' `on_spawn`. |
| `despawn(obj)` | `obj` | Returns an object to the pool. For a `GameObject`, `go.despawn()` does the same. |
| `despawn_all()` | — | Returns every currently active object to the pool. |
| `prewarm(count)` | `count: int` | Creates `count` objects up front, without activating them. |
| `active_count` / `free_count` | `int` (properties) | How many objects are currently handed out / free in the pool. |

#### Usage Example

```python
from engine.components.box_collider2d import BoxCollider2D
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.game_object import GameObject
from engine.core.object_pool import GameObjectPool
from engine.core.scene import Scene

scene = Scene("pooling")


def make_bullet():
    go = GameObject(name="Bullet")
    go.add_component(BoxCollider2D(size=(6, 6), is_trigger=True))
    go.add_component(Rigidbody2D(use_gravity=False, is_kinematic=True))
    return go


bullets = GameObjectPool(scene, make_bullet, initial_size=16, max_size=64)

bullet = bullets.spawn(x=100, y=200)             # reuses a free pool object
if bullet is not None:
    bullet.get_component(Rigidbody2D).velocity.x = 500

for _ in range(90):
    scene.tick(1 / 60)

bullet.despawn()                                  # return it to the pool, not destroy()
print("free in the pool:", bullets.free_count, "/ handed out:", bullets.active_count)
```

### PlayerPrefs

**Description:** A Unity-style settings and save-data store, backed by a single JSON file (`playerprefs.json` in the working directory by default). Values are typed: calling `get_int` on a key that actually holds a string returns the default, not an error. `save()` writes atomically (through a temp file), so a crash mid-write can never leave a corrupted file; if an existing file still fails to parse, it's renamed to `*.corrupt`, the error is logged, and the game carries on with an empty store. `Engine` saves any unsaved changes on exit automatically.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `PlayerPrefs.set_path(path)` / `get_path()` | `path: str` | Use a different file (discards unsaved changes). |
| `set_int(key, value)` / `get_int(key, default=0)` | `key: str, value: int, default: int` | Integers: `PlayerPrefs.set_int("high_score", 4200)`. |
| `set_float(key, value)` / `get_float(key, default=0.0)` | `key: str, value: float, default: float` | Floating-point numbers. |
| `set_string(key, value)` / `get_string(key, default="")` | `key: str, value: str, default: str` | Strings. |
| `has_key(key)` / `delete_key(key)` / `delete_all()` | `key: str` | Check whether a key exists / delete one value / clear the whole store. |
| `save()` | — | Writes to disk atomically. Nothing hits the disk until this is called. |
| `reload()` | — | Discards unsaved changes and re-reads the file. |
| `is_dirty()` | — | Whether there are unsaved changes. |

#### Usage Example

```python
from engine.core.player_prefs import PlayerPrefs

PlayerPrefs.set_path("saves/profile.json")

PlayerPrefs.set_int("high_score", 4200)
PlayerPrefs.set_string("player_name", "Georgii")
PlayerPrefs.set_float("music_volume", 0.6)
PlayerPrefs.save()                              # nothing is written to disk before this line

print(PlayerPrefs.get_int("high_score"))        # 4200
print(PlayerPrefs.get_int("no_such_key", 0))    # 0 — the default value
```

### AudioManager and AudioSource

**Description:** `AudioManager` handles music, sound effects, volume, and positional audio; two channels are reserved for music ("two decks"), so a crossfade genuinely overlaps the tracks and a sound effect can never steal the music channel. Fades run inside `update(dt)` and never block. Effective volume = master × (sfx or music) × the source's own volume × distance attenuation, recomputed every frame — so moving a slider immediately affects sounds already playing. Positional sounds (`position=(x, y)`) fade linearly between `min_distance` and `max_distance` around the listener (the active camera, by default) and pan by horizontal offset. `AudioSource` is the component for sound attached to an object (`spatial=True` makes it follow the object). With no audio device, everything just logs and doesn't stop the game from running.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `AudioManager.play_music(path, loop=True, fade_in=0.0, volume=1.0)` | `path: str` | Starts a track, cutting off the previous one (with a fade-in if `fade_in` is set). |
| `AudioManager.crossfade_to(path, duration=2.0, loop=True, volume=1.0)` | `path: str, duration: float` | Smoothly switches tracks, with both playing at once during the transition. |
| `AudioManager.stop_music(fade_out=0.0)` / `pause_music()` / `resume_music()` | — | Stop (with a fade-out) / pause / resume the music. |
| `AudioManager.play_sfx(sound, volume=1.0, loop=False, position=None, min_distance=100.0, max_distance=800.0, rolloff="linear")` | `sound: str or pygame.mixer.Sound, position: tuple` | A one-shot or looping sound effect; `position` enables distance attenuation and panning. |
| `AudioManager.set_master_volume(v)` / `set_sfx_volume(v)` / `set_music_volume(v)` | `v: float, 0..1` | Three independent volume sliders. |
| `AudioManager.mute()` / `unmute()` / `toggle_mute()` / `is_muted()` | — | Global mute. |
| `AudioManager.load_sound(path, cache=True)` | `path: str` | Preloads and caches a sound ahead of time, to avoid a pause on first playback. |
| `AudioManager.save_settings(prefix="audio.")` / `load_settings(prefix="audio.")` | `prefix: str` | Saves/loads the three volume sliders through `PlayerPrefs`. |
| `AudioSource(path=None, volume=1.0, loop=False, play_on_start=False, spatial=False, min_distance=100.0, max_distance=800.0)` | — | A component wrapper around `AudioManager` for a specific object. |
| `AudioSource.play()` / `stop()` / `pause()` / `resume()` | — | Playback control. |
| `AudioSource.load(path)` / `set_volume(v)` | `path: str` / `v: float` | Change the sound / the volume. |

#### Usage Example

```python
from engine.audio.audio_manager import AudioManager
from engine.components.audio_source import AudioSource
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("audio")

AudioManager.play_music("assets/theme.ogg", fade_in=1.5, volume=0.5)
AudioManager.set_sfx_volume(0.8)

torch = GameObject(400, 300, name="Torch")
source = torch.add_component(AudioSource("assets/fire_loop.ogg", loop=True,
                                         play_on_start=True, spatial=True, max_distance=500))
scene.add_game_object(torch)

AudioManager.play_sfx("assets/coin.wav", volume=0.7, position=(420, 280))   # a one-shot positional sound
AudioManager.crossfade_to("assets/battle.ogg", duration=2.0)                # a smooth track switch
```

### Debug

**Description:** A single point for logging and debug overlays. `Debug` is an alias for `DebugManager` (`Debug.log(...)`, in the style of Unity's `Debug.Log`). The built-in overlays are toggled with function keys (remappable through `debug.keys`): **F1** — stats (FPS, frame time, entity count, draw calls, physics counters), **F2** — collider outlines and velocity vectors, **F3** — a world coordinate grid, **F4** — a scrollable console of recent log entries. `Engine(debug=False)` disables every hotkey and overlay at once — for a release build.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Debug.log(message, source=None)` | `message: any, source: str` | An ordinary log entry: `Debug.log("Level loaded")`. |
| `Debug.log_warning(message, source=None)` / `log_error(message, source=None)` | — | A warning / an error (different colours in the F4 console). |
| `Debug.log_exception(exc, source=None)` | `exc: Exception` | Logs an exception as an error. |
| `Debug.clear_logs()` | — | Clears the log history. |
| `debug.set_stat(name, value)` | `name: str, value: any or None` | Adds your own line to the F1 overlay (`None` removes it). |
| `debug.toggle_overlay()` / `toggle_colliders()` / `toggle_grid()` / `toggle_console()` | — | Programmatically toggles any of the four overlays. |
| `debug.keys` | `dict` | Remaps hotkeys: `debug.keys["console"] = "grave"`. |

#### Usage Example

```python
from engine.core.debug_manager import Debug

Debug.log("Game started")
Debug.log_warning("Texture not found, using a placeholder")
try:
    1 / 0
except ZeroDivisionError as exc:
    Debug.log_exception(exc, source="Startup")
```

### Vector2 and Helper Utilities

**Description:** `Vector2` is a minimal 2D vector, used everywhere you'd otherwise have to carry an `x`/`y` pair around (position, velocity, a camera offset). `engine.primitives` provides quick factories for ready-made `GameObject`s (rectangle, square, circle, triangle, line) with a sprite and, optionally, a collider and a `Rigidbody2D` — handy for prototyping without preparing your own images.

#### API and Methods

| Method / Property | Signature / Parameters | Description and Usage |
| :--- | :--- | :--- |
| `Vector2(x=0.0, y=0.0)` | `x: float, y: float` | Supports `+`, `-`, unary `-`, `*`/`/` by a number, `+=`, `-=`, `==`. |
| `copy()` | — | An independent copy. |
| `length()` | — | The vector's length (`math.hypot`). |
| `normalized()` | — | A vector of the same direction, length 1 (a zero vector stays `(0, 0)`, no division by zero). |
| `lerp(other, t)` | `other: Vector2, t: float` | Linear interpolation; `t` is clamped to `[0, 1]`. |
| `as_tuple()` / `as_int_tuple()` | — | A plain `(x, y)`, or rounded to integers. |
| `Vector2.zero()` / `Vector2.one()` | — (static) | Quick `(0, 0)` and `(1, 1)`. |
| `create_rectangle(x=0, y=0, width=50, height=50, color=(200,200,200), name="Rectangle", add_collider=True, add_rigidbody=False, border_radius=0, is_static=False, layer=0)` | — | A ready-made rectangular `GameObject`. |
| `create_square(x=0, y=0, size=50, ..., is_static=False, layer=0)` | — | The same for a square (side length `size`). |
| `create_circle(x=0, y=0, radius=25, ..., precise_collider=False, is_static=False, layer=0)` | — | A circle; `precise_collider=True` gives it a `CircleCollider2D` instead of a square-approximation hitbox. |
| `create_triangle(x=0, y=0, size=50, ..., is_static=False, layer=0)` / `create_line(x=0, y=0, length=100, thickness=4, ..., vertical=False, is_static=False, layer=0)` | — | A triangle inscribed in a `size×size` square, and a line segment (horizontal or vertical). |

#### Usage Example

```python
from engine.core.scene import Scene
from engine.primitives import create_circle, create_rectangle
from engine.utils.vector2 import Vector2

start = Vector2(0, 0)
end = Vector2(300, 150)
midpoint = start.lerp(end, 0.5)          # Vector2(150.0, 75.0)
direction = (end - start).normalized()

scene = Scene("primitives")
platform = create_rectangle(0, 400, 300, 30, color=(90, 70, 50), is_static=True)
ball = create_circle(150, 100, radius=20, color=(230, 90, 90), add_rigidbody=True)
scene.add_game_object(platform)
scene.add_game_object(ball)
```
