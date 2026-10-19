"""Tests for the physics rework (accumulating fall speed, exact integration, momentum, bounce, portal helpers,
swept triggers) and for gamepad support. Headless; run with:  python -m unittest tests.test_physics_and_gamepad
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: E402
from test_engine import EngineTestCase, Recorder, add_box, fixed_steps  # noqa: E402
from engine.components.box_collider2d import BoxCollider2D  # noqa: E402
from engine.components.player_controller import PlayerController  # noqa: E402
from engine.components.rigidbody2d import Rigidbody2D  # noqa: E402
from engine.core.app import Engine  # noqa: E402
from engine.core.game_object import GameObject  # noqa: E402
from engine.core.game_time import Time  # noqa: E402
from engine.core.scene import Scene  # noqa: E402
from engine.input.input_manager import Input  # noqa: E402

DT = 1.0 / 60.0


def falling_body(scene, **kwargs):
    go = GameObject(0, 0)
    go.add_component(Rigidbody2D(**kwargs))
    scene.add_game_object(go)
    return go, go.get_component(Rigidbody2D)


class TestFallAndIntegration(EngineTestCase):
    def test_fall_speed_accumulates_instead_of_being_constant(self):
        scene = Scene()
        go, rb = falling_body(scene, gravity=500)
        speeds = []
        for _ in range(4):
            fixed_steps(scene, 15)                   # a quarter second each
            speeds.append(rb.velocity.y)
        for earlier, later in zip(speeds, speeds[1:]):
            self.assertGreater(later, earlier + 100)
        self.assertAlmostEqual(speeds[0], 125.0, delta=0.5)      # g * t

    def test_distance_matches_half_g_t_squared_at_any_physics_rate(self):
        for hz in (30, 60, 120, 240):
            Time.reset()
            Time.set_fixed_rate(hz)
            scene = Scene()
            go, rb = falling_body(scene, gravity=500, terminal_velocity=10 ** 6)
            fixed_steps(scene, hz)                   # one second
            self.assertAlmostEqual(go.transform.world_y, 250.0, delta=0.01, msg=f"{hz} Hz")
        Time.reset()

    def test_a_jump_peaks_at_v_squared_over_two_g(self):
        scene = Scene()
        go, rb = falling_body(scene, gravity=500)
        rb.velocity.y = -430
        highest = 0.0
        for _ in range(120):
            fixed_steps(scene, 1)
            highest = max(highest, -go.transform.world_y)
        self.assertAlmostEqual(highest, 430 ** 2 / 1000.0, delta=0.6)

    def test_gravity_stops_accelerating_at_terminal_velocity(self):
        scene = Scene()
        go, rb = falling_body(scene, gravity=500, terminal_velocity=1000)
        fixed_steps(scene, 60 * 5)
        self.assertEqual(rb.velocity.y, 1000)

    def test_a_body_already_faster_than_terminal_velocity_keeps_its_speed(self):
        """The portal case: leaving a portal at 2500 px/s must not be snapped down to 1000."""
        scene = Scene()
        go, rb = falling_body(scene, gravity=500, terminal_velocity=1000)
        rb.velocity.y = 2500
        fixed_steps(scene, 30)
        self.assertEqual(rb.velocity.y, 2500)        # gravity neither speeds it up nor slows it down
        rb.drag = 1.0
        fixed_steps(scene, 30)
        self.assertLess(rb.velocity.y, 2500)         # but air drag still can

    def test_horizontal_launch_speed_is_never_clamped(self):
        scene = Scene()
        go, rb = falling_body(scene, gravity=0, use_gravity=False)
        rb.velocity.x = 4000
        fixed_steps(scene, 10)
        self.assertEqual(rb.velocity.x, 4000)


class TestPortalHelpers(EngineTestCase):
    def test_teleport_clears_velocity_by_default_and_keeps_it_on_request(self):
        scene = Scene()
        go, rb = falling_body(scene, use_gravity=False)
        rb.velocity.x, rb.velocity.y = 300, -400
        rb.teleport(50, 60)
        self.assertEqual((rb.velocity.x, rb.velocity.y), (0, 0))
        rb.velocity.x, rb.velocity.y = 300, -400
        rb.teleport(500, 600, keep_velocity=True)
        self.assertEqual((rb.velocity.x, rb.velocity.y), (300, -400))
        self.assertEqual(go.transform.get_world_xy(), (500, 600))

    def test_redirect_velocity_keeps_the_speed_and_changes_the_direction(self):
        scene = Scene()
        go, rb = falling_body(scene, use_gravity=False)
        rb.velocity.x, rb.velocity.y = 0, 1500
        self.assertAlmostEqual(rb.speed, 1500)
        rb.redirect_velocity(1, 0)
        self.assertAlmostEqual(rb.velocity.x, 1500)
        self.assertAlmostEqual(rb.velocity.y, 0)
        rb.redirect_velocity(0, 0)                   # no direction: unchanged
        self.assertAlmostEqual(rb.velocity.x, 1500)

    def test_a_portal_exit_flings_the_body_across_the_room(self):
        scene = Scene()
        go, rb = falling_body(scene, gravity=500)
        rb.velocity.y = 1800
        rb.teleport(100, 0, keep_velocity=True)
        rb.redirect_velocity(1, 0)
        fixed_steps(scene, 60)
        self.assertGreater(go.transform.world_x, 100 + 1700)


class TestBounce(EngineTestCase):
    def make_ball(self, scene, bounce):
        add_box(scene, -500, 300, 2000, 40, name="floor", static=True, sprite=False)
        ball = add_box(scene, 0, 0, 20, 20, name="ball", body=True, sprite=False, bounce=bounce)
        return ball, ball.get_component(Rigidbody2D)

    def test_default_is_a_dead_stop(self):
        scene = Scene()
        ball, rb = self.make_ball(scene, 0.0)
        fixed_steps(scene, 120)
        self.assertTrue(rb.is_grounded)
        self.assertEqual(rb.velocity.y, 0.0)

    def test_a_bouncy_ball_rebounds_lower_each_time_and_finally_rests(self):
        scene = Scene()
        ball, rb = self.make_ball(scene, 0.6)
        floor_top = 300 - 20
        apex = []
        previous_vy = 0
        for _ in range(60 * 12):
            fixed_steps(scene, 1)
            if previous_vy < 0 <= rb.velocity.y:
                apex.append(floor_top - ball.transform.world_y - 20)
            previous_vy = rb.velocity.y
        self.assertGreaterEqual(len(apex), 3)
        self.assertTrue(all(b < a for a, b in zip(apex, apex[1:])), apex)
        self.assertTrue(rb.is_grounded)
        self.assertEqual(rb.velocity.y, 0.0)


class TestSweptTriggers(EngineTestCase):
    def test_a_fast_body_cannot_skip_a_thin_trigger(self):
        scene = Scene()
        add_box(scene, 500, -100, 4, 300, name="gate", trigger=True, static=True, sprite=False)
        rec = Recorder()
        runner = add_box(scene, 0, 0, 20, 20, name="runner", body=True, sprite=False, use_gravity=False)
        runner.add_component(rec)
        runner.get_component(Rigidbody2D).velocity.x = 3600          # 60 px per step: clears the 4 px gate in one go
        fixed_steps(scene, 20)
        self.assertIn("trig_enter", rec.kinds())
        self.assertIn("trig_exit", rec.kinds())

    def test_a_slow_body_gets_exactly_one_enter_and_one_exit(self):
        scene = Scene()
        add_box(scene, 100, -100, 40, 300, name="zone", trigger=True, static=True, sprite=False)
        rec = Recorder()
        runner = add_box(scene, 0, 0, 20, 20, name="runner", body=True, sprite=False, use_gravity=False)
        runner.add_component(rec)
        runner.get_component(Rigidbody2D).velocity.x = 120
        fixed_steps(scene, 180)
        self.assertEqual(rec.kinds().count("trig_enter"), 1)
        self.assertEqual(rec.kinds().count("trig_exit"), 1)

    def test_a_fast_body_that_misses_the_trigger_does_not_fire_it(self):
        scene = Scene()
        add_box(scene, 500, 200, 4, 50, name="gate", trigger=True, static=True, sprite=False)
        rec = Recorder()
        runner = add_box(scene, 0, 0, 20, 20, name="runner", body=True, sprite=False, use_gravity=False)
        runner.add_component(rec)
        runner.get_component(Rigidbody2D).velocity.x = 3600
        fixed_steps(scene, 20)
        self.assertEqual(rec.kinds(), [])

    def test_a_fast_diagonal_body_only_fires_when_its_line_really_crosses(self):
        scene = Scene()
        add_box(scene, 300, 300, 4, 4, name="pin", trigger=True, static=True, sprite=False)     # on the line y = x
        add_box(scene, 600, 100, 4, 4, name="off", trigger=True, static=True, sprite=False)      # well off it
        rec = Recorder()
        runner = add_box(scene, 0, 0, 20, 20, name="runner", body=True, sprite=False, use_gravity=False)
        runner.add_component(rec)
        rb = runner.get_component(Rigidbody2D)
        rb.velocity.x, rb.velocity.y = 3000, 3000
        fixed_steps(scene, 15)
        entered = [name for kind, name in rec.log if kind == "trig_enter"]
        self.assertEqual(entered, ["pin"])


class TestMomentumInPlayerController(EngineTestCase):
    def make_player(self, scene, **kwargs):
        go = add_box(scene, 0, 0, 20, 30, name="p", body=True, sprite=False, gravity=500)
        go.add_component(PlayerController(speed=200, movement_type="platformer", **kwargs))
        return go, go.get_component(Rigidbody2D)

    def test_normal_running_is_unchanged(self):
        scene = Scene()
        go, rb = self.make_player(scene)
        Input.instance().inject_key("d", True)
        scene.tick(DT)
        self.assertEqual(rb.velocity.x, 200)
        Input.instance().begin_frame()
        Input.instance().inject_key("d", False)
        scene.tick(DT)
        self.assertEqual(rb.velocity.x, 0)

    def test_a_fast_body_keeps_its_speed_in_the_air(self):
        scene = Scene()
        go, rb = self.make_player(scene)
        rb.velocity.x = 900
        for _ in range(30):
            scene.tick(DT)
        self.assertAlmostEqual(rb.velocity.x, 900, delta=0.01)

    def test_pushing_against_the_motion_in_the_air_brakes_it(self):
        scene = Scene()
        go, rb = self.make_player(scene)
        rb.velocity.x = 900
        Input.instance().begin_frame()
        Input.instance().inject_key("a", True)
        for _ in range(30):
            scene.tick(DT)
        self.assertLess(rb.velocity.x, 900 - 500)

    def test_the_extra_speed_bleeds_off_on_the_ground(self):
        scene = Scene()
        add_box(scene, -2000, 100, 6000, 40, name="floor", static=True, sprite=False)
        go, rb = self.make_player(scene)
        scene.tick(DT)
        rb.velocity.x = 900
        for _ in range(90):
            scene.tick(DT)
        self.assertLessEqual(abs(rb.velocity.x), 200 + 1e-6)


class TestGamepad(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.input = Input.instance()

    def tearDown(self):
        self.input.reset()
        super().tearDown()

    def test_off_by_default_and_ignored_until_enabled(self):
        self.input.inject_gamepad_button("a")
        self.input.inject_gamepad_axis("left_x", 1.0)
        self.assertFalse(Input.is_gamepad_enabled())
        self.assertFalse(Input.is_gamepad_down("a"))
        self.assertEqual(Input.gamepad_axis("left_x"), 0.0)
        self.assertEqual(Input.gamepad_stick("left"), (0.0, 0.0))
        self.assertEqual(Input.gamepad_count(), 0)

    def test_button_edges_and_hold(self):
        Input.enable_gamepad()
        self.input.inject_gamepad_button("a", True)
        self.assertTrue(Input.is_gamepad_pressed("a"))
        self.assertTrue(Input.is_gamepad_down("a"))
        self.input.begin_frame()
        self.assertFalse(Input.is_gamepad_pressed("a"))
        self.assertTrue(Input.is_gamepad_down("a"))
        self.input.inject_gamepad_button("a", False)
        self.assertTrue(Input.is_gamepad_up("a"))
        self.assertFalse(Input.is_gamepad_down("a"))

    def test_fixed_step_edges_are_seen_by_exactly_one_step(self):
        Input.enable_gamepad()
        self.input.begin_frame()
        self.input.inject_gamepad_button("b", True)
        self.input.begin_frame()                         # the frame edge is gone...
        Time.in_fixed_step = True
        try:
            self.assertTrue(Input.is_gamepad_pressed("b"))     # ...but the physics step still gets it once
            self.input.end_fixed_step()
            self.assertFalse(Input.is_gamepad_pressed("b"))
        finally:
            Time.in_fixed_step = False

    def test_slots_are_independent(self):
        Input.enable_gamepad()
        self.input.inject_gamepad_button("x", True, slot=1)
        self.assertTrue(Input.is_gamepad_down("x", 1))
        self.assertFalse(Input.is_gamepad_down("x", 0))
        self.assertEqual(Input.gamepad_count(), 1)
        self.input.inject_gamepad_axis("left_x", 1.0, slot=0)
        self.assertEqual(Input.gamepad_count(), 2)

    def test_deadzone_and_rescaling(self):
        Input.enable_gamepad(deadzone=0.2)
        self.input.inject_gamepad_axis("left_x", 0.15)
        self.assertEqual(Input.gamepad_axis("left_x"), 0.0)
        self.input.inject_gamepad_axis("left_x", 0.6)
        self.assertAlmostEqual(Input.gamepad_axis("left_x"), 0.5)
        self.input.inject_gamepad_axis("left_x", -1.0)
        self.assertAlmostEqual(Input.gamepad_axis("left_x"), -1.0)

    def test_triggers_run_from_zero_to_one(self):
        Input.enable_gamepad(deadzone=0.0)
        self.input.inject_gamepad_axis("right_trigger", -0.5)
        self.assertEqual(Input.gamepad_axis("right_trigger"), 0.0)
        self.input.inject_gamepad_axis("right_trigger", 0.75)
        self.assertAlmostEqual(Input.gamepad_axis("right_trigger"), 0.75)

    def test_stick_deadzone_is_radial_and_never_longer_than_one(self):
        Input.enable_gamepad(deadzone=0.2)
        self.input.inject_gamepad_axis("left_x", 0.15)
        self.input.inject_gamepad_axis("left_y", 0.15)         # each axis small, length 0.21 -> just outside
        x, y = Input.gamepad_stick("left")
        self.assertAlmostEqual(x, y)
        self.input.inject_gamepad_axis("left_x", 1.0)
        self.input.inject_gamepad_axis("left_y", -1.0)
        x, y = Input.gamepad_stick("left")
        self.assertAlmostEqual(math.hypot(x, y), 1.0)
        self.assertLess(y, 0)                                   # up is negative, like the screen

    def test_unknown_names_fail_loudly(self):
        with self.assertRaises(ValueError):
            Input.is_gamepad_down("triangle")
        with self.assertRaises(ValueError):
            Input.gamepad_axis("left_z")
        with self.assertRaises(ValueError):
            self.input.inject_gamepad_button("nope")

    def test_real_sdl_events_are_translated_and_unplugging_releases_held_buttons(self):
        class StubPad:
            name = "Stub pad"

            def quit(self):
                pass

        Input.enable_gamepad()
        self.input._pads[0] = (StubPad(), 77)
        down = pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, instance_id=77, button=pygame.CONTROLLER_BUTTON_A)
        self.input.process_event(down)
        self.assertTrue(Input.is_gamepad_pressed("a"))
        self.assertEqual(Input.gamepad_name(0), "Stub pad")
        other = pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, instance_id=12345, button=pygame.CONTROLLER_BUTTON_B)
        self.input.process_event(other)                          # an unknown device is ignored
        self.assertFalse(Input.is_gamepad_down("b"))
        self.input.begin_frame()
        self.input.process_event(pygame.event.Event(pygame.CONTROLLERDEVICEREMOVED, instance_id=77))
        self.assertFalse(Input.is_gamepad_down("a"))
        self.assertTrue(Input.is_gamepad_up("a"))
        self.assertEqual(Input.gamepad_count(), 0)

    def test_window_focus_loss_releases_pad_buttons_too(self):
        Input.enable_gamepad()
        self.input.inject_gamepad_button("a", True)
        self.input.begin_frame()
        self.input.release_all()
        self.assertFalse(Input.is_gamepad_down("a"))
        self.assertTrue(Input.is_gamepad_up("a"))

    def test_disabling_releases_everything(self):
        Input.enable_gamepad()
        self.input.inject_gamepad_button("a", True)
        Input.enable_gamepad(False)
        self.input.begin_frame()
        self.assertFalse(Input.is_gamepad_down("a"))

    def test_engine_flag_turns_it_on(self):
        Engine(320, 240, "pad", gamepad=True, gamepad_deadzone=0.3)
        self.assertTrue(Input.is_gamepad_enabled())
        self.assertAlmostEqual(Input.instance()._deadzone, 0.3)       # Engine creates its own Input instance


class TestGamepadDrivesPlayerController(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.input = Input.instance()

    def tearDown(self):
        self.input.reset()
        super().tearDown()

    def player(self, scene, movement, **kwargs):
        go = add_box(scene, 0, 0, 20, 30, name="p", body=True, sprite=False, gravity=500 if movement == "platformer" else 0,
                     use_gravity=movement == "platformer")
        go.add_component(PlayerController(speed=200, jump_force=400, movement_type=movement, **kwargs))
        return go, go.get_component(Rigidbody2D)

    def test_the_stick_is_ignored_while_gamepads_are_off(self):
        scene = Scene()
        go, rb = self.player(scene, "platformer")
        self.input.inject_gamepad_axis("left_x", 1.0)
        scene.tick(DT)
        self.assertEqual(rb.velocity.x, 0)

    def test_analog_tilt_scales_platformer_speed(self):
        scene = Scene()
        go, rb = self.player(scene, "platformer")
        Input.enable_gamepad(deadzone=0.0)
        self.input.inject_gamepad_axis("left_x", 0.5)
        scene.tick(DT)
        self.assertAlmostEqual(rb.velocity.x, 100)
        self.input.inject_gamepad_axis("left_x", -1.0)
        scene.tick(DT)
        self.assertAlmostEqual(rb.velocity.x, -200)

    def test_dpad_moves_and_a_button_jumps(self):
        scene = Scene()
        add_box(scene, -500, 40, 2000, 40, name="floor", static=True, sprite=False)
        go, rb = self.player(scene, "platformer")
        Input.enable_gamepad()
        for _ in range(40):
            scene.tick(DT)
        self.assertTrue(rb.is_grounded)
        self.input.inject_gamepad_button("dpad_right", True)
        self.input.inject_gamepad_button("a", True)
        scene.tick(DT)
        self.assertEqual(rb.velocity.x, 200)
        self.assertLess(rb.velocity.y, 0)

    def test_use_gamepad_false_opts_a_character_out(self):
        scene = Scene()
        go, rb = self.player(scene, "platformer", use_gamepad=False)
        Input.enable_gamepad()
        self.input.inject_gamepad_axis("left_x", 1.0)
        scene.tick(DT)
        self.assertEqual(rb.velocity.x, 0)

    def test_two_players_listen_to_their_own_pads(self):
        scene = Scene()
        one, rb1 = self.player(scene, "platformer", gamepad_slot=0)
        two, rb2 = self.player(scene, "platformer", gamepad_slot=1)
        Input.enable_gamepad(deadzone=0.0)
        self.input.inject_gamepad_axis("left_x", 1.0, slot=1)
        scene.tick(DT)
        self.assertEqual(rb1.velocity.x, 0)
        self.assertEqual(rb2.velocity.x, 200)

    def test_top_down_stick_is_analog_and_never_faster_than_full_tilt(self):
        scene = Scene()
        go, rb = self.player(scene, "top_down")
        Input.enable_gamepad(deadzone=0.0)
        self.input.inject_gamepad_axis("left_x", 1.0)
        self.input.inject_gamepad_axis("left_y", 1.0)
        scene.tick(DT)
        self.assertAlmostEqual(math.hypot(rb.velocity.x, rb.velocity.y), 200, delta=0.01)
        self.input.inject_gamepad_axis("left_y", 0.0)
        self.input.inject_gamepad_axis("left_x", 0.5)
        scene.tick(DT)
        self.assertAlmostEqual(rb.velocity.x, 100)


if __name__ == "__main__":
    unittest.main()
