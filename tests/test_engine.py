"""Headless test suite for the engine overhaul. Runs with either runner:

    python -m unittest discover tests        (no extra dependencies)
    python -m pytest tests

Uses SDL's dummy video/audio drivers, so no window or sound device is needed.
Organised by feature area; the `TestRegressions` class pins down bugs that
existed before the overhaul.
"""
import math
import os
import random
import struct
import sys
import tempfile
import unittest
import wave

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

pygame.init()
DISPLAY = pygame.display.set_mode((640, 480))

from engine.audio.audio_manager import AudioManager  # noqa: E402
from engine.components.animator import Animator  # noqa: E402
from engine.components.box_collider2d import BoxCollider2D  # noqa: E402
from engine.components.camera import Camera  # noqa: E402
from engine.components.circle_collider2d import CircleCollider2D  # noqa: E402
from engine.components.collider2d import Collider2D  # noqa: E402
from engine.components.component import Component  # noqa: E402
from engine.components.particle_system import ParticleSystem  # noqa: E402
from engine.components.player_controller import PlayerController  # noqa: E402
from engine.components.rigidbody2d import Rigidbody2D  # noqa: E402
from engine.components.sprite_renderer import SpriteRenderer  # noqa: E402
from engine.components.audio_source import AudioSource  # noqa: E402
from engine.core.debug_manager import Debug, DebugManager  # noqa: E402
from engine.core.event_bus import EventBus, EventDispatcher  # noqa: E402
from engine.core.game_object import GameObject  # noqa: E402
from engine.core.game_time import Time  # noqa: E402
from engine.core.object_pool import GameObjectPool, ObjectPool  # noqa: E402
from engine.core.player_prefs import PlayerPrefs  # noqa: E402
from engine.core.scene import Scene  # noqa: E402
from engine.core.scene_manager import SceneManager  # noqa: E402
from engine.core.spatial_hash import SpatialHash  # noqa: E402
from engine.input.input_manager import Input  # noqa: E402
from engine.input.key import Key, normalize_key  # noqa: E402
from engine.physics.layers import CollisionLayers  # noqa: E402
from engine.rendering.surface_cache import SurfaceCache, prepare_surface, sprite_cache  # noqa: E402
from engine.rendering.tilemap import BakedLayer, bake_static_sprites, bake_tilemap  # noqa: E402
from engine.ui.canvas import Canvas  # noqa: E402
from engine.ui.ui_button import UIButton  # noqa: E402
from engine.ui.ui_health_bar import UIHealthBar  # noqa: E402
from engine.ui.ui_panel import UIPanel  # noqa: E402
from engine.ui.ui_text import UIText  # noqa: E402
from engine.utils.fonts import render_text  # noqa: E402
from engine.utils.vector2 import Vector2  # noqa: E402

DT = 1.0 / 60.0


# -- helpers ---------------------------------------------------------------------------------

def make_surface(w, h, color=(255, 0, 0)):
    surface = pygame.Surface((w, h))
    surface.fill(color)
    return surface


def add_box(scene, x, y, w=32, h=32, name="box", static=False, body=False, color=(200, 60, 60),
            sprite=True, trigger=False, layer=0, mask=None, **rb_kwargs):
    go = GameObject(x, y, name=name, layer=layer)
    if sprite:
        go.add_component(SpriteRenderer(sprite=make_surface(w, h, color)))
    go.add_component(BoxCollider2D(size=(w, h), is_trigger=trigger, mask=mask))
    if body:
        go.add_component(Rigidbody2D(**rb_kwargs))
    if static:
        go.is_static = True
    scene.add_game_object(go)
    return go


def run(scene, seconds=1.0, fps=60):
    dt = 1.0 / fps
    for _ in range(round(seconds * fps)):
        scene.tick(dt)


def fixed_steps(scene, count):
    for _ in range(count):
        scene.fixed_update(Time.fixed_delta_time)


class Recorder(Component):
    """Counts hook calls and records physics events (both hook styles)."""

    def __init__(self):
        super().__init__()
        self.updates = 0
        self.fixed = 0
        self.log = []

    def update(self, dt):
        self.updates += 1

    def fixed_update(self, dt):
        self.fixed += 1

    def on_collision_enter(self, c):
        self.log.append(("col_enter", c.game_object.name))

    def on_collision_stay(self, c):
        self.log.append(("col_stay", c.game_object.name))

    def on_collision_exit(self, c):
        self.log.append(("col_exit", c.game_object.name))

    def on_trigger_enter(self, other):
        self.log.append(("trig_enter", other.game_object.name))

    def on_trigger_stay(self, other):
        self.log.append(("trig_stay", other.game_object.name))

    def on_trigger_exit(self, other):
        self.log.append(("trig_exit", other.game_object.name))

    def kinds(self):
        return [k for k, _ in self.log]


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        Time.reset()
        SceneManager.reset()
        CollisionLayers.reset()
        EventBus.clear()
        Input.instance().reset()
        sprite_cache.clear()
        self.debug = DebugManager(print_to_console=False)
        AudioManager.shutdown()

    def tearDown(self):
        SceneManager.reset()
        Time.reset()
        AudioManager.shutdown()

    def messages(self, level=None):
        return [e.message for e in self.debug.logs if level is None or e.level == level]


# ==========================================================================================
# 1. Scene management
# ==========================================================================================

LIFECYCLE = []


class SceneA(Scene):
    def start(self):
        LIFECYCLE.append("A.start")
        super().start()

    def destroy(self):
        LIFECYCLE.append("A.destroy")
        super().destroy()


class SceneB(Scene):
    def __init__(self, difficulty=1):
        super().__init__("B")
        self.difficulty = difficulty

    def start(self):
        LIFECYCLE.append("B.start")
        super().start()

    def destroy(self):
        LIFECYCLE.append("B.destroy")
        super().destroy()


class Destroyable(Component):
    destroyed = 0

    def on_destroy(self):
        Destroyable.destroyed += 1


class ChangeSceneOnUpdate(Component):
    def update(self, dt):
        SceneManager.change_scene(SceneB, difficulty=3)
        self.seen_active = SceneManager.active_scene


class TestSceneManager(EngineTestCase):
    def setUp(self):
        super().setUp()
        LIFECYCLE.clear()
        Destroyable.destroyed = 0

    def test_change_scene_runs_start_then_destroy_in_order(self):
        SceneManager.change_scene(SceneA)
        self.assertEqual(LIFECYCLE, ["A.start"])
        self.assertIsInstance(SceneManager.active_scene, SceneA)
        SceneManager.change_scene(SceneB)
        self.assertEqual(LIFECYCLE, ["A.start", "A.destroy", "B.start"])
        self.assertIsInstance(SceneManager.active_scene, SceneB)

    def test_constructor_arguments_reach_the_new_scene(self):
        scene = SceneManager.change_scene(SceneB, difficulty=7)
        self.assertEqual(scene.difficulty, 7)

    def test_change_during_update_is_deferred_to_end_of_frame(self):
        scene = SceneA()
        go = GameObject(name="changer")
        watcher = go.add_component(ChangeSceneOnUpdate())
        go.add_component(Destroyable())
        scene.add_game_object(go)
        SceneManager.change_scene(scene)

        SceneManager.update(DT)                      # the component requests B mid-frame
        self.assertIs(watcher.seen_active, scene)    # ...A was still active while it ran
        self.assertIsInstance(SceneManager.active_scene, SceneB)
        self.assertEqual(SceneManager.active_scene.difficulty, 3)
        self.assertEqual(Destroyable.destroyed, 1)   # old scene's objects got on_destroy
        self.assertTrue(scene.is_destroyed)

    def test_destroy_tears_everything_down(self):
        scene = Scene("s")
        owner_hits = []
        EventBus.subscribe("x", lambda: owner_hits.append(1), owner=scene)
        floor = add_box(scene, 0, 100, static=True)
        body = add_box(scene, 0, 0, body=True)
        body.add_component(Destroyable())
        SceneManager.change_scene(scene)
        scene.destroy()
        self.assertEqual(scene.game_objects, [])
        self.assertEqual(len(scene.physics.colliders), 0)
        self.assertEqual(len(scene.spatial_hash), 0)
        self.assertEqual(Destroyable.destroyed, 1)
        self.assertIsNone(floor.scene)
        EventBus.emit("x")
        self.assertEqual(owner_hits, [])             # owner-tagged subscription was dropped

    def test_legacy_named_api_keeps_previous_scene_alive(self):
        first, second = SceneA(), SceneB()
        SceneManager.add_scene("first", first)
        SceneManager.add_scene("second", second)
        self.assertIs(SceneManager.set_active("first"), first)
        SceneManager.set_active("second")
        self.assertFalse(first.is_destroyed)
        SceneManager.set_active("first")
        self.assertEqual(LIFECYCLE.count("A.start"), 1)       # start() only the first time
        self.assertIsNone(SceneManager.set_active("nope"))
        self.assertTrue(any("nope" in m for m in self.messages("ERROR")))

    def test_registered_class_is_instantiated_fresh_each_time(self):
        SceneManager.register("level", SceneB)
        first = SceneManager.change_scene("level")
        second = SceneManager.change_scene("level")
        self.assertIsNot(first, second)
        self.assertTrue(first.is_destroyed)

    def test_a_left_scene_is_actually_garbage_collected(self):
        # "destroy() upon exit for clean garbage collection": nothing global (SceneManager,
        # EventBus, caches, pools, Input...) may keep the old scene or its objects alive.
        import gc
        import weakref

        class Busy(Scene):
            def start(self):
                super().start()
                add_box(self, 0, 300, 400, 20, name="floor", static=True)
                player = add_box(self, 50, 0, name="player", body=True)
                player.add_component(PlayerController())
                hud = GameObject(10, 10, name="hud")
                hud.add_component(UIText("hello"))
                hud.add_component(UIHealthBar(100, 10))
                self.add_game_object(hud)
                fx = GameObject(60, 60, name="fx")
                fx.add_component(ParticleSystem(emission_rate=50, lifetime=(0.5, 1.0), seed=1))
                self.add_game_object(fx)
                self.pool = GameObjectPool(self, lambda: add_box(self, 0, 0, 8, 8, name="bullet", body=True),
                                           initial_size=4)
                self.pool.spawn(x=5, y=5)
                EventBus.subscribe("score", self.on_score, owner=self)
                player.events.subscribe("jumped", self.on_score)
                self.floor_ref = self.find_game_object("floor")

            def on_score(self, *a, **k):
                pass

        first = SceneManager.change_scene(Busy)
        for _ in range(30):
            SceneManager.update(DT)
            render(first)
        refs = [weakref.ref(first), weakref.ref(first.find_game_object("player")),
                weakref.ref(first.find_game_object("fx").get_component(ParticleSystem)),
                weakref.ref(first.pool)]
        del first
        SceneManager.change_scene(SceneB)          # tears the busy scene down
        gc.collect()
        self.assertEqual([r() is None for r in refs], [True] * 4,
                         "the old scene (or something in it) is still referenced from a global")

    def test_hooks_exist_on_base_scene(self):
        scene = Scene()
        for hook in ("start", "update", "fixed_update", "draw", "destroy"):
            self.assertTrue(callable(getattr(scene, hook)))


# ==========================================================================================
# 2. Fixed timestep + physics
# ==========================================================================================

class TestFixedTimestep(EngineTestCase):
    def test_physics_rate_is_independent_of_frame_rate(self):
        for fps, expected_updates in ((30, 30), (60, 60), (144, 144)):
            scene = Scene()
            rec = GameObject()
            recorder = rec.add_component(Recorder())
            scene.add_game_object(rec)
            run(scene, 1.0, fps)
            self.assertEqual(recorder.updates, expected_updates, f"{fps} fps updates")
            self.assertLessEqual(abs(recorder.fixed - 60), 1, f"{fps} fps fixed steps = {recorder.fixed}")

    def test_lag_spike_catches_up_in_several_steps_but_is_capped(self):
        scene = Scene()
        rec = GameObject()
        recorder = rec.add_component(Recorder())
        scene.add_game_object(rec)
        steps = scene.tick(0.1)                        # 6 steps' worth of time
        self.assertEqual(steps, 6)
        steps = scene.tick(30.0)                       # clamped, then capped: no spiral of death
        self.assertLessEqual(steps, Time.max_fixed_steps)
        self.assertLess(scene._accumulator, Time.fixed_delta_time)

    def test_same_step_count_gives_identical_state_at_any_frame_rate(self):
        def build():
            scene = Scene()
            add_box(scene, 0, 300, 400, 20, static=True, sprite=False)
            bodies = [add_box(scene, 20 + i * 41.5, 3.3 * i, name=f"b{i}", body=True, sprite=False) for i in range(6)]
            bodies[0].get_component(Rigidbody2D).velocity.x = 90.0
            return scene, bodies

        scene_a, bodies_a = build()
        for _ in range(120):
            scene_a.tick(1 / 60)
        steps_a = scene_a.physics.stats.steps

        scene_b, bodies_b = build()
        while scene_b.physics.stats.steps < steps_a:
            scene_b.tick(1 / 144)
        self.assertEqual(scene_b.physics.stats.steps, steps_a)
        for a, b in zip(bodies_a, bodies_b):
            self.assertEqual(a.transform.get_world_xy(), b.transform.get_world_xy())

    def test_time_scale_zero_pauses_simulation(self):
        scene = Scene()
        body = add_box(scene, 0, 0, body=True, sprite=False)
        run(scene, 0.5)
        y = body.transform.world_y
        Time.time_scale = 0.0
        run(scene, 1.0)
        self.assertEqual(body.transform.world_y, y)
        Time.time_scale = 1.0
        run(scene, 0.2)
        self.assertGreater(body.transform.world_y, y)

    def test_fast_body_cannot_tunnel_through_a_thin_wall(self):
        for dt in (1 / 60, 1 / 30, 0.25):
            scene = Scene()
            add_box(scene, 300, 0, 4, 200, name="wall", static=True, sprite=False)
            bullet = add_box(scene, 0, 50, 8, 8, name="bullet", body=True, sprite=False,
                             use_gravity=False)
            bullet.get_component(Rigidbody2D).velocity.x = 6000.0     # 100 px per step
            for _ in range(int(1.0 / dt)):
                scene.tick(dt)
            right_edge = bullet.get_component(BoxCollider2D).bounds[2]
            self.assertLessEqual(right_edge, 300.0 + 1e-6, f"tunneled at dt={dt}")


class TestPhysics(EngineTestCase):
    def test_free_fall_matches_analytic_gravity(self):
        scene = Scene()
        go = GameObject(0, 0)
        go.add_component(Rigidbody2D(gravity=500))
        scene.add_game_object(go)
        fixed_steps(scene, 60)
        self.assertAlmostEqual(go.transform.world_y, 0.5 * 500 * 1.0 ** 2, delta=250 * 0.03)
        self.assertAlmostEqual(go.get_component(Rigidbody2D).velocity.y, 500.0, delta=1.0)

    def test_acceleration_forces_and_impulses(self):
        scene = Scene()
        go = GameObject()
        rb = go.add_component(Rigidbody2D(use_gravity=False, mass=2.0, acceleration=(30, 0)))
        scene.add_game_object(go)
        fixed_steps(scene, 1)
        self.assertAlmostEqual(rb.velocity.x, 30 * DT)
        rb.velocity.x = 0
        rb.acceleration.x = 0
        rb.add_impulse(10, 0)
        self.assertAlmostEqual(rb.velocity.x, 5.0)                 # impulse / mass
        rb.velocity.x = 0
        rb.add_force(40, 0)                                        # accumulated, applied next step
        fixed_steps(scene, 1)
        self.assertAlmostEqual(rb.velocity.x, (40 / 2.0) * DT)
        fixed_steps(scene, 1)
        self.assertAlmostEqual(rb.velocity.x, (40 / 2.0) * DT)     # force was one-shot
        rb.velocity.x = 0
        rb.add_force(40, 0, delta_time=0.5)                        # legacy immediate form
        self.assertAlmostEqual(rb.velocity.x, 10.0)

    def test_drag_decays_exponentially_on_both_axes(self):
        scene = Scene()
        go = GameObject()
        rb = go.add_component(Rigidbody2D(use_gravity=False, drag=2.0))
        scene.add_game_object(go)
        rb.velocity.x, rb.velocity.y = 100.0, -60.0
        fixed_steps(scene, 60)
        self.assertAlmostEqual(rb.velocity.x, 100 * math.exp(-2.0), places=6)
        self.assertAlmostEqual(rb.velocity.y, -60 * math.exp(-2.0), places=6)

    def test_ground_friction_decelerates_then_stops(self):
        scene = Scene()
        add_box(scene, 0, 200, 2000, 20, static=True, sprite=False)
        body = add_box(scene, 0, 168, name="crate", body=True, sprite=False, friction=0.5, gravity=500)
        rb = body.get_component(Rigidbody2D)
        fixed_steps(scene, 5)
        self.assertTrue(rb.is_grounded)
        rb.velocity.x = 200.0
        fixed_steps(scene, 30)                                     # 0.5 s at 250 px/s^2 -> 75 px/s left
        self.assertAlmostEqual(rb.velocity.x, 200 - 250 * 0.5, delta=2.0)
        fixed_steps(scene, 60)
        self.assertEqual(rb.velocity.x, 0.0)

    def test_body_stops_flush_against_a_wall(self):
        scene = Scene()
        add_box(scene, 200, 0, 20, 200, name="wall", static=True, sprite=False)
        body = add_box(scene, 0, 50, name="mover", body=True, sprite=False, use_gravity=False)
        rb = body.get_component(Rigidbody2D)
        rb.velocity.x = 300
        fixed_steps(scene, 120)
        self.assertEqual(body.get_component(BoxCollider2D).bounds[2], 200.0)
        self.assertEqual(rb.velocity.x, 0.0)

    def test_stacked_boxes_come_to_rest(self):
        scene = Scene()
        add_box(scene, 0, 300, 400, 20, static=True, sprite=False)
        low = add_box(scene, 100, 260, name="low", body=True, sprite=False)
        high = add_box(scene, 104, 200, name="high", body=True, sprite=False)
        fixed_steps(scene, 240)
        self.assertEqual(low.transform.world_y, 268.0)
        self.assertEqual(high.transform.world_y, 236.0)
        ys = []
        for _ in range(60):
            fixed_steps(scene, 1)
            ys.append((low.transform.world_y, high.transform.world_y))
        self.assertEqual(len(set(ys)), 1)

    def test_overlapping_spawn_is_pushed_out(self):
        scene = Scene()
        add_box(scene, 0, 100, 300, 40, static=True, sprite=False)
        body = add_box(scene, 50, 90, name="stuck", body=True, sprite=False)   # 22px into the floor
        fixed_steps(scene, 10)
        collider = body.get_component(BoxCollider2D)
        self.assertLessEqual(collider.bounds[3], 100.0 + 0.011)

    def test_landing_is_jitter_free_from_fractional_heights(self):
        for start_y in (0.3, 17.77, 123.456):
            scene = Scene()
            add_box(scene, 0, 400, 500, 20, static=True, sprite=False)
            body = add_box(scene, 40.25, start_y, name="dropper", body=True, sprite=False)
            rb = body.get_component(Rigidbody2D)
            grounded_history, ys = [], []
            for _ in range(240):
                fixed_steps(scene, 1)
                grounded_history.append(rb.is_grounded)
                ys.append(body.transform.world_y)
            first = grounded_history.index(True)
            self.assertTrue(all(grounded_history[first:]), f"is_grounded flickered (start {start_y})")
            self.assertEqual(len(set(ys[first:])), 1, f"position jittered (start {start_y})")
            self.assertEqual(ys[-1], 368.0)

    def test_walking_across_a_tile_seam_never_snags(self):
        scene = Scene()
        for i in range(10):
            add_box(scene, i * 32, 200, 32, 32, name=f"tile{i}", static=True, sprite=False)
        walker = add_box(scene, 10, 168, 20, 32, name="walker", body=True, sprite=False)
        rb = walker.get_component(Rigidbody2D)
        fixed_steps(scene, 5)
        xs = []
        for _ in range(60):
            rb.velocity.x = 180.0
            fixed_steps(scene, 1)
            xs.append(walker.transform.world_x)
        deltas = [b - a for a, b in zip(xs, xs[1:])]
        self.assertTrue(all(abs(d - 3.0) < 1e-6 for d in deltas), f"snagged: {min(deltas)}")

    def test_random_worlds_never_leave_solid_bodies_overlapping(self):
        # Property test over random layouts/velocities: whatever the swept movement,
        # depenetration and single-query optimisation do, no two solid boxes may end a
        # step overlapping by more than the contact tolerance, and nothing goes NaN/inf.
        tol = 0.011
        for seed in range(6):
            rng = random.Random(seed)
            scene = Scene()
            for i in range(25):
                add_box(scene, rng.uniform(-200, 800), rng.uniform(50, 500), rng.choice((20, 40, 90)),
                        rng.choice((10, 30, 60)), name=f"wall{i}", static=True, sprite=False)
            add_box(scene, -400, 520, 1800, 30, name="ground", static=True, sprite=False)
            bodies = []
            for i in range(30):
                go = add_box(scene, rng.uniform(-100, 700), rng.uniform(-300, 400), rng.choice((12, 20, 30)),
                             rng.choice((12, 24)), name=f"b{i}", body=True, sprite=False,
                             use_gravity=rng.random() < 0.8, drag=rng.choice((0.0, 0.5)))
                go.get_component(Rigidbody2D).velocity.x = rng.uniform(-400, 400)
                go.get_component(Rigidbody2D).velocity.y = rng.uniform(-300, 300)
                bodies.append(go)
            for _ in range(40):                                  # let initial overlaps resolve
                fixed_steps(scene, 1)
            for step in range(220):
                if step % 25 == 0:
                    body = rng.choice(bodies).get_component(Rigidbody2D)
                    body.velocity.x, body.velocity.y = rng.uniform(-600, 600), rng.uniform(-500, 100)
                fixed_steps(scene, 1)
                colliders = [c for c in scene.physics.colliders if not c.is_trigger]
                for c in colliders:
                    b = c.bounds
                    self.assertTrue(all(math.isfinite(v) for v in b), (seed, step, c.game_object.name))
                for i, a in enumerate(colliders):
                    if a.is_static:
                        continue
                    for other in colliders:
                        if other is a or (not other.is_static and colliders.index(other) < i):
                            continue
                        ab, ob = a.bounds, other.bounds
                        pen_x = min(ab[2], ob[2]) - max(ab[0], ob[0])
                        pen_y = min(ab[3], ob[3]) - max(ab[1], ob[1])
                        self.assertFalse(pen_x > tol and pen_y > tol,
                                         f"seed {seed} step {step}: {a.game_object.name} overlaps "
                                         f"{other.game_object.name} by ({pen_x:.3f}, {pen_y:.3f})")

    def test_airborne_bodies_skip_geometry_and_are_not_grounded(self):
        scene = Scene()
        add_box(scene, 5000, 5000, 32, 32, name="far", static=True, sprite=False)
        body = add_box(scene, 0, 0, name="faller", body=True, sprite=False)
        calls = []
        original = Rigidbody2D._move_y
        Rigidbody2D._move_y = lambda *a, **k: calls.append(1) or original(*a, **k)
        try:
            fixed_steps(scene, 30)
        finally:
            Rigidbody2D._move_y = original
        self.assertEqual(calls, [])
        self.assertFalse(body.get_component(Rigidbody2D).is_grounded)

    def test_kinematic_body_moves_through_solids(self):
        scene = Scene()
        add_box(scene, 100, 0, 20, 100, static=True, sprite=False)
        mover = add_box(scene, 0, 10, name="platform", body=True, sprite=False, is_kinematic=True)
        mover.get_component(Rigidbody2D).velocity.x = 120
        fixed_steps(scene, 120)
        self.assertAlmostEqual(mover.transform.world_x, 240.0, places=6)

    def test_pooling_hooks_reset_a_body(self):
        scene = Scene()
        go = GameObject()
        rb = go.add_component(Rigidbody2D())
        scene.add_game_object(go)
        rb.velocity.x = 50
        rb.on_despawn()
        self.assertEqual((rb.velocity.x, rb.velocity.y), (0, 0))


class TestLayers(EngineTestCase):
    def test_layer_registry(self):
        CollisionLayers.register("player", 1)
        CollisionLayers.register("Enemy", 2)
        self.assertEqual(CollisionLayers.index("PLAYER"), 1)
        self.assertEqual(CollisionLayers.mask("player", "enemy"), 0b110)
        with self.assertRaises(ValueError):
            CollisionLayers.index("nope")
        with self.assertRaises(ValueError):
            CollisionLayers.index(40)

    def test_bodies_pass_through_layers_they_do_not_mask(self):
        CollisionLayers.register("ghost", 3)
        CollisionLayers.register("wall", 4)
        scene = Scene()
        wall = add_box(scene, 0, 200, 400, 20, static=True, sprite=False, layer="wall")
        solid = add_box(scene, 50, 100, name="solid", body=True, sprite=False, layer="default")
        ghost = add_box(scene, 200, 100, name="ghost", body=True, sprite=False, layer="ghost",
                        mask=CollisionLayers.mask("default"))          # ignores "wall"
        fixed_steps(scene, 120)
        self.assertEqual(solid.transform.world_y, 168.0)
        self.assertGreater(ghost.transform.world_y, 400)               # fell straight through

    def test_interaction_needs_both_masks_to_agree(self):
        CollisionLayers.register("a", 1)
        CollisionLayers.register("b", 2)
        scene = Scene()
        floor = add_box(scene, 0, 200, 400, 20, static=True, sprite=False, layer="a", mask=CollisionLayers.ALL)
        body = add_box(scene, 50, 100, body=True, sprite=False, layer="b", mask=CollisionLayers.mask("a"))
        floor.get_component(BoxCollider2D).mask = CollisionLayers.mask("default")   # floor doesn't want "b"
        fixed_steps(scene, 90)
        self.assertGreater(body.transform.world_y, 300)

    def test_non_interacting_layers_skip_the_exact_overlap_test(self):
        CollisionLayers.register("x", 1)
        CollisionLayers.register("y", 2)
        scene = Scene()
        add_box(scene, 0, 0, name="tx", trigger=True, sprite=False, layer="x", mask=CollisionLayers.mask("x"))
        add_box(scene, 0, 0, name="ty", trigger=True, sprite=False, layer="y", mask=CollisionLayers.mask("y"))
        calls = []
        original = Collider2D._overlap_strict
        Collider2D._overlap_strict = lambda self, other: calls.append(1) or original(self, other)
        try:
            fixed_steps(scene, 5)
            self.assertEqual(calls, [], "layers x/y don't interact: no exact test should run")
            add_box(scene, 0, 0, name="tx2", trigger=True, sprite=False, layer="x", mask=CollisionLayers.mask("x"))
            fixed_steps(scene, 1)
            self.assertGreater(len(calls), 0)
        finally:
            Collider2D._overlap_strict = original


# ==========================================================================================
# Collision + trigger callbacks
# ==========================================================================================

class TestCallbacks(EngineTestCase):
    def test_collision_enter_stay_exit_via_hooks(self):
        scene = Scene()
        add_box(scene, 0, 200, 400, 20, name="ground", static=True, sprite=False)
        body = add_box(scene, 50, 100, name="ball", body=True, sprite=False)
        rec = body.add_component(Recorder())
        fixed_steps(scene, 120)
        kinds = rec.kinds()
        self.assertEqual(kinds.count("col_enter"), 1)
        self.assertGreater(kinds.count("col_stay"), 30)
        self.assertNotIn("col_exit", kinds)
        self.assertEqual(rec.log[0], ("col_enter", "ground"))
        body.get_component(Rigidbody2D).velocity.y = -400          # leap away
        fixed_steps(scene, 5)
        self.assertEqual(rec.kinds().count("col_exit"), 1)

    def test_collision_object_carries_a_contact_normal(self):
        scene = Scene()
        add_box(scene, 0, 200, 400, 20, static=True, sprite=False)
        body = add_box(scene, 50, 150, body=True, sprite=False)
        seen = []

        class Grab(Component):
            def on_collision_enter(self, collision):
                seen.append((collision.normal.x, collision.normal.y))
        body.add_component(Grab())
        fixed_steps(scene, 60)
        self.assertEqual(seen, [(0.0, -1.0)])

    def test_list_callbacks_fire_for_collision_and_trigger(self):
        scene = Scene()
        add_box(scene, 0, 200, 400, 20, static=True, sprite=False)
        zone = add_box(scene, 40, 150, 100, 100, name="zone", trigger=True, sprite=False, static=True)
        body = add_box(scene, 50, 100, name="ball", body=True, sprite=False)
        events = []
        collider = body.get_component(BoxCollider2D)
        collider.on_collision_enter.append(lambda me, other: events.append(("col", other.game_object.name)))
        zone.get_component(BoxCollider2D).on_trigger_enter.append(lambda me, other: events.append(("trig", other.game_object.name)))
        collider.on_trigger_enter.append(lambda me, other: events.append(("self_trig", other.game_object.name)))
        fixed_steps(scene, 90)
        self.assertIn(("col", "box"), events)
        self.assertIn(("trig", "ball"), events)           # fired on the trigger
        self.assertIn(("self_trig", "zone"), events)      # ...and on the other side too

    def test_trigger_lifecycle_with_a_moving_kinematic_body(self):
        scene = Scene()
        zone = add_box(scene, 100, 0, 50, 50, name="zone", trigger=True, sprite=False, static=True)
        rec = zone.add_component(Recorder())
        mover = add_box(scene, 0, 10, 20, 20, name="mover", body=True, sprite=False, is_kinematic=True)
        mover.get_component(Rigidbody2D).velocity.x = 100
        fixed_steps(scene, 240)                                   # crosses the zone entirely
        kinds = rec.kinds()
        self.assertEqual(kinds.count("trig_enter"), 1)
        self.assertEqual(kinds.count("trig_exit"), 1)
        self.assertGreater(kinds.count("trig_stay"), 10)
        self.assertLess(kinds.index("trig_enter"), kinds.index("trig_exit"))

    def test_trigger_exit_fires_when_other_is_deactivated_or_destroyed(self):
        for how in ("deactivate", "destroy", "remove"):
            scene = Scene()
            zone = add_box(scene, 0, 0, 100, 100, name="zone", trigger=True, sprite=False, static=True)
            rec = zone.add_component(Recorder())
            visitor = add_box(scene, 10, 10, 20, 20, name="visitor", body=True, sprite=False, use_gravity=False)
            fixed_steps(scene, 3)
            self.assertEqual(rec.kinds().count("trig_enter"), 1)
            collider = zone.get_component(BoxCollider2D)
            self.assertEqual(len(collider.overlapping_colliders), 1)
            if how == "deactivate":
                visitor.active = False
            elif how == "destroy":
                visitor.destroy()
            else:
                scene.remove_game_object(visitor)
            fixed_steps(scene, 2)
            self.assertEqual(rec.kinds().count("trig_exit"), 1, how)
            self.assertEqual(len(collider.overlapping_colliders), 0, how)

    def test_callback_that_destroys_its_own_object_is_safe_mid_step(self):
        scene = Scene()
        add_box(scene, 0, 200, 400, 20, static=True, sprite=False)
        bullet = add_box(scene, 50, 100, name="bullet", body=True, sprite=False)

        class Explode(Component):
            def on_collision_enter(self, collision):
                self.game_object.destroy()
        bullet.add_component(Explode())
        fixed_steps(scene, 90)
        self.assertNotIn(bullet, scene.game_objects)
        self.assertIsNone(bullet.scene)

    def test_exceptions_in_callbacks_are_logged_not_raised(self):
        scene = Scene()
        zone = add_box(scene, 0, 0, 100, 100, trigger=True, sprite=False, static=True)
        visitor = add_box(scene, 10, 10, 20, 20, body=True, sprite=False, use_gravity=False)
        zone.get_component(BoxCollider2D).on_trigger_enter.append(lambda me, other: 1 / 0)

        class Boom(Component):
            def on_trigger_enter(self, other):
                raise RuntimeError("hook failed")
        zone.add_component(Boom())
        fixed_steps(scene, 3)
        self.assertTrue(any("ZeroDivisionError" in m for m in self.messages("ERROR")))
        self.assertTrue(any("hook failed" in m for m in self.messages("ERROR")))


# ==========================================================================================
# 3. Static objects, hierarchy
# ==========================================================================================

class TestStaticObjects(EngineTestCase):
    def test_static_rigidbody_is_never_simulated(self):
        scene = Scene()
        go = add_box(scene, 10, 10, body=True, sprite=False, static=True)
        fixed_steps(scene, 30)
        self.assertEqual(go.transform.get_world_xy(), (10, 10))
        self.assertEqual(scene.physics.bodies, [])

    def test_static_collider_bounds_are_computed_once(self):
        scene = Scene()
        count = {"static": 0, "dynamic": 0}
        original = BoxCollider2D._recompute_bounds

        def counting(self, transform):
            count["static" if self.game_object.is_static else "dynamic"] += 1
            original(self, transform)
        BoxCollider2D._recompute_bounds = counting
        try:
            add_box(scene, 0, 0, name="wall", static=True, sprite=False)
            mover = add_box(scene, 50, 0, name="mover", sprite=False)
            run(scene, 1.0)
            self.assertEqual(count["static"], 1)               # registered once, never again
            before = count["dynamic"]
            run(scene, 1.0)
            self.assertEqual(count["dynamic"], before)         # unmoved dynamic collider: no recompute either
            mover.transform.position.x += 5
            fixed_steps(scene, 1)
            self.assertEqual(count["dynamic"], before + 1)
        finally:
            BoxCollider2D._recompute_bounds = original

    def test_static_objects_still_run_gameplay_components(self):
        scene = Scene()
        go = GameObject(is_static=True)
        recorder = go.add_component(Recorder())
        scene.add_game_object(go)
        run(scene, 0.5)
        self.assertEqual(recorder.updates, 30)

    def test_unsetting_static_lets_the_object_move_again(self):
        scene = Scene()
        crate = add_box(scene, 0, 0, name="crate", static=True, sprite=False)
        self.assertEqual(len(scene.physics._dynamic), 0)
        crate.is_static = False
        crate.transform.position.x = 500
        fixed_steps(scene, 1)
        hits = scene.physics.query_point(510, 10)
        self.assertEqual([c.game_object.name for c in hits], ["crate"])
        self.assertEqual(scene.physics.query_point(10, 10), [])

    def test_moving_a_static_object_warns_once(self):
        scene = Scene()
        crate = add_box(scene, 0, 0, name="crate", static=True, sprite=False)
        crate.transform.position.x = 5
        crate.transform.position.x = 6
        warnings = [m for m in self.messages("WARNING") if "is_static" in m]
        self.assertEqual(len(warnings), 1)


class TestTransformHierarchy(EngineTestCase):
    def test_world_position_composes_parent_and_local(self):
        parent = GameObject(100, 50)
        child = GameObject(20, 5, parent=parent)
        self.assertEqual(child.transform.get_world_xy(), (120, 55))
        parent.transform.position.x += 10
        self.assertEqual(child.transform.get_world_xy(), (130, 55))
        self.assertEqual(child.transform.local_position, Vector2(20, 5))
        self.assertIs(child.transform.position, child.transform.local_position)

    def test_rotation_and_scale_compose(self):
        parent = GameObject(100, 100)
        child = GameObject(10, 0, parent=parent)
        parent.transform.rotation = 90            # clockwise on screen: +x turns into +y (down)
        x, y = child.transform.get_world_xy()
        self.assertAlmostEqual(x, 100, places=6)
        self.assertAlmostEqual(y, 110, places=6)
        self.assertAlmostEqual(child.transform.world_rotation, 90)
        parent.transform.rotation = 0
        parent.transform.scale = Vector2(2, 3)
        self.assertEqual(child.transform.get_world_xy(), (120, 100))
        self.assertEqual(child.transform.world_scale, Vector2(2, 3))

    def test_dirty_flag_caches_world_values(self):
        parent = GameObject(0, 0)
        child = GameObject(1, 1, parent=parent)
        grandchild = GameObject(1, 1, parent=child)
        grandchild.transform.get_world_xy()
        self.assertFalse(grandchild.transform.is_dirty)
        version = grandchild.transform.world_version
        for _ in range(100):
            grandchild.transform.get_world_xy()
        self.assertEqual(grandchild.transform.world_version, version)     # nothing recomputed

        parent.transform.position.x += 1                                  # in-place mutation
        for go in (parent, child, grandchild):
            self.assertTrue(go.transform.is_dirty)
        grandchild.transform.get_world_xy()
        self.assertEqual(grandchild.transform.world_version, version + 1)  # recomputed exactly once
        self.assertFalse(child.transform.is_dirty)                         # ...and so was the chain

    def test_reparenting_and_keeping_world_position(self):
        a = GameObject(100, 100)
        b = GameObject(300, 50)
        b.transform.rotation = 0
        child = GameObject(20, 0, parent=a)
        self.assertEqual(child.transform.get_world_xy(), (120, 100))
        child.set_parent(b)                                    # keeps the local offset
        self.assertEqual(child.transform.get_world_xy(), (320, 50))
        child.set_parent(a, keep_world_position=True)          # keeps where it is in the world
        self.assertEqual(child.transform.get_world_xy(), (320, 50))
        self.assertEqual(child.transform.local_position, Vector2(220, -50))
        child.transform.world_position = Vector2(0, 0)
        self.assertEqual(child.transform.local_position, Vector2(-100, -100))

    def test_cycles_are_rejected(self):
        a, b = GameObject(), GameObject()
        b.set_parent(a)
        with self.assertRaises(ValueError):
            a.set_parent(b)
        with self.assertRaises(ValueError):
            a.set_parent(a)

    def test_children_join_the_scene_with_their_parent(self):
        scene = Scene()
        parent = GameObject(name="p")
        child = GameObject(name="c", parent=parent)
        scene.add_game_object(parent)
        self.assertIs(child.scene, scene)
        late = GameObject(name="late")
        late.set_parent(parent)                       # parenting to an object in a scene adds it
        self.assertIs(late.scene, scene)
        self.assertEqual(parent.children, [child, late])

    def test_destroying_a_parent_destroys_children(self):
        scene = Scene()
        parent = GameObject(name="p")
        child = GameObject(name="c", parent=parent)
        child.add_component(Destroyable())
        Destroyable.destroyed = 0
        scene.add_game_object(parent)
        parent.destroy()
        self.assertEqual(scene.game_objects, [])
        self.assertEqual(Destroyable.destroyed, 1)
        self.assertIsNone(child.scene)

    def test_inactive_parent_deactivates_the_subtree(self):
        scene = Scene()
        parent = GameObject(name="p")
        child = GameObject(name="c", parent=parent)
        rec = child.add_component(Recorder())
        scene.add_game_object(parent)
        run(scene, 0.1)
        ticks = rec.updates
        parent.active = False
        self.assertFalse(child.active_in_hierarchy)
        self.assertTrue(child.active)
        run(scene, 0.1)
        self.assertEqual(rec.updates, ticks)
        parent.active = True
        run(scene, 0.1)
        self.assertGreater(rec.updates, ticks)

    def test_collider_on_a_child_follows_its_parent(self):
        scene = Scene()
        player = GameObject(100, 100, name="player")
        weapon = GameObject(30, 0, name="weapon", parent=player)
        weapon.add_component(BoxCollider2D(size=(10, 10), is_trigger=True))
        scene.add_game_object(player)
        collider = weapon.get_component(BoxCollider2D)
        self.assertEqual(collider.bounds, (130, 100, 140, 110))
        player.transform.position.x = 500
        fixed_steps(scene, 1)
        self.assertEqual(collider.bounds, (530, 100, 540, 110))
        self.assertEqual([c.game_object.name for c in scene.physics.query_point(535, 105)], ["weapon"])

    def test_hierarchy_helpers(self):
        root = GameObject(name="root")
        mid = GameObject(name="mid", parent=root)
        leaf = GameObject(name="leaf", parent=mid)
        self.assertEqual(leaf.transform.depth, 2)
        self.assertIs(leaf.transform.root, root.transform)
        self.assertIs(root.find_child("mid"), mid)
        p = leaf.transform.transform_point(5, 0)
        self.assertEqual((p.x, p.y), (5, 0))
        back = leaf.transform.inverse_transform_point(5, 0)
        self.assertEqual((back.x, back.y), (5, 0))


# ==========================================================================================
# 3. Rendering: culling, baking, sorting, interpolation, caching, animation
# ==========================================================================================

BG = (10, 20, 30)


def render(scene, size=(640, 480)):
    surface = pygame.Surface(size)
    surface.fill(BG)
    scene.draw(surface)
    return surface


def pixels(surface):
    return pygame.image.tostring(surface, "RGB")


def sprite_go(scene, x, y, w, h, color, name="s", z=0, static=False, **kw):
    go = GameObject(x, y, name=name, is_static=static)
    renderer = go.add_component(SpriteRenderer(sprite=make_surface(w, h, color), z_index=z, **kw))
    scene.add_game_object(go)
    return go, renderer


class TestCulling(EngineTestCase):
    def test_offscreen_dynamic_sprites_are_not_drawn(self):
        scene = Scene()
        sprite_go(scene, 100, 100, 32, 32, (255, 0, 0), "inside")
        sprite_go(scene, 5000, 5000, 32, 32, (0, 255, 0), "far")
        sprite_go(scene, -16, 50, 32, 32, (0, 0, 255), "edge")
        surface = render(scene)
        stats = scene.render_system.stats
        self.assertEqual((stats.sprites_drawn, stats.sprites_culled, stats.draw_calls), (2, 1, 2))
        self.assertEqual(surface.get_at((110, 110))[:3], (255, 0, 0))
        self.assertEqual(surface.get_at((5, 60))[:3], (0, 0, 255))

    def test_scaled_sprite_is_culled_by_its_transformed_bounds(self):
        # Regression: culling used the *unscaled* size, so a magnified sprite
        # whose edge was still on screen popped out of existence.
        scene = Scene()
        # Unscaled footprint is x -70..-38 (fully off-screen). Scaled 4x around its
        # centre (x = -54) it spans -118..10, so its right edge is on screen.
        go, _ = sprite_go(scene, -70, 100, 32, 32, (255, 0, 0), "big")
        go.transform.scale = Vector2(4, 4)
        surface = render(scene)
        self.assertEqual(scene.render_system.stats.sprites_drawn, 1)
        self.assertEqual(surface.get_at((5, 116))[:3], (255, 0, 0))
        self.assertEqual(surface.get_at((12, 116))[:3], BG)

    def test_static_sprites_use_the_grid_and_only_visible_ones_draw(self):
        rng = random.Random(7)
        scene = Scene()
        boxes = []
        for i in range(1000):
            x, y = rng.randrange(-10000, 10000), rng.randrange(-10000, 10000)
            sprite_go(scene, x, y, 16, 16, (200, 50, 50), f"s{i}", static=True)
            boxes.append((x, y))
        camera_target = GameObject(0, 0)
        scene.add_game_object(camera_target)
        cam = camera_target.add_component(Camera(target=camera_target))
        scene.set_active_camera(cam)
        render(scene)
        vl, vt = -320, -240
        expected = sum(1 for x, y in boxes if x + 16 >= vl and x <= vl + 640 and y + 16 >= vt and y <= vt + 480)
        self.assertEqual(scene.render_system.stats.sprites_drawn, expected)
        self.assertEqual(scene.render_system.stats.static_registered, 1000)
        self.assertGreater(scene.render_system.stats.sprites_culled, 900)

    def test_z_index_then_y_decides_draw_order(self):
        scene = Scene()
        sprite_go(scene, 0, 0, 40, 40, (0, 0, 255), "low", z=0)
        sprite_go(scene, 10, 10, 40, 40, (255, 0, 0), "high", z=1)
        surface = render(scene)
        self.assertEqual(surface.get_at((20, 20))[:3], (255, 0, 0))          # higher z wins the overlap

        scene = Scene()
        sprite_go(scene, 0, 20, 40, 40, (255, 255, 0), "front")               # created first, but lower on screen
        sprite_go(scene, 10, 0, 40, 40, (0, 255, 0), "back")
        surface = render(scene)
        self.assertEqual(surface.get_at((20, 30))[:3], (255, 255, 0))        # larger y draws in front

    def test_rotation_and_scale_pivot_around_the_center(self):
        scene = Scene()
        go, _ = sprite_go(scene, 100, 100, 20, 20, (255, 0, 0), "spin")
        go.transform.scale = Vector2(2, 2)
        surface = render(scene)
        self.assertEqual(surface.get_at((99, 99))[:3], (255, 0, 0))          # 40x40 centered on the 20x20 footprint
        self.assertEqual(surface.get_at((80, 80))[:3], BG)
        go.transform.rotation = 45
        surface = render(scene)
        self.assertEqual(surface.get_at((110, 110))[:3], (255, 0, 0))

    def test_child_sprite_draws_at_world_position(self):
        scene = Scene()
        parent = GameObject(200, 200)
        child, _ = sprite_go(scene, 50, 0, 10, 10, (255, 0, 0), "held")
        child.set_parent(parent)
        scene.add_game_object(parent)
        surface = render(scene)
        self.assertEqual(surface.get_at((252, 202))[:3], (255, 0, 0))


class TestBaking(EngineTestCase):
    def build_static_scene(self, seed=4, alpha=False):
        rng = random.Random(seed)
        scene = Scene()
        for i in range(150):
            color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            size = (rng.choice((16, 24, 32)), rng.choice((16, 24)))
            go = GameObject(rng.randrange(-100, 700), rng.randrange(-100, 560), name=f"t{i}", is_static=True)
            if alpha:
                surf = pygame.Surface(size, pygame.SRCALPHA)
                surf.fill((*color, 128))
            else:
                surf = make_surface(*size, color)
            go.add_component(SpriteRenderer(sprite=surf))
            scene.add_game_object(go)
        return scene

    def test_baked_layer_matches_individual_blits_pixel_for_pixel(self):
        scene = self.build_static_scene()
        before = render(scene)
        calls_before = scene.render_system.stats.draw_calls
        layers = bake_static_sprites(scene)
        after = render(scene)
        self.assertEqual(pixels(before), pixels(after))
        self.assertGreater(calls_before, 50)
        self.assertLessEqual(scene.render_system.stats.draw_calls, 4)     # hundreds of blits -> one
        self.assertEqual(len(layers), 1)

    def test_chunked_bake_matches_single_surface(self):
        scene = self.build_static_scene(seed=9)
        before = render(scene)
        layers = bake_static_sprites(scene, chunk_size=96)
        layer = layers[0].get_component(BakedLayer)
        self.assertGreater(layer.chunk_count, 4)
        self.assertEqual(pixels(before), pixels(render(scene)))

    def test_overlapping_translucent_sprites_bake_within_rounding(self):
        scene = self.build_static_scene(seed=2, alpha=True)
        before = render(scene)
        bake_static_sprites(scene)
        after = render(scene)
        worst = max(abs(a - b) for a, b in zip(pixels(before), pixels(after)))
        self.assertLessEqual(worst, 3)          # rounding only; a naive alpha-on-alpha bake is off by ~30

    def test_bake_tilemap_places_tiles_on_the_grid(self):
        scene = Scene()
        red, blue = make_surface(32, 32, (255, 0, 0)), make_surface(32, 32, (0, 0, 255))
        go = bake_tilemap([[1, None], [None, 2]], {1: red, 2: blue}, 32, origin=(10, 20))
        scene.add_game_object(go)
        surface = render(scene)
        self.assertEqual(surface.get_at((15, 25))[:3], (255, 0, 0))
        self.assertEqual(surface.get_at((10 + 32 + 5, 20 + 32 + 5))[:3], (0, 0, 255))
        self.assertEqual(surface.get_at((10 + 32 + 5, 25))[:3], BG)
        self.assertEqual(go.get_component(BakedLayer).item_count, 2)

    def test_huge_sparse_maps_are_chunked_not_one_giant_surface(self):
        red = make_surface(32, 32, (255, 0, 0))
        go = bake_tilemap([[1] + [None] * 9999] + [[None] * 10000] * 0, {1: red}, 32)     # 1 x 10000 grid
        layer = go.get_component(BakedLayer)
        layer.bake([(red, 0, 0), (red, 12000, 12000)])
        self.assertEqual(layer.chunk_count, 2)                    # only chunks holding tiles exist
        scene = Scene()
        scene.add_game_object(go)
        target = GameObject(12000 + 16, 12000 + 16)
        scene.add_game_object(target)
        cam = target.add_component(Camera(target=target))
        scene.set_active_camera(cam)
        surface = render(scene)
        self.assertEqual(surface.get_at((320, 240))[:3], (255, 0, 0))

    def test_baking_leaves_colliders_and_gameplay_components_working(self):
        scene = Scene()
        wall = add_box(scene, 100, 100, 32, 32, name="wall", static=True)
        bake_static_sprites(scene)
        self.assertFalse(wall.get_component(SpriteRenderer).enabled)
        self.assertEqual([c.game_object.name for c in scene.physics.query_point(110, 110)], ["wall"])

    def test_animated_and_dynamic_sprites_are_not_baked(self):
        scene = Scene()
        sprite_go(scene, 0, 0, 10, 10, (1, 2, 3), "mover")
        anim, _ = sprite_go(scene, 50, 0, 10, 10, (1, 2, 3), "torch", static=True)
        anim.add_component(Animator({"a": [make_surface(10, 10)]}, default_animation="a"))
        self.assertEqual(bake_static_sprites(scene), [])


class TestInterpolation(EngineTestCase):
    def moving_body(self, scene):
        body = add_box(scene, 0, 0, 8, 8, name="m", body=True, sprite=False, use_gravity=False)
        body.get_component(Rigidbody2D).velocity.x = 600
        return body

    def test_render_position_blends_between_physics_steps(self):
        scene = Scene()
        body = self.moving_body(scene)
        fixed_steps(scene, 1)                                 # x: 0 -> 10
        t = body.transform
        self.assertAlmostEqual(t.get_render_xy(0.0)[0], 0.0)
        self.assertAlmostEqual(t.get_render_xy(0.5)[0], 5.0)
        self.assertAlmostEqual(t.get_render_xy(1.0)[0], 10.0)

    def test_teleport_and_scripted_moves_are_never_smeared(self):
        scene = Scene()
        body = self.moving_body(scene)
        fixed_steps(scene, 1)
        body.get_component(Rigidbody2D).teleport(500, 20)
        self.assertEqual(body.transform.get_render_xy(0.5), (500, 20))
        fixed_steps(scene, 1)
        body.transform.position.x = 300                        # gameplay code moved it between steps
        self.assertEqual(body.transform.get_render_xy(0.5)[0], 300)

    def test_child_follows_the_interpolated_parent(self):
        scene = Scene()
        body = self.moving_body(scene)
        weapon = GameObject(20, 0, parent=body)
        scene.add_game_object(weapon)
        fixed_steps(scene, 1)
        self.assertAlmostEqual(weapon.transform.get_render_xy(0.5)[0], 25.0)
        self.assertAlmostEqual(weapon.transform.get_world_xy()[0], 30.0)

    def test_static_and_non_physics_objects_are_not_interpolated(self):
        go = GameObject(10, 10)
        self.assertEqual(go.transform.get_render_xy(0.5), (10, 10))

    def test_sprite_and_camera_use_the_same_interpolated_position(self):
        scene = Scene()
        body = add_box(scene, 0, 100, 8, 8, name="m", body=True, use_gravity=False, color=(255, 0, 0))
        body.get_component(Rigidbody2D).velocity.x = 600
        fixed_steps(scene, 1)
        Time.alpha = 0.5
        surface = render(scene)
        self.assertEqual(surface.get_at((5, 102))[:3], (255, 0, 0))
        self.assertEqual(surface.get_at((3, 102))[:3], BG)
        cam = GameObject().add_component(Camera(target=body, smooth_follow=False))
        cam.game_object.transform.parent = None
        cam.update(DT)
        self.assertAlmostEqual(cam.position.x, 5.0, places=6)
        Time.alpha = 1.0


class TestSurfaceCaching(EngineTestCase):
    def test_transformed_variants_are_cached_quantized_and_bounded(self):
        cache = SurfaceCache(max_entries=4)
        img = make_surface(20, 10)
        a = cache.get_transformed(img, 30.0, 1, 1)
        b = cache.get_transformed(img, 30.2, 1, 1)             # same 1-degree step
        self.assertIs(a, b)
        self.assertEqual((cache.hits, cache.misses), (1, 1))
        for angle in (10, 20, 40, 50, 60):
            cache.get_transformed(img, angle, 1, 1)
        self.assertEqual(len(cache), 4)                        # LRU bound holds
        exact = SurfaceCache()
        self.assertIsNot(exact.get_transformed(img, 30.0, 1, 1, rotation_step=0),
                         exact.get_transformed(img, 30.2, 1, 1, rotation_step=0))

    def test_scale_sizes_and_negative_scale_mirrors(self):
        cache = SurfaceCache()
        img = pygame.Surface((10, 4))
        img.fill((255, 0, 0), (0, 0, 5, 4))
        img.fill((0, 0, 255), (5, 0, 5, 4))
        self.assertEqual(cache.get_transformed(img, 0, 2, 3).get_size(), (20, 12))
        mirrored = cache.get_transformed(img, 0, -1, 1)
        self.assertEqual(mirrored.get_at((0, 0))[:3], (0, 0, 255))

    def test_prepare_surface_converts_once_and_is_idempotent(self):
        opaque = pygame.Surface((8, 8), 0, 24)
        converted = prepare_surface(opaque)
        self.assertEqual(converted.get_bitsize(), DISPLAY.get_bitsize())
        self.assertIs(prepare_surface(converted), converted)
        self.assertIs(prepare_surface(opaque), converted)      # memoized
        alpha = pygame.Surface((8, 8), pygame.SRCALPHA)
        self.assertTrue(prepare_surface(alpha).get_flags() & pygame.SRCALPHA)
        self.assertIsNone(prepare_surface(None))

    def test_renderer_can_skip_conversion(self):
        img = pygame.Surface((8, 8), 0, 24)
        self.assertIs(SpriteRenderer(sprite=img, convert=False).sprite, img)


class TestAnimator(EngineTestCase):
    def build(self, scene, x=100, y=100, frames=4, loop_kwargs=None, **animator_kwargs):
        surfaces = [make_surface(8, 8, (i * 40, 0, 0)) for i in range(frames)]
        go = GameObject(x, y)
        go.add_component(SpriteRenderer(sprite=surfaces[0]))
        animator = go.add_component(Animator({"run": surfaces}, default_animation="run",
                                             frame_duration=0.1, **animator_kwargs))
        scene.add_game_object(go)
        return go, animator

    def test_playback_speed_is_bound_to_time_not_frame_rate(self):
        indices = []
        for fps in (30, 60, 144):
            scene = Scene()
            _, animator = self.build(scene)
            run(scene, 1.05, fps)
            indices.append(animator.frame_index)
        self.assertEqual(indices, [2, 2, 2])                   # 10 frames elapsed, mod 4

    def test_speed_multiplier(self):
        scene = Scene()
        _, animator = self.build(scene, speed=2.0)
        run(scene, 0.55, 60)
        self.assertEqual(animator.frame_index, 11 % 4)

    def test_frames_are_converted_to_display_format(self):
        scene = Scene()
        _, animator = self.build(scene)
        frame = animator.animations["run"][0]
        self.assertIs(prepare_surface(frame), frame)
        self.assertIs(animator.sprite_renderer.sprite, frame)

    def test_offscreen_looping_animation_does_not_tick(self):
        scene = Scene()
        go, animator = self.build(scene, x=9000, y=9000)
        surface = pygame.Surface((640, 480))
        for _ in range(10):                                    # a few real frames so visibility is established
            scene.tick(DT)
            scene.draw(surface)
        self.assertFalse(animator.sprite_renderer.is_visible)
        frozen = (animator.frame_index, animator._timer)
        for _ in range(60):
            scene.tick(DT)
            scene.draw(surface)
        self.assertEqual((animator.frame_index, animator._timer), frozen)
        go.transform.position.x = 100                          # comes into view -> resumes
        go.transform.position.y = 100
        for _ in range(30):
            scene.tick(DT)
            scene.draw(surface)
        self.assertNotEqual((animator.frame_index, animator._timer), frozen)

    def test_animations_keep_running_when_the_scene_is_never_drawn(self):
        # Headless simulation: without a draw pass "off-screen" has no meaning.
        scene = Scene()
        _, animator = self.build(scene, x=9000, y=9000)
        run(scene, 1.05, 60)
        self.assertEqual(animator.frame_index, 2)

    def test_offscreen_culling_can_be_disabled_and_finish_callbacks_still_fire(self):
        scene = Scene()
        go, animator = self.build(scene, x=9000, y=9000)
        animator.play("run", loop=False, force_restart=True)
        finished = []
        animator.on_finished.append(lambda a, name: finished.append(name))
        surface = pygame.Surface((640, 480))
        for _ in range(60):
            scene.tick(DT)
            scene.draw(surface)
        self.assertEqual(finished, ["run"])                    # off-screen, but gameplay logic still completed

        scene2 = Scene()
        _, always = self.build(scene2, x=9000, y=9000, cull_offscreen=False)
        for _ in range(60):
            scene2.tick(DT)
            scene2.draw(surface)
        self.assertNotEqual((always.frame_index, always._timer), (0, 0.0))


# ==========================================================================================
# 4. Input
# ==========================================================================================

def key_event(kind, key):
    return pygame.event.Event(kind, key=key)


class TestInput(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.input = Input.instance()

    def new_frame(self):
        self.input.begin_frame()

    def test_string_key_names(self):
        self.assertEqual(normalize_key("space"), pygame.K_SPACE)
        self.assertEqual(normalize_key("w"), pygame.K_w)
        self.assertEqual(normalize_key("left_shift"), pygame.K_LSHIFT)
        self.assertEqual(normalize_key("Left Shift"), pygame.K_LSHIFT)
        self.assertEqual(normalize_key("right_ctrl"), pygame.K_RCTRL)
        self.assertEqual(normalize_key("mouse_left"), "mouse_left")
        self.assertEqual(normalize_key(Key.W), pygame.K_w)
        for bad in ("notakey", True, 3.5):
            with self.assertRaises(ValueError):
                normalize_key(bad)

    def test_down_pressed_up_semantics_across_frames(self):
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYDOWN, pygame.K_SPACE))
        self.assertTrue(Input.is_key_down("space"))
        self.assertTrue(Input.is_key_pressed("space"))
        self.assertFalse(Input.is_key_up("space"))
        self.new_frame()                                       # still held
        self.assertTrue(Input.is_key_down("space"))
        self.assertFalse(Input.is_key_pressed("space"))
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYUP, pygame.K_SPACE))
        self.assertFalse(Input.is_key_down("space"))
        self.assertTrue(Input.is_key_up("space"))
        self.new_frame()
        self.assertFalse(Input.is_key_up("space"))

    def test_a_tap_shorter_than_one_frame_is_not_lost(self):
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYDOWN, pygame.K_e))
        self.input.process_event(key_event(pygame.KEYUP, pygame.K_e))
        self.assertTrue(Input.is_key_pressed("e"))
        self.assertTrue(Input.is_key_up("e"))
        self.assertTrue(Input.is_key_down("e"))

    def test_os_key_repeat_is_not_a_new_press(self):
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYDOWN, pygame.K_a))
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYDOWN, pygame.K_a))
        self.assertFalse(Input.is_key_pressed("a"))

    def test_mouse_buttons_position_delta_and_wheel(self):
        self.new_frame()
        self.input.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 6)))
        self.input.process_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(5, 6)))
        self.assertTrue(Input.is_key_pressed("mouse_left"))
        self.assertTrue(Input.is_key_down("mouse_right"))
        self.assertTrue(Input.is_mouse_just_pressed(0))        # legacy index API agrees
        self.input.process_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=2))
        self.input.process_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1))
        self.assertEqual(Input.mouse_scroll(), 3)
        self.input.inject_mouse_position(100, 50)
        self.input.update()
        self.input.inject_mouse_position(110, 45)
        self.input.update()
        self.assertEqual(Input.mouse_position(), (110, 45))
        self.assertEqual(Input.mouse_delta(), (10, -5))
        self.new_frame()
        self.assertEqual(Input.mouse_scroll(), 0)              # wheel ticks are per-frame
        self.assertTrue(Input.is_key_down("mouse_left"))       # buttons persist until released

    def test_fixed_step_sees_every_press_exactly_once(self):
        # A frame may run two physics steps or none; edges must not be dropped or duplicated.
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYDOWN, pygame.K_SPACE))
        self.new_frame()                                       # a frame passes with NO fixed step
        self.assertFalse(Input.is_key_pressed("space"))        # per-frame edge is gone...
        Time.in_fixed_step = True
        self.assertTrue(Input.is_key_pressed("space"))         # ...but the fixed step still sees it
        self.assertTrue(Input.is_key_pressed("space"))         # (stays visible for the whole step)
        self.input.end_fixed_step()
        self.assertFalse(Input.is_key_pressed("space"))        # consumed: a second step in the same frame won't see it
        Time.in_fixed_step = False

    def test_fixed_update_hook_receives_the_press_once_through_the_real_loop(self):
        seen = []

        class Probe(Component):
            def fixed_update(self, dt):
                if Input.is_key_pressed("space"):
                    seen.append(1)
        scene = Scene()
        go = GameObject()
        go.add_component(Probe())
        scene.add_game_object(go)
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYDOWN, pygame.K_SPACE))
        scene.tick(0.1)                                        # six fixed steps in one frame
        self.assertEqual(len(seen), 1)

    def test_window_focus_loss_releases_held_keys(self):
        if not hasattr(pygame, "WINDOWFOCUSLOST"):
            self.skipTest("pygame too old")
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYDOWN, pygame.K_d))
        self.new_frame()
        self.input.process_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertFalse(Input.is_key_down("d"))
        self.assertTrue(Input.is_key_up("d"))

    def test_legacy_names_and_axis_helper(self):
        self.new_frame()
        self.input.process_event(key_event(pygame.KEYDOWN, pygame.K_d))
        self.assertTrue(Input.is_pressed(Key.D))
        self.assertTrue(Input.is_just_pressed("d"))
        self.assertEqual(Input.get_axis("a", "d"), 1)
        self.input.inject_key("a", True)
        self.assertEqual(Input.get_axis("a", "d"), 0)


# ==========================================================================================
# 5. Canvas / UI
# ==========================================================================================

def ui_go(scene, component, x=0, y=0, parent=None, name="ui"):
    go = GameObject(x, y, name=name)
    go.add_component(component)
    if parent is not None:
        go.set_parent(parent)
    scene.add_game_object(go)
    return go


class TestUI(EngineTestCase):
    def test_anchor_names_are_forgiving_and_validated(self):
        for spelling in ("BottomRight", "bottom_right", "bottomright", "BOTTOM-RIGHT"):
            self.assertEqual(UIPanel(anchor=spelling).anchor, "bottomright")
        self.assertEqual(UIPanel(anchor="TopCenter").anchor, "midtop")
        self.assertEqual(UIPanel(anchor="Center").anchor, "center")
        with self.assertRaises(ValueError):
            UIPanel(anchor="nowhere")

    def test_anchored_elements_hug_the_screen_edges(self):
        scene = Scene()
        go = ui_go(scene, UIPanel(100, 40, anchor="BottomRight"), x=-10, y=-10)
        rect = go.get_component(UIPanel).rect
        self.assertEqual(rect.bottomright, (630, 470))
        go = ui_go(scene, UIPanel(300, 200, anchor="Center"))
        self.assertEqual(go.get_component(UIPanel).rect.center, (320, 240))
        go = ui_go(scene, UIPanel(100, 40, anchor="TopLeft"), x=8, y=8)
        self.assertEqual(go.get_component(UIPanel).rect.topleft, (8, 8))
        go = ui_go(scene, UIPanel(100, 50, anchor="TopRight", pivot="TopLeft"))
        self.assertEqual(go.get_component(UIPanel).rect.topleft, (640, 0))       # pivot moves the pinned point

    def test_children_anchor_to_their_parent_panel(self):
        scene = Scene()
        panel = ui_go(scene, UIPanel(200, 100), x=100, y=50, name="panel")
        label = ui_go(scene, UIPanel(40, 20, anchor="BottomRight"), x=-5, y=-5, parent=panel, name="child")
        self.assertEqual(label.get_component(UIPanel).rect.bottomright, (295, 145))
        legacy = ui_go(scene, UIPanel(10, 10), x=10, y=20, parent=panel, name="legacy")
        self.assertEqual(legacy.get_component(UIPanel).rect.topleft, (110, 70))   # hierarchy composes offsets
        centered = ui_go(scene, UIPanel(60, 20, anchor="Center"), parent=panel, name="centered")
        self.assertEqual(centered.get_component(UIPanel).rect.center, (200, 100))

    def test_visibility_cascades_to_children(self):
        scene = Scene()
        panel = ui_go(scene, UIPanel(100, 100), name="panel")
        child = ui_go(scene, UIPanel(50, 50, style=None), parent=panel, name="child")
        child_panel = child.get_component(UIPanel)
        self.assertTrue(child_panel.is_visible)
        panel.get_component(UIPanel).visible = False
        self.assertFalse(child_panel.is_visible)
        self.assertEqual(pixels(render(scene)), pixels(render(Scene())))      # nothing drawn at all

    def test_hud_ignores_the_camera_and_draws_over_the_world(self):
        def build(with_camera):
            scene = Scene()
            sprite_go(scene, 0, 0, 640, 480, (0, 0, 200), "backdrop", z=100)
            ui_go(scene, UIPanel(60, 30, anchor="TopLeft"), x=10, y=10)
            if with_camera:
                target = GameObject(5000, 5000)
                scene.add_game_object(target)
                cam = target.add_component(Camera(target=target))
                scene.set_active_camera(cam)
            return scene
        plain, scrolled = render(build(False)), render(build(True))
        self.assertEqual(plain.get_at((20, 20))[:3], UIPanel().style.background_color)   # UI on top of a huge sprite
        self.assertEqual(scrolled.get_at((20, 20))[:3], UIPanel().style.background_color)  # ...and unmoved by the camera
        self.assertEqual(scrolled.get_at((300, 300))[:3], BG)                            # while the world scrolled away

    def test_world_space_health_bar_follows_its_parent_through_the_camera(self):
        scene = Scene()
        player = GameObject(420, 290, name="player")            # camera centers here -> world offset (100, 50)
        scene.add_game_object(player)
        cam = player.add_component(Camera(target=player, smooth_follow=False))
        scene.set_active_camera(cam)
        enemy = GameObject(300, 200, name="enemy")
        scene.add_game_object(enemy)
        bar_go = GameObject(0, -30, parent=enemy, name="bar")
        bar = bar_go.add_component(UIHealthBar(40, 8, world_space=True, pivot="Center", border_width=0,
                                               fill_color=(0, 255, 0)))
        surface = render(scene)
        self.assertEqual(surface.get_at((200, 120))[:3], (0, 255, 0))          # world (300,170) - offset (100,50)
        enemy.transform.position.x += 50
        self.assertEqual(render(scene).get_at((250, 120))[:3], (0, 255, 0))    # moved with its parent
        self.assertEqual(render(scene).get_at((200, 120))[:3], BG)

    def test_health_bar_value_ratio_colors_and_binding(self):
        bar = UIHealthBar(100, 10, max_value=50, value=999, border_width=0,
                          fill_color=(0, 200, 0), low_color=(200, 0, 0), low_threshold=0.3, anchor="TopLeft")
        self.assertEqual((bar.value, bar.ratio), (50.0, 1.0))
        bar.value = -5
        self.assertEqual(bar.value, 0.0)
        scene = Scene()
        go = ui_go(scene, bar)
        bar.value = 40
        self.assertEqual(render(scene).get_at((5, 5))[:3], (0, 200, 0))
        bar.value = 10                                          # 20% <= 30% threshold
        self.assertEqual(render(scene).get_at((5, 5))[:3], (200, 0, 0))
        hp = {"v": 25.0}
        bar.bind(lambda: hp["v"])
        scene.update(DT)
        self.assertEqual(bar.value, 25.0)
        bar.set_max_value(100, keep_ratio=True)
        self.assertAlmostEqual(bar.ratio, 0.5)

    def test_health_bar_smoothing_and_damage_trail(self):
        bar = UIHealthBar(100, 10, max_value=100, smooth_speed=2.0, trail_color=(255, 255, 0))
        bar.value = 0
        self.assertEqual(bar.displayed_ratio, 1.0)              # glides instead of jumping
        bar.update(0.25)
        self.assertAlmostEqual(bar.displayed_ratio, 0.5)
        bar.update(1.0)
        self.assertEqual(bar.displayed_ratio, 0.0)
        self.assertGreater(bar._trail, 0.0)                     # the "recently lost" chip lags behind

    def test_button_click_press_release_and_cancel(self):
        scene = Scene()
        button = UIButton("Go", width=100, height=40, anchor="TopLeft")
        ui_go(scene, button, x=50, y=50)
        clicks = []
        button.on_click.append(lambda b: clicks.append("click"))
        inp = Input.instance()

        def frame(down=None, pos=None):
            inp.begin_frame()
            if pos is not None:
                inp.inject_mouse_position(*pos)
            if down is not None:
                inp.inject_key("mouse_left", down)
            scene.update(DT)

        frame(pos=(60, 60))
        self.assertTrue(button.is_hovered)
        frame(down=True)
        self.assertTrue(button.is_pressed)
        frame(down=False)
        self.assertEqual(clicks, ["click"])                     # press + release over the button = click
        frame(down=True)
        frame(down=False, pos=(500, 400))                       # released elsewhere: cancelled
        self.assertEqual(clicks, ["click"])

    def test_hidden_buttons_cannot_be_clicked(self):
        scene = Scene()
        panel = ui_go(scene, UIPanel(300, 300), name="menu")
        button = UIButton("X", 100, 40)
        ui_go(scene, button, x=10, y=10, parent=panel)
        clicks = []
        button.on_click.append(lambda b: clicks.append(1))
        panel.get_component(UIPanel).visible = False
        inp = Input.instance()
        inp.begin_frame()
        inp.inject_mouse_position(20, 20)
        inp.inject_key("mouse_left", True)
        scene.update(DT)
        inp.begin_frame()
        inp.inject_key("mouse_left", False)
        scene.update(DT)
        self.assertEqual(clicks, [])

    def test_canvas_groups_and_hides_a_ui_tree(self):
        scene = Scene()
        root = ui_go(scene, Canvas(), name="pause_menu")
        canvas = root.get_component(Canvas)
        self.assertEqual(canvas.rect, pygame.Rect(0, 0, 640, 480))
        text = ui_go(scene, UIText("Paused", anchor="Center"), parent=root, name="label")
        rect = text.get_component(UIText).rect
        self.assertLessEqual(abs(rect.centerx - 320), 1)
        self.assertLessEqual(abs(rect.centery - 240), 1)
        canvas.visible = False
        self.assertFalse(text.get_component(UIText).is_visible)

    def test_text_is_cached_and_autosizes(self):
        font = UIText("x")._font
        self.assertIs(render_text(font, "hello", (1, 2, 3)), render_text(font, "hello", (1, 2, 3)))
        self.assertIsNot(render_text(font, "hello", (1, 2, 3)), render_text(font, "hello", (9, 2, 3)))
        label = UIText("hi")
        narrow = label.width
        label.text = "a much longer label"
        self.assertGreater(label.width, narrow)                 # measured width follows the text
        fixed = UIText("hi", width=200)
        fixed.text = "a much longer label"
        self.assertEqual(fixed.width, 200)                      # explicit width is respected


# ==========================================================================================
# 6. Audio
# ==========================================================================================

def make_wav(path, seconds=2.0, freq=440.0, rate=22050):
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
                          for i in range(int(rate * seconds)))
        f.writeframes(frames)


class ChannelSpy:
    """Wraps a mixer Channel and records set_volume() calls. (pygame's two-argument
    set_volume(left, right) applies stereo gains that get_volume() can't read back.)"""

    def __init__(self, channel):
        self._channel = channel
        self.volumes = []

    def set_volume(self, *args):
        self.volumes.append(args)
        return self._channel.set_volume(*args)

    def __getattr__(self, name):
        return getattr(self._channel, name)


class TestAudio(EngineTestCase):
    def setUp(self):
        super().setUp()
        if not AudioManager.init():
            self.skipTest("no audio device (even the dummy driver) available")
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.sfx = os.path.join(self.dir.name, "sfx.wav")
        self.music_a = os.path.join(self.dir.name, "a.wav")
        self.music_b = os.path.join(self.dir.name, "b.wav")
        make_wav(self.sfx, 2.0)
        make_wav(self.music_a, 4.0, 220)
        make_wav(self.music_b, 4.0, 330)
        AudioManager.set_master_volume(1.0)
        AudioManager.set_sfx_volume(1.0)
        AudioManager.set_music_volume(1.0)
        AudioManager.unmute()
        AudioManager.listener = None

    def tearDown(self):
        AudioManager.listener = None
        AudioManager.set_master_volume(1.0)
        AudioManager.set_sfx_volume(1.0)
        AudioManager.set_music_volume(1.0)
        AudioManager.unmute()
        super().tearDown()

    def test_attenuation_pan_and_stereo_math(self):
        att = AudioManager.compute_attenuation
        self.assertEqual(att(50, 100, 500), 1.0)
        self.assertEqual(att(100, 100, 500), 1.0)
        self.assertAlmostEqual(att(300, 100, 500), 0.5)
        self.assertEqual(att(500, 100, 500), 0.0)
        self.assertEqual(att(900, 100, 500), 0.0)
        self.assertAlmostEqual(att(200, 100, 500, "inverse"), (100 / 200) * (1 - 0.25))
        self.assertEqual(AudioManager.compute_pan(0, 800), 0.0)
        self.assertEqual(AudioManager.compute_pan(400, 800), 1.0)
        self.assertEqual(AudioManager.compute_pan(-9999, 800), -1.0)
        self.assertEqual(AudioManager.stereo_volumes(1.0, 0.0), (1.0, 1.0))
        self.assertEqual(AudioManager.stereo_volumes(1.0, 1.0), (0.0, 1.0))
        self.assertEqual(AudioManager.stereo_volumes(0.8, -0.5), (0.8, 0.4))

    def test_volume_sliders_clamp_combine_and_mute(self):
        AudioManager.set_master_volume(5)
        self.assertEqual(AudioManager.get_master_volume(), 1.0)
        AudioManager.set_sfx_volume(-1)
        self.assertEqual(AudioManager.get_sfx_volume(), 0.0)
        AudioManager.set_master_volume(0.5)
        AudioManager.set_sfx_volume(0.5)
        AudioManager.set_music_volume(0.8)
        self.assertAlmostEqual(AudioManager._sfx_gain(), 0.25)
        self.assertAlmostEqual(AudioManager._music_gain(), 0.4)
        AudioManager.mute()
        self.assertEqual(AudioManager._sfx_gain(), 0.0)
        AudioManager.toggle_mute()
        self.assertFalse(AudioManager.is_muted())

    def test_sfx_plays_and_sliders_reach_sounds_already_playing(self):
        handle = AudioManager.play_sfx(self.sfx, volume=0.5)
        self.assertTrue(handle.is_playing)
        handle.channel = spy = ChannelSpy(handle.channel)
        AudioManager.update(DT)
        self.assertEqual(spy.volumes[-1], (0.5, 0.5))
        AudioManager.set_sfx_volume(0.0)
        AudioManager.update(DT)
        self.assertEqual(spy.volumes[-1], (0.0, 0.0))
        AudioManager.set_sfx_volume(1.0)
        AudioManager.set_master_volume(0.5)
        AudioManager.update(DT)
        self.assertEqual(spy.volumes[-1], (0.25, 0.25))
        AudioManager.mute()
        AudioManager.update(DT)
        self.assertEqual(spy.volumes[-1], (0.0, 0.0))
        handle.stop()
        self.assertFalse(handle.is_playing)

    def test_positional_sfx_attenuates_pans_and_culls_out_of_earshot(self):
        AudioManager.listener = (0, 0)
        near = AudioManager.play_sfx(self.sfx, position=(0, 0), min_distance=100, max_distance=800)
        self.assertEqual(AudioManager._handle_volumes(near), (1.0, 1.0))
        right = AudioManager.play_sfx(self.sfx, position=(300, 0), min_distance=100, max_distance=800)
        left_vol, right_vol = AudioManager._handle_volumes(right)
        self.assertGreater(right_vol, left_vol)
        self.assertAlmostEqual(right_vol, 1.0 - 200 / 700)
        self.assertIsNone(AudioManager.play_sfx(self.sfx, position=(900, 0), max_distance=800))
        listener_go = GameObject(300, 0)
        AudioManager.listener = listener_go                     # listener can be a GameObject
        self.assertEqual(AudioManager._handle_volumes(right)[0], AudioManager._handle_volumes(right)[1])

    def test_music_fade_in_and_fade_out_are_ramped_by_update(self):
        self.assertTrue(AudioManager.play_music(self.music_a, fade_in=1.0))
        self.assertEqual(AudioManager.music_level(), 0.0)
        self.assertEqual(AudioManager.current_music(), self.music_a)
        AudioManager.update(0.5)
        self.assertAlmostEqual(AudioManager.music_level(), 0.5)
        AudioManager.update(0.6)
        self.assertEqual(AudioManager.music_level(), 1.0)
        AudioManager.stop_music(fade_out=1.0)
        AudioManager.update(0.5)
        self.assertAlmostEqual(AudioManager._decks[0].volume, 0.5)
        AudioManager.update(0.6)
        self.assertFalse(AudioManager.is_music_playing())
        self.assertIsNone(AudioManager.current_music())

    def test_crossfade_overlaps_two_tracks(self):
        AudioManager.play_music(self.music_a)
        AudioManager.crossfade_to(self.music_b, duration=2.0)
        AudioManager.update(1.0)
        levels = sorted(d.volume for d in AudioManager._decks)
        self.assertAlmostEqual(levels[0], 0.5)
        self.assertAlmostEqual(levels[1], 0.5)
        self.assertTrue(all(d.channel.get_busy() for d in AudioManager._decks))   # both audible at once
        AudioManager.update(1.1)
        self.assertEqual(AudioManager.current_music(), self.music_b)
        self.assertEqual(AudioManager.music_level(), 1.0)
        self.assertEqual(sum(1 for d in AudioManager._decks if d.sound is not None), 1)

    def test_music_and_sfx_have_separate_channels(self):
        AudioManager.play_music(self.music_a)
        handles = [AudioManager.play_sfx(self.sfx) for _ in range(45)]
        playing = [h for h in handles if h is not None]
        self.assertEqual(len(playing), AudioManager.NUM_CHANNELS - AudioManager.RESERVED_CHANNELS)
        self.assertTrue(AudioManager._decks[0].channel.get_busy())               # music survived the SFX flood
        self.assertEqual(AudioManager.current_music(), self.music_a)
        AudioManager.stop_all_sfx()
        self.assertTrue(AudioManager.is_music_playing())

    def test_pause_and_resume_music_and_music_volume_slider(self):
        AudioManager.play_music(self.music_a)
        AudioManager.set_music_volume(0.5)
        AudioManager.update(DT)
        self.assertAlmostEqual(AudioManager._decks[0].channel.get_volume(), 0.5, places=2)
        AudioManager.pause_music()
        self.assertTrue(AudioManager._decks[0].paused)
        AudioManager.update(DT)
        self.assertIsNotNone(AudioManager.current_music())                        # a paused track isn't released
        AudioManager.resume_music()
        self.assertFalse(AudioManager._decks[0].paused)

    def test_missing_files_are_logged_never_raised(self):
        self.assertIsNone(AudioManager.load_sound("definitely/not/here.wav"))
        self.assertFalse(AudioManager.play_music("definitely/not/here.ogg"))
        self.assertIsNone(AudioManager.play_sfx("definitely/not/here.wav"))
        AudioSource("definitely/not/here.wav")
        self.assertGreaterEqual(len(self.messages("ERROR")), 3)

    def test_audio_source_follows_its_object_and_cleans_up(self):
        AudioManager.listener = (0, 0)
        scene = Scene()
        go = GameObject(0, 0)
        source = go.add_component(AudioSource(self.sfx, spatial=True, min_distance=100, max_distance=800, loop=True))
        scene.add_game_object(go)
        source.play()
        self.assertTrue(source.is_playing)
        near = AudioManager._handle_volumes(source._handle)[1]
        go.transform.position.x = 600
        scene.update(DT)
        self.assertLess(AudioManager._handle_volumes(source._handle)[0], near)       # got quieter as it moved away
        go.destroy()
        self.assertFalse(source.is_playing)
        self.assertEqual(AudioManager.active_sfx_count(), 0)

    def test_audio_source_without_a_sound_warns(self):
        source = AudioSource()
        source.play()
        self.assertTrue(any("no sound loaded" in m for m in self.messages("WARNING")))

    def test_settings_round_trip_through_player_prefs(self):
        with tempfile.TemporaryDirectory() as tmp:
            PlayerPrefs.set_path(os.path.join(tmp, "prefs.json"))
            try:
                AudioManager.set_master_volume(0.3)
                AudioManager.set_sfx_volume(0.6)
                AudioManager.set_music_volume(0.9)
                AudioManager.save_settings()
                PlayerPrefs.save()
                AudioManager.set_master_volume(1.0)
                AudioManager.set_sfx_volume(1.0)
                AudioManager.set_music_volume(1.0)
                PlayerPrefs.reload()
                AudioManager.load_settings()
                self.assertEqual((AudioManager.get_master_volume(), AudioManager.get_sfx_volume(),
                                  AudioManager.get_music_volume()), (0.3, 0.6, 0.9))
            finally:
                PlayerPrefs.set_path(PlayerPrefs.DEFAULT_PATH)


# ==========================================================================================
# 7. Debug tools
# ==========================================================================================

class TestDebug(EngineTestCase):
    def press(self, *keys):
        inp = Input.instance()
        inp.begin_frame()
        for key in keys:
            inp.inject_key(key, True)
        self.debug.handle_input()
        for key in keys:
            inp.inject_key(key, False)

    def test_unity_style_logging_api(self):
        Debug.log("hello")
        Debug.log_warning("careful")
        Debug.log_error("bad")
        self.assertIs(Debug, DebugManager)
        self.assertEqual([(e.level, e.message) for e in self.debug.logs],
                         [("INFO", "hello"), ("WARNING", "careful"), ("ERROR", "bad")])
        self.assertEqual(list(self.debug.logs)[1].format(), "[WARNING] careful")
        Debug.log_error("with source", source="Physics")
        self.assertEqual(list(self.debug.logs)[-1].format(), "[ERROR][Physics] with source")
        try:
            raise ValueError("boom")
        except ValueError as exc:
            Debug.log_exception(exc)
        self.assertEqual(list(self.debug.logs)[-1].message, "ValueError: boom")
        Debug.clear_logs()
        self.assertEqual(len(self.debug.logs), 0)

    def test_function_keys_toggle_each_overlay(self):
        d = self.debug
        for key, attr in (("f1", "show_overlay"), ("f2", "show_colliders"), ("f3", "show_grid"), ("f4", "show_console")):
            self.assertFalse(getattr(d, attr))
            self.press(key)
            self.assertTrue(getattr(d, attr), key)
            Input.instance().begin_frame()
            d.handle_input()
            self.assertTrue(getattr(d, attr), "must not re-toggle without a new press")
            self.press(key)
            self.assertFalse(getattr(d, attr), key)

    def test_hotkeys_are_configurable_and_can_be_disabled(self):
        self.debug.keys["stats"] = "f9"
        self.press("f1")
        self.assertFalse(self.debug.show_overlay)
        self.press("f9")
        self.assertTrue(self.debug.show_overlay)
        self.debug.show_overlay = False
        self.debug.enabled = False
        self.press("f9")
        self.assertFalse(self.debug.show_overlay)
        surface = pygame.Surface((320, 240))
        self.debug.show_grid = self.debug.show_console = self.debug.show_colliders = True
        self.debug.draw_grid(surface)
        self.debug.draw_console(surface)
        self.debug.draw_colliders(surface, Scene())
        self.assertEqual(pixels(surface), pixels(pygame.Surface((320, 240))))     # disabled = draws nothing

    def test_stats_overlay_reports_fps_entities_and_draw_calls(self):
        scene = Scene("stats")
        sprite_go(scene, 10, 10, 8, 8, (1, 2, 3))
        sprite_go(scene, 30, 10, 8, 8, (1, 2, 3))
        render(scene)
        for _ in range(40):
            self.debug.update(1 / 60)
        self.assertAlmostEqual(self.debug.fps, 60.0, delta=1.0)
        self.assertAlmostEqual(self.debug.frame_ms, 16.67, delta=0.5)
        text = "\n".join(self.debug._stat_lines(scene))
        self.assertIn("FPS:", text)
        self.assertIn("Entities: 2/2", text)
        self.assertIn("Draw calls: 2", text)
        self.assertIn("Physics:", text)
        self.debug.show_overlay = True
        surface = pygame.Surface((640, 480))
        surface.fill(BG)
        self.debug.draw_overlay(surface, scene)
        self.assertNotEqual(surface.get_at((20, 20))[:3], BG)                     # panel is drawn top-left
        self.assertEqual(surface.get_at((600, 400))[:3], BG)
        self.debug.set_stat("custom", 42)
        self.assertIn("custom: 42", "\n".join(self.debug._stat_lines(scene)))

    def test_gizmos_outline_colliders_by_kind(self):
        scene = Scene()
        add_box(scene, 100, 100, 50, 50, name="wall", static=True, sprite=False)                 # blue
        add_box(scene, 300, 100, 50, 50, name="zone", trigger=True, sprite=False, static=True)   # red
        add_box(scene, 100, 300, 50, 50, name="crate", sprite=False)                             # green
        self.debug.show_colliders = True
        surface = pygame.Surface((640, 480))
        surface.fill(BG)
        self.debug.draw_colliders(surface, scene)
        self.assertEqual(surface.get_at((101, 125))[:3], (90, 150, 255))
        self.assertEqual(surface.get_at((301, 125))[:3], (255, 90, 90))
        self.assertEqual(surface.get_at((101, 325))[:3], (90, 255, 120))
        self.assertEqual(surface.get_at((125, 125))[:3], BG)                                     # hollow

    def test_grid_draws_labelled_axes_through_the_origin(self):
        self.debug.show_grid = True
        surface = pygame.Surface((640, 480))
        surface.fill(BG)
        self.debug.draw_grid(surface)
        self.assertEqual(surface.get_at((300, 0))[:3], (230, 100, 100))            # y = 0 axis
        self.assertEqual(surface.get_at((0, 250))[:3], (230, 100, 100))            # x = 0 axis (250: between grid rows)
        self.assertEqual(surface.get_at((250, 100))[:3], (70, 70, 80))            # an ordinary 100px grid line

    def test_console_shows_recent_logs_and_scrolls(self):
        for i in range(40):
            Debug.log(f"line {i}")
        self.debug.show_console = True
        surface = pygame.Surface((640, 480))
        surface.fill(BG)
        self.debug.draw_console(surface)
        first = pixels(surface)
        self.assertNotEqual(first, pixels(pygame.Surface((640, 480))))
        self.assertEqual(surface.get_at((320, 5))[:3], BG)                          # anchored bottom-left
        self.debug.scroll_console(10)
        self.assertEqual(self.debug._console_scroll, 10)
        self.debug.scroll_console(10_000)
        self.assertEqual(self.debug._console_scroll, len(self.debug.logs) - self.debug.console_lines)
        self.debug.scroll_console(-10_000)
        self.assertEqual(self.debug._console_scroll, 0)
        surface2 = pygame.Surface((640, 480))
        surface2.fill(BG)
        self.debug.scroll_console(5)
        self.debug.draw_console(surface2)
        self.assertNotEqual(pixels(surface2), first)                                # different window of the log


# ==========================================================================================
# 8. Event bus
# ==========================================================================================

class TestEventBus(EngineTestCase):
    def test_global_publish_subscribe(self):
        got = []
        EventBus.subscribe("game_over", lambda score=0: got.append(score))
        self.assertEqual(EventBus.emit("game_over", score=120), 1)
        self.assertEqual(EventBus.emit("game_over", 7), 1)
        self.assertEqual(got, [120, 7])
        self.assertEqual(EventBus.emit("nobody_listens"), 0)

    def test_priority_order_and_once_and_unsubscribe(self):
        order = []
        low = lambda: order.append("low")
        EventBus.subscribe("e", low, priority=-5)
        EventBus.subscribe("e", lambda: order.append("first"), priority=5)
        EventBus.subscribe("e", lambda: order.append("mid"))
        EventBus.once("e", lambda: order.append("once"))
        EventBus.emit("e")
        self.assertEqual(order, ["first", "mid", "once", "low"])
        order.clear()
        EventBus.emit("e")
        self.assertEqual(order, ["first", "mid", "low"])
        self.assertEqual(EventBus.unsubscribe("e", low), 1)
        order.clear()
        EventBus.emit("e")
        self.assertEqual(order, ["first", "mid"])

    def test_handlers_may_unsubscribe_and_resubscribe_while_emitting(self):
        calls = []
        subs = []

        def selfish():
            calls.append("selfish")
            subs[0].cancel()
            EventBus.subscribe("e", lambda: calls.append("added"))
        subs.append(EventBus.subscribe("e", selfish))
        EventBus.emit("e")
        EventBus.emit("e")
        self.assertEqual(calls, ["selfish", "added"])

    def test_a_raising_handler_is_logged_and_does_not_stop_the_others(self):
        ran = []
        EventBus.subscribe("e", lambda: 1 / 0)
        EventBus.subscribe("e", lambda: ran.append("second"))
        self.assertEqual(EventBus.emit("e"), 2)
        self.assertEqual(ran, ["second"])
        self.assertTrue(any("ZeroDivisionError" in m for m in self.messages("ERROR")))

    def test_owner_tagging_drops_all_of_an_owners_subscriptions(self):
        owner, other = object(), object()
        hits = []
        EventBus.subscribe("a", lambda: hits.append("a1"), owner=owner)
        EventBus.subscribe("b", lambda: hits.append("b1"), owner=owner)
        EventBus.subscribe("a", lambda: hits.append("a2"), owner=other)
        self.assertEqual(EventBus.unsubscribe_owner(owner), 2)
        EventBus.emit("a")
        EventBus.emit("b")
        self.assertEqual(hits, ["a2"])

    def test_weak_subscriptions_do_not_keep_listeners_alive(self):
        import gc

        class Listener:
            def __init__(self):
                self.hits = 0

            def on_event(self):
                self.hits += 1
        listener = Listener()
        EventBus.subscribe("e", listener.on_event, weak=True)
        EventBus.emit("e")
        self.assertEqual(listener.hits, 1)
        del listener
        gc.collect()
        self.assertEqual(EventBus.emit("e"), 0)
        self.assertEqual(EventBus.listener_count("e"), 0)         # pruned on emit

    def test_entity_scoped_events_are_isolated(self):
        a, b = GameObject(name="a"), GameObject(name="b")
        got = []
        a.events.subscribe("hit", lambda dmg: got.append(("a", dmg)))
        b.events.subscribe("hit", lambda dmg: got.append(("b", dmg)))
        EventBus.subscribe("hit", lambda dmg: got.append(("global", dmg)))
        a.events.emit("hit", 5)
        self.assertEqual(got, [("a", 5)])                         # neither b nor the global bus heard it
        EventBus.emit("hit", 9)
        self.assertEqual(got, [("a", 5), ("global", 9)])
        self.assertIsNot(a.events, b.events)
        self.assertIs(a.add_component(Recorder()).events, a.events)

    def test_destroying_an_entity_clears_its_subscriptions(self):
        scene = Scene()
        go = GameObject(name="mob")
        comp = go.add_component(Recorder())
        scene.add_game_object(go)
        hits = []
        go.events.subscribe("x", lambda: hits.append("entity"))
        EventBus.subscribe("y", lambda: hits.append("global"), owner=comp)
        go.destroy()
        go.events.emit("x")
        EventBus.emit("y")
        self.assertEqual(hits, [])

    def test_player_controller_emits_jump_charge_events(self):
        scene = Scene()
        add_box(scene, 0, 300, 600, 20, static=True, sprite=False)
        player = add_box(scene, 50, 250, 20, 30, name="player", body=True, sprite=False)
        controller = player.add_component(PlayerController(movement_type="platformer", max_jumps=2))
        controller.start()
        seen = []
        player.events.subscribe("jumps_changed", lambda remaining, maximum: seen.append(remaining))
        player.events.subscribe("landed", lambda: seen.append("landed"))
        inp = Input.instance()
        for _ in range(30):
            inp.begin_frame()
            scene.tick(DT)
        inp.begin_frame()
        inp.inject_key("space", True)
        scene.tick(DT)
        self.assertEqual(seen[-1], 1)                             # one jump charge left after the first jump
        inp.inject_key("space", False)
        for _ in range(120):
            inp.begin_frame()
            scene.tick(DT)
        self.assertEqual(seen[-2:], ["landed", 2])                # landing refills both charges


# ==========================================================================================
# 9. Object pooling
# ==========================================================================================

class Bullet:
    made = 0

    def __init__(self):
        Bullet.made += 1
        self.alive = False
        self.pos = (0, 0)


class TestObjectPool(EngineTestCase):
    def test_instances_are_reused_not_recreated(self):
        Bullet.made = 0
        pool = ObjectPool(Bullet, on_spawn=lambda b, x, y: setattr(b, "pos", (x, y)),
                          on_despawn=lambda b: setattr(b, "alive", False), initial_size=4)
        self.assertEqual((pool.free_count, pool.total_created), (4, 4))
        first = pool.spawn(1, 2)
        self.assertEqual(first.pos, (1, 2))
        self.assertEqual(pool.active_count, 1)
        pool.despawn(first)
        for _ in range(100):
            bullet = pool.spawn(0, 0)
            pool.despawn(bullet)
        self.assertEqual(Bullet.made, 4)                          # a hundred spawns, zero new allocations
        self.assertEqual(pool.free_count, 4)

    def test_max_size_refuses_extra_spawns_and_double_despawn_warns(self):
        pool = ObjectPool(Bullet, max_size=2)
        a, b = pool.spawn(), pool.spawn()
        self.assertIsNone(pool.spawn())
        self.assertEqual(pool.dropped, 1)
        self.assertTrue(pool.despawn(a))
        self.assertFalse(pool.despawn(a))
        self.assertTrue(any("isn't active" in m for m in self.messages("WARNING")))
        self.assertIsNotNone(pool.spawn())
        pool.despawn_all()
        self.assertEqual(pool.active_count, 0)

    def test_game_object_pool_toggles_activity_instead_of_churning_the_scene(self):
        scene = Scene()

        def make_bullet():
            go = GameObject(name="bullet")
            go.add_component(SpriteRenderer(sprite=make_surface(4, 4, (255, 255, 0))))
            go.add_component(Recorder())
            go.add_component(Rigidbody2D(use_gravity=False))
            return go
        pool = GameObjectPool(scene, make_bullet, initial_size=3)
        self.assertEqual(len(scene.game_objects), 3)
        self.assertEqual(scene.active_entity_count, 0)            # idle pool members are inactive
        self.assertEqual(scene.render_system.stats.dynamic_registered, 0)

        shot = pool.spawn(x=100, y=50)
        self.assertTrue(shot.active)
        self.assertEqual(shot.transform.get_world_xy(), (100, 50))
        self.assertEqual(scene.render_system.stats.dynamic_registered, 1)
        shot.get_component(Rigidbody2D).velocity.x = 300
        run(scene, 0.2)
        self.assertGreater(shot.transform.world_x, 100)
        recorder = shot.get_component(Recorder)
        ticks = recorder.updates

        shot.despawn()                                            # GameObject.despawn() -> its pool
        self.assertFalse(shot.active)
        self.assertEqual(shot.get_component(Rigidbody2D).velocity.x, 0)   # component reset hook ran
        run(scene, 0.2)
        self.assertEqual(recorder.updates, ticks)                 # idle: skipped by update
        self.assertEqual(scene.render_system.stats.dynamic_registered, 0)
        self.assertEqual(len(scene.game_objects), 3)              # never left the scene

        again = pool.spawn(x=5, y=5)
        self.assertIs(again, shot)                                # recycled
        self.assertEqual(again.transform.get_render_xy(0.5), (5, 5))    # no interpolation smear from its old spot
        self.assertEqual(again.get_component(Rigidbody2D).velocity.x, 0)

    def test_destroying_a_pooled_object_removes_it_from_the_pool(self):
        scene = Scene()
        pool = GameObjectPool(scene, lambda: GameObject(name="p"), initial_size=2)
        go = pool.spawn()
        go.destroy()
        self.assertEqual((pool.active_count, pool.free_count), (0, 1))

    def test_pool_hooks_reach_component_on_spawn_with_kwargs(self):
        scene = Scene()
        seen = []

        class Enemy(Component):
            def on_spawn(self, hp=0):
                seen.append(hp)
        pool = GameObjectPool(scene, lambda: _with(GameObject(), Enemy()), initial_size=1)
        pool.spawn(x=1, y=1, hp=30)
        self.assertEqual(seen, [30])


def _with(go, component):
    go.add_component(component)
    return go


# ==========================================================================================
# 10. PlayerPrefs
# ==========================================================================================

class TestPlayerPrefs(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "saves", "prefs.json")
        PlayerPrefs.set_path(self.path)

    def tearDown(self):
        PlayerPrefs.set_path(PlayerPrefs.DEFAULT_PATH)
        super().tearDown()

    def test_typed_values_round_trip_through_the_file(self):
        PlayerPrefs.set_int("score", 4200)
        PlayerPrefs.set_float("volume", 0.75)
        PlayerPrefs.set_string("name", "Georgii")
        self.assertTrue(PlayerPrefs.is_dirty())
        self.assertFalse(os.path.exists(self.path))                # nothing hits the disk until save()
        self.assertTrue(PlayerPrefs.save())
        self.assertFalse(PlayerPrefs.is_dirty())
        PlayerPrefs.set_path(self.path)                            # forget memory, reload from disk
        self.assertEqual(PlayerPrefs.get_int("score"), 4200)
        self.assertEqual(PlayerPrefs.get_float("volume"), 0.75)
        self.assertEqual(PlayerPrefs.get_string("name"), "Georgii")
        self.assertTrue(PlayerPrefs.has_key("score"))

    def test_defaults_and_type_mismatches(self):
        self.assertEqual(PlayerPrefs.get_int("missing"), 0)
        self.assertEqual(PlayerPrefs.get_int("missing", 7), 7)
        self.assertEqual(PlayerPrefs.get_float("missing", 1.5), 1.5)
        self.assertEqual(PlayerPrefs.get_string("missing", "dflt"), "dflt")
        PlayerPrefs.set_string("k", "text")
        self.assertEqual(PlayerPrefs.get_int("k", -1), -1)          # wrong type -> default, like Unity
        PlayerPrefs.set_int("n", 3)
        self.assertEqual(PlayerPrefs.get_float("n"), 3.0)           # ints widen to float
        PlayerPrefs.set_float("f", 3.5)
        self.assertEqual(PlayerPrefs.get_int("f", -1), -1)          # but floats don't narrow

    def test_input_validation(self):
        for call, arg in ((PlayerPrefs.set_int, 3.5), (PlayerPrefs.set_int, "3"), (PlayerPrefs.set_float, "x"),
                          (PlayerPrefs.set_string, 5)):
            with self.assertRaises(TypeError):
                call("k", arg)
        with self.assertRaises(ValueError):
            PlayerPrefs.set_float("k", float("nan"))
        with self.assertRaises(TypeError):
            PlayerPrefs.set_int("", 1)

    def test_delete_and_dirty_tracking(self):
        PlayerPrefs.set_int("a", 1)
        PlayerPrefs.set_int("b", 2)
        PlayerPrefs.save()
        PlayerPrefs.set_int("a", 1)                                # same value: not a change
        self.assertFalse(PlayerPrefs.is_dirty())
        PlayerPrefs.delete_key("a")
        self.assertFalse(PlayerPrefs.has_key("a"))
        self.assertTrue(PlayerPrefs.is_dirty())
        PlayerPrefs.delete_all()
        self.assertFalse(PlayerPrefs.has_key("b"))

    def test_save_is_atomic_and_creates_directories(self):
        PlayerPrefs.set_int("x", 1)
        PlayerPrefs.save()
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["prefs.json"])   # no stray .tmp
        PlayerPrefs.set_int("x", 2)
        PlayerPrefs.save()
        with open(self.path) as f:
            self.assertIn('"x": 2', f.read())

    def test_corrupt_file_is_moved_aside_not_crashed_on(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("{ this is not json")
        self.assertEqual(PlayerPrefs.get_int("anything", 5), 5)
        self.assertTrue(os.path.exists(self.path + ".corrupt"))
        self.assertTrue(any("couldn't read" in m for m in self.messages("ERROR")))
        PlayerPrefs.set_int("fresh", 1)
        self.assertTrue(PlayerPrefs.save())


# ==========================================================================================
# 11. Particles
# ==========================================================================================

class TestParticles(EngineTestCase):
    def emitter(self, scene=None, x=100, y=100, **kwargs):
        scene = scene or Scene()
        defaults = dict(emission_rate=0, lifetime=(1.0, 1.0), speed=(0, 0), play_on_start=False, seed=1,
                        start_size=6, end_size=6, start_color=(255, 0, 0), end_color=(255, 0, 0),
                        start_alpha=255, end_alpha=255, max_particles=50)
        defaults.update(kwargs)
        go = GameObject(x, y, name="fx")
        system = go.add_component(ParticleSystem(**defaults))
        scene.add_game_object(go)
        return scene, go, system

    def test_burst_lifetime_and_pool_reuse(self):
        scene, go, system = self.emitter()
        system.burst(30)
        self.assertEqual(system.particle_count, 30)
        scene.update(0.5)
        self.assertEqual(system.particle_count, 30)
        scene.update(0.6)
        self.assertEqual(system.particle_count, 0)                 # expired particles went back to the pool
        self.assertEqual((system.pool.active_count, system.pool.free_count), (0, 30))
        system.burst(30)
        self.assertEqual(system.pool.total_created, 30)            # reused, not reallocated

    def test_max_particles_caps_emission(self):
        scene, go, system = self.emitter(max_particles=50)
        system.burst(500)
        self.assertEqual(system.particle_count, 50)
        self.assertEqual(system.pool.dropped, 1)

    def test_steady_emission_reaches_equilibrium_without_growth(self):
        scene, go, system = self.emitter(emission_rate=100, lifetime=(0.5, 0.5), max_particles=200)
        system.play()
        for _ in range(300):
            scene.update(DT)
        self.assertAlmostEqual(system.particle_count, 50, delta=3)          # rate x lifetime
        self.assertLessEqual(system.pool.total_created, 60)                 # steady-state allocation is bounded

    def test_duration_stops_a_non_looping_system(self):
        scene, go, system = self.emitter(emission_rate=100, duration=0.5, loop=False)
        system.play()
        for _ in range(120):
            scene.update(DT)
        self.assertFalse(system.is_playing)
        self.assertEqual(system.particle_count, 0)

    def test_seed_makes_effects_reproducible(self):
        results = []
        for _ in range(2):
            scene, go, system = self.emitter(speed=(20, 80), spread=360, seed=42, lifetime=(0.5, 1.5))
            system.burst(20)
            scene.update(0.3)
            results.append([(round(p.x, 6), round(p.y, 6)) for p in system._active])
        self.assertEqual(results[0], results[1])
        scene, go, other = self.emitter(speed=(20, 80), spread=360, seed=43, lifetime=(0.5, 1.5))
        other.burst(20)
        scene.update(0.3)
        self.assertNotEqual(results[0], [(round(p.x, 6), round(p.y, 6)) for p in other._active])

    def test_direction_speed_and_gravity(self):
        scene, go, system = self.emitter(speed=(100, 100), direction=-90, spread=0, gravity=0)
        system.burst(1)
        particle = system._active[0]
        self.assertAlmostEqual(particle.vx, 0.0, places=6)
        self.assertAlmostEqual(particle.vy, -100.0)                          # -90 degrees is straight up
        scene2, _, falling = self.emitter(speed=(0, 0), gravity=200)
        falling.burst(1)
        scene2.update(0.5)
        self.assertAlmostEqual(falling._active[0].vy, 100.0)
        self.assertGreater(falling._active[0].y, 100)

    def test_gradient_size_scaling_and_fade_are_baked_into_the_lookup_table(self):
        scene, go, system = self.emitter(start_size=10, end_size=2, start_alpha=255, end_alpha=0,
                                         color_stops=[(255, 0, 0), (0, 0, 255)], lut_steps=8)
        system.burst(1)
        scene.draw(pygame.Surface((320, 240)))
        first, last = system._lut[0][0], system._lut[-1][0]
        self.assertEqual((first.get_width(), last.get_width()), (10, 2))
        self.assertEqual(tuple(first.get_at((5, 5))), (255, 0, 0, 255))
        self.assertEqual(tuple(last.get_at((1, 1)))[3], 0)                   # fully faded by the end of life
        middle = system._lut[4][0]
        centre = middle.get_at((middle.get_width() // 2, middle.get_height() // 2))
        self.assertTrue(centre[0] > 0 and centre[2] > 0, f"mid-life should mix red and blue, got {tuple(centre)}")
        self.assertTrue(0 < centre[3] < 255)                                # ...and be partly faded

    def test_world_space_particles_stay_put_local_space_particles_follow(self):
        surface = pygame.Surface((320, 240))
        for world_space, expect_follow in ((True, False), (False, True)):
            scene, go, system = self.emitter(x=50, y=50, world_space=world_space, start_size=6, end_size=6)
            system.burst(1)
            go.transform.position.x = 200
            surface.fill(BG)
            scene.draw(surface)
            at_old, at_new = surface.get_at((50, 50))[:3], surface.get_at((200, 50))[:3]
            self.assertEqual(at_new == (255, 0, 0), expect_follow, world_space)
            self.assertEqual(at_old == (255, 0, 0), not expect_follow, world_space)

    def test_particles_draw_through_the_camera_and_count_as_draw_calls(self):
        scene, go, system = self.emitter(x=1000, y=1000)
        target = GameObject(1000, 1000)
        scene.add_game_object(target)
        cam = target.add_component(Camera(target=target))
        scene.set_active_camera(cam)
        system.burst(5)
        surface = render(scene, (320, 240))
        self.assertEqual(surface.get_at((160, 120))[:3], (255, 0, 0))
        self.assertGreaterEqual(scene.render_system.stats.draw_calls, 1)

    def test_additive_blending_brightens_what_is_behind(self):
        scene, go, system = self.emitter(additive=True, start_color=(100, 100, 100), end_color=(100, 100, 100))
        system.burst(1)
        surface = pygame.Surface((320, 240))
        surface.fill((50, 50, 50))
        scene.draw(surface)
        self.assertGreater(surface.get_at((100, 100))[0], 50)
        self.assertEqual(surface.get_at((10, 10))[:3], (50, 50, 50))

    def test_clear_and_destroy_return_everything_to_the_pool(self):
        scene, go, system = self.emitter()
        system.burst(10)
        system.clear()
        self.assertEqual(system.particle_count, 0)
        system.burst(10)
        go.destroy()
        self.assertEqual(system.pool.active_count, 0)


# ==========================================================================================
# 12. Spatial partitioning
# ==========================================================================================

class Item:
    pass


class TestSpatialHash(EngineTestCase):
    def test_queries_never_miss_a_true_overlap(self):
        rng = random.Random(3)
        grid = SpatialHash(64)
        items = {}
        for _ in range(400):
            item = Item()
            l, t = rng.uniform(-2000, 2000), rng.uniform(-2000, 2000)
            w, h = rng.uniform(1, 150), rng.uniform(1, 150)
            items[item] = (l, t, l + w, t + h)
            grid.update_bounds(item, *items[item])
        for _ in range(300):
            ql, qt = rng.uniform(-2100, 2100), rng.uniform(-2100, 2100)
            query = (ql, qt, ql + rng.uniform(1, 400), qt + rng.uniform(1, 400))
            found = grid.query_bounds(*query)
            self.assertEqual(len(found), len(set(found)), "duplicates in a query result")
            for item, b in items.items():
                if b[0] < query[2] and b[2] > query[0] and b[1] < query[3] and b[3] > query[1]:
                    self.assertIn(item, found)

    def test_moves_within_the_same_cells_cost_nothing_and_moves_across_cells_update(self):
        grid = SpatialHash(100)
        item = Item()
        self.assertTrue(grid.update_bounds(item, 10, 10, 20, 20))
        self.assertFalse(grid.update_bounds(item, 30, 30, 40, 40))         # same cell: no work
        self.assertTrue(grid.update_bounds(item, 150, 10, 160, 20))
        self.assertEqual(grid.query_bounds(0, 0, 50, 50), [])
        self.assertEqual(grid.query_bounds(140, 0, 170, 50), [item])
        self.assertEqual(len(grid._cells), 1)                              # the old cell was released

    def test_remove_and_clear_leave_no_garbage(self):
        grid = SpatialHash(50)
        items = [Item() for _ in range(20)]
        for i, item in enumerate(items):
            grid.update_bounds(item, i * 30, 0, i * 30 + 60, 40)
        self.assertEqual(len(grid), 20)
        for item in items:
            grid.remove(item)
        self.assertEqual((len(grid), len(grid._cells)), (0, 0))

    def test_huge_objects_do_not_flood_the_grid(self):
        grid = SpatialHash(32)
        world_trigger, small = Item(), Item()
        grid.update_bounds(world_trigger, -1e6, -1e6, 1e6, 1e6)
        grid.update_bounds(small, 5, 5, 10, 10)
        self.assertLess(len(grid._cells), 10)                              # not millions of cells
        self.assertIn(world_trigger, grid.query_bounds(500, 500, 510, 510))
        self.assertEqual(len(grid.query_bounds(0, 0, 20, 20)), 2)
        grid.update_bounds(world_trigger, 0, 0, 10, 10)                    # shrinks back into the grid
        self.assertEqual(len(grid._oversized), 0)

    def test_iteration_order_is_deterministic(self):
        def build():
            grid = SpatialHash(64)
            for i in range(30):
                item = Item()
                item.n = i
                grid.update_bounds(item, (i % 6) * 40, (i // 6) * 40, (i % 6) * 40 + 50, (i // 6) * 40 + 50)
            return [x.n for x in grid.query_bounds(0, 0, 400, 400)]
        self.assertEqual(build(), build())

    def test_legacy_rect_api(self):
        grid = SpatialHash(64)

        class Legacy:
            rect = pygame.Rect(10, 10, 20, 20)
        item = Legacy()
        grid.update(item)
        self.assertEqual(grid.query(pygame.Rect(0, 0, 40, 40)), {item})
        self.assertEqual(grid.query(pygame.Rect(500, 500, 10, 10)), set())

    def test_physics_broadphase_scales_with_local_density_not_total_count(self):
        scene = Scene()
        for i in range(3000):
            add_box(scene, (i % 100) * 40, (i // 100) * 40, 32, 32, static=True, sprite=False)
        mover = add_box(scene, 2034, 34, 4, 4, name="m", body=True, sprite=False)   # in the 8px gap between tiles
        before = scene.physics.stats.queries
        fixed_steps(scene, 5)
        per_step = (scene.physics.stats.queries - before) / 5
        self.assertLessEqual(per_step, 3)                                  # a couple of sweeps, not 3000 tests
        candidates = scene.spatial_hash.query_bounds(*mover.get_component(BoxCollider2D).bounds)
        self.assertLess(len(candidates), 25)                               # one grid cell's worth of the 3000


# ==========================================================================================
# 13. Regressions: bugs that existed before the overhaul
# ==========================================================================================

class Mover(Component):
    def update(self, dt):
        self.game_object.transform.position.x += 10


class OrderProbe(Component):
    def __init__(self, tag, order, log):
        super().__init__()
        self.tag = tag
        self.update_order = order
        self.log = log

    def update(self, dt):
        self.log.append(self.tag)


class TestRegressions(EngineTestCase):
    def test_camera_sees_final_positions_no_matter_which_gameobject_came_first(self):
        # update_order used to sort components only *within* one GameObject, so a
        # camera on an earlier GameObject than its target followed last frame's position.
        scene = Scene()
        cam_go = GameObject(name="camera")
        cam = cam_go.add_component(Camera(smooth_follow=False))
        scene.add_game_object(cam_go)                       # added BEFORE the player
        player = GameObject(0, 0, name="player")
        player.add_component(Mover())
        scene.add_game_object(player)
        cam.set_target(player)
        for expected in (10, 20, 30):
            scene.update(DT)
            self.assertEqual(cam.position.x, expected)      # zero-frame lag

    def test_update_order_is_global_across_the_scene(self):
        log = []
        scene = Scene()
        for tag, order in (("late", 100), ("early", -5), ("normal", 0)):
            go = GameObject(name=tag)
            go.add_component(OrderProbe(tag, order, log))
            scene.add_game_object(go)
        scene.update(DT)
        self.assertEqual(log, ["early", "normal", "late"])

    def test_only_overridden_hooks_are_scheduled(self):
        scene = Scene()
        go = GameObject()
        go.add_component(Component())                       # overrides nothing
        go.add_component(Recorder())                        # overrides update + fixed_update
        scene.add_game_object(go)
        scheduled = {type(c) for bucket in scene._update_buckets.values() for c in bucket}
        self.assertEqual(scheduled, {Recorder})
        scheduled_fixed = {type(c) for bucket in scene._fixed_buckets.values() for c in bucket}
        self.assertEqual(scheduled_fixed, {Recorder})

    def test_a_removed_collider_component_no_longer_blocks(self):
        # remove_component used to leave the collider registered in the spatial hash: an invisible wall.
        scene = Scene()
        floor = add_box(scene, 0, 200, 400, 20, static=True, sprite=False)
        body = add_box(scene, 50, 100, body=True, sprite=False)
        floor.remove_component(floor.get_component(BoxCollider2D))
        fixed_steps(scene, 120)
        self.assertGreater(body.transform.world_y, 300)
        self.assertEqual(len(scene.physics.colliders), 1)

    def test_a_disabled_collider_is_ignored(self):
        scene = Scene()
        floor = add_box(scene, 0, 200, 400, 20, static=True, sprite=False)
        body = add_box(scene, 50, 100, body=True, sprite=False)
        floor.get_component(BoxCollider2D).enabled = False
        fixed_steps(scene, 120)
        self.assertGreater(body.transform.world_y, 300)
        floor.get_component(BoxCollider2D).enabled = True    # and it works again when re-enabled
        body.get_component(Rigidbody2D).teleport(50, 100)
        fixed_steps(scene, 120)
        self.assertEqual(body.transform.world_y, 168.0)

    def test_removed_objects_leave_no_ghosts_behind(self):
        # remove_game_object used to keep go.scene set; moving the removed object could re-insert
        # its collider into the old scene's hash.
        scene = Scene()
        go = add_box(scene, 100, 100, name="gone")
        scene.remove_game_object(go)
        self.assertIsNone(go.scene)
        go.transform.position.x = 300
        fixed_steps(scene, 2)
        self.assertEqual(scene.physics.colliders, [])
        self.assertEqual(scene.physics.query_point(310, 110), [])
        self.assertEqual(scene.render_system.stats.dynamic_registered, 0)

    def test_spawning_does_not_rebuild_the_component_index(self):
        # The old cache was thrown away and rebuilt from scratch on every add/remove.
        scene = Scene()
        add_box(scene, 0, 0, name="first")
        index = scene._by_type[SpriteRenderer]
        for i in range(50):
            add_box(scene, i, i, name=f"spawn{i}")
        self.assertIs(scene._by_type[SpriteRenderer], index)
        self.assertEqual(len(scene.get_components(SpriteRenderer)), 51)
        self.assertEqual(len(scene.get_components(Component)), len({c for go in scene.game_objects for c in go.components}))

    def test_destroying_objects_from_inside_an_update_loop_is_safe(self):
        scene = Scene()
        victims = [add_box(scene, i, 0, name=f"v{i}", sprite=False) for i in range(50)]

        class Reaper(Component):
            def update(self, dt):
                for victim in victims:
                    victim.destroy()
                    scene.remove_game_object(victim)        # both spellings, mid-iteration
        reaper = GameObject(name="reaper")
        reaper.add_component(Reaper())
        scene.add_game_object(reaper)
        scene.update(DT)
        self.assertEqual(scene.game_objects, [reaper])
        self.assertTrue(all(v.scene is None for v in victims))

    def test_legacy_transform_idioms_still_work(self):
        go = GameObject(10, 20)
        go.transform.position.x += 5
        go.transform.position += Vector2(1, 1)
        self.assertEqual((go.x, go.y), (16, 21))
        go.transform.position = Vector2(100, 200)            # assigning a fresh vector
        self.assertEqual(go.transform.get_world_xy(), (100, 200))
        go.x = 7
        self.assertEqual(go.transform.world_x, 7)
        go.transform.rotation = 30
        go.transform.scale.x = 2
        self.assertEqual((go.transform.rotation, go.transform.scale.x), (30, 2))
        self.assertEqual(go.transform.position.copy(), Vector2(7, 200))

    def test_collider_rect_is_fresh_even_between_physics_steps(self):
        scene = Scene()
        go = add_box(scene, 0, 0, 10, 10, name="m", sprite=False)
        collider = go.get_component(BoxCollider2D)
        self.assertEqual(collider.rect, pygame.Rect(0, 0, 10, 10))
        go.transform.position.x = 55                          # script moves it; no fixed step has run
        self.assertEqual(collider.rect, pygame.Rect(55, 0, 10, 10))
        self.assertEqual(collider.rect.size, (10, 10))

    def test_scene_render_is_an_alias_of_draw(self):
        scene = Scene()
        sprite_go(scene, 10, 10, 8, 8, (255, 0, 0))
        via_render = pygame.Surface((64, 64))
        via_render.fill(BG)
        scene.render(via_render)
        via_draw = pygame.Surface((64, 64))
        via_draw.fill(BG)
        scene.draw(via_draw)
        self.assertEqual(pixels(via_render), pixels(via_draw))

    def test_ground_probe_hack_is_gone_but_the_attribute_remains(self):
        self.assertEqual(Rigidbody2D.GROUND_PROBE_DISTANCE, 0)

    def test_a_body_hanging_just_above_the_floor_is_not_grounded(self):
        # The old 4px "ground probe" reported is_grounded for a body still in the air.
        scene = Scene()
        add_box(scene, 0, 200, 400, 20, static=True, sprite=False)
        body = add_box(scene, 50, 160, 40, 30, body=True, sprite=False, use_gravity=False)   # 10px above the floor
        fixed_steps(scene, 3)
        self.assertFalse(body.get_component(Rigidbody2D).is_grounded)


# ==========================================================================================
# 14. End-to-end: the real Engine loop, in a subprocess (Engine.run() ends with pygame.quit())
# ==========================================================================================

ENGINE_SMOKE = r'''
import json, os, sys
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, ROOT)
import pygame
from engine.core.app import Engine
from engine.core.scene import Scene
from engine.core.scene_manager import SceneManager
from engine.core.game_object import GameObject
from engine.core.game_time import Time
from engine.core.debug_manager import Debug
from engine.core.player_prefs import PlayerPrefs
from engine.components.component import Component
from engine.components.sprite_renderer import SpriteRenderer
from engine.components.box_collider2d import BoxCollider2D
from engine.components.rigidbody2d import Rigidbody2D
from engine.components.particle_system import ParticleSystem
from engine.components.camera import Camera
from engine.ui.ui_text import UIText
from engine.ui.ui_health_bar import UIHealthBar

PlayerPrefs.set_path(os.path.join(TMP, "prefs.json"))
result = {}

class Quitter(Component):
    frames = 0
    def update(self, dt):
        Quitter.frames += 1
        if Quitter.frames == 5:
            result["scene_name"] = SceneManager.active_scene.name
            engine.quit()

class Next(Scene):
    def start(self):
        super().start()
        result["next_started"] = True
        go = GameObject(name="quitter")
        go.add_component(Quitter())
        self.add_game_object(go)

class Driver(Component):
    frame = 0
    def update(self, dt):
        Driver.frame += 1
        if Driver.frame == 3:
            for key in (pygame.K_F1, pygame.K_F2, pygame.K_F3, pygame.K_F4):
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key))
        if Driver.frame == 20:
            Debug.log("frame 20 reached")
            PlayerPrefs.set_int("frames", Driver.frame)          # left unsaved on purpose: Engine must save on exit
        if Driver.frame == 30:
            SceneManager.change_scene(Next)                      # deferred change from inside update

engine = Engine(320, 240, fps=60, fixed_fps=30, debug=True)
result["fixed_dt"] = Time.fixed_delta_time
scene = Scene("smoke")
ground = GameObject(0, 200, is_static=True)
ground.add_component(BoxCollider2D(size=(320, 20)))
scene.add_game_object(ground)
ball = GameObject(100, 0, name="ball")
surface = pygame.Surface((16, 16)); surface.fill((255, 0, 0))
ball.add_component(SpriteRenderer(sprite=surface))
ball.add_component(BoxCollider2D(size=(16, 16)))
ball.add_component(Rigidbody2D())
scene.add_game_object(ball)
hud = GameObject(name="hud")
hud.add_component(UIText("hello", anchor="TopLeft"))
scene.add_game_object(hud)
bar = GameObject(name="bar", x=10, y=30)
bar.add_component(UIHealthBar(80, 10, anchor="TopLeft"))
scene.add_game_object(bar)
fx = GameObject(100, 100)
fx.add_component(ParticleSystem(emission_rate=50, lifetime=(0.2, 0.4), speed=(20, 60), seed=1))
scene.add_game_object(fx)
cam_go = GameObject(name="cam")
cam = cam_go.add_component(Camera(target=ball))
scene.add_game_object(cam_go)
scene.set_active_camera(cam)
driver = GameObject(name="driver"); driver.add_component(Driver()); scene.add_game_object(driver)

engine.load_scene("smoke", scene)
engine.run()

result.update(
    frames=Driver.frame,
    next_frames=Quitter.frames,
    toggles=[engine.debug.show_overlay, engine.debug.show_colliders, engine.debug.show_grid, engine.debug.show_console],
    scene_after=SceneManager.active_scene.name if SceneManager.active_scene else None,
    smoke_destroyed=scene.is_destroyed,
    logged=any("frame 20" in e.message for e in engine.debug.logs),
    draw_time_recorded="draw" in engine.debug.timings,
    fixed_steps=scene.physics.stats.steps,
)
print("RESULT " + json.dumps(result))
'''


class TestEngineLoop(unittest.TestCase):
    def test_full_loop_debug_hotkeys_scene_change_and_orderly_shutdown(self):
        import json
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as tmp:
            script = ENGINE_SMOKE.replace("ROOT", repr(root)).replace("TMP", repr(tmp))
            proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=40)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            line = [l for l in proc.stdout.splitlines() if l.startswith("RESULT ")]
            self.assertTrue(line, proc.stdout[-2000:])
            result = json.loads(line[0][len("RESULT "):])
            self.assertEqual(result["frames"], 30)                               # the old scene's driver stopped when it was destroyed
            self.assertEqual(result["next_frames"], 5)                           # the new scene ran, then quit the engine
            self.assertEqual(result["scene_name"], "Next")                       # named after its class by the manager
            self.assertIsNone(result["scene_after"])                             # shutdown destroyed the active scene
            self.assertEqual(result["toggles"], [True, True, True, True])       # F1..F4 through the real event path
            self.assertAlmostEqual(result["fixed_dt"], 1 / 30)
            self.assertTrue(result["next_started"])                              # deferred change_scene ran mid-loop
            self.assertTrue(result["smoke_destroyed"])                           # ...and destroyed the old scene
            self.assertTrue(result["logged"])
            self.assertTrue(result["draw_time_recorded"])
            self.assertGreater(result["fixed_steps"], 0)
            with open(os.path.join(tmp, "prefs.json")) as f:                     # unsaved prefs were flushed on exit
                self.assertEqual(json.load(f), {"frames": 20})


class TestShowcaseExample(unittest.TestCase):
    """examples/showcase.py exercises nearly every system together; keep it working."""

    def test_showcase_runs_headless_and_plays_itself(self):
        import re
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "shot.png")
            proc = subprocess.run([sys.executable, os.path.join(root, "examples", "showcase.py"),
                                   "--headless", "420", shot, "--debug"],
                                  capture_output=True, text=True, timeout=90, cwd=tmp)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertTrue(os.path.getsize(shot) > 5000, "screenshot missing or blank")
            summary = [l for l in proc.stdout.splitlines() if l.startswith("frames=")]
            self.assertTrue(summary, proc.stdout[-1500:])
            score = int(re.search(r"score=(\d+)", summary[0]).group(1))
            self.assertGreaterEqual(score, 20, "the scripted player should collect coins")
            self.assertIn("Baked 425 tiles into one layer", proc.stdout)
            self.assertIn("Showcase scene destroyed", proc.stdout)         # orderly shutdown ran on_destroy


if __name__ == "__main__":
    unittest.main(verbosity=2)
