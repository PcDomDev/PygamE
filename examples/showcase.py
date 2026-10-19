"""Engine showcase: one small playable level that touches every system.

    python examples/showcase.py                           # play
    python examples/showcase.py --headless 300 shot.png   # simulate 300 frames offscreen, save a screenshot
    python examples/showcase.py --headless 300 shot.png --debug   # ...with F1 stats + F2 gizmos on

Controls: A/D or arrows = move, Space = jump (twice), left mouse = shoot toward the
cursor, M = crossfade the music, H = show/hide the HUD, R = restart the level
(SceneManager.change_scene), Esc = quit.  Debug: F1 stats, F2 gizmos, F3 grid, F4 console.

What each part demonstrates:
  ground/platforms   static colliders + `bake_tilemap` (thousands of tile blits -> a few)
  player             Rigidbody2D + PlayerController, fixed-step physics, interpolated rendering,
                     entity events ("jumped", "jumps_changed"), collision layers/masks
  coins              trigger colliders, EventBus, ParticleSystem bursts, positional SFX
  enemies            patrol via collision hooks, Health, world-space UIHealthBar attached to the enemy
  bullets            GameObjectPool + kinematic trigger bodies (no allocation while shooting)
  HUD                Canvas + anchored UIText/UIHealthBar/UIButton (never moves with the camera)
  audio              AudioManager: music crossfade, SFX, mute (tones are generated at start-up)
  prefs              PlayerPrefs stores the high score
"""
import math
import os
import random
import struct
import sys
import tempfile
import wave

if "--headless" in sys.argv:                       # must be set before pygame is imported
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from engine.audio.audio_manager import AudioManager  # noqa: E402
from engine.components.box_collider2d import BoxCollider2D  # noqa: E402
from engine.components.camera import Camera  # noqa: E402
from engine.components.circle_collider2d import CircleCollider2D  # noqa: E402
from engine.components.component import Component  # noqa: E402
from engine.components.particle_system import ParticleSystem  # noqa: E402
from engine.components.player_controller import PlayerController  # noqa: E402
from engine.components.rigidbody2d import Rigidbody2D  # noqa: E402
from engine.components.sprite_renderer import SpriteRenderer  # noqa: E402
from engine.core.app import Engine  # noqa: E402
from engine.core.debug_manager import Debug  # noqa: E402
from engine.core.event_bus import EventBus  # noqa: E402
from engine.core.game_object import GameObject  # noqa: E402
from engine.core.object_pool import GameObjectPool  # noqa: E402
from engine.core.player_prefs import PlayerPrefs  # noqa: E402
from engine.core.scene import Scene  # noqa: E402
from engine.core.scene_manager import SceneManager  # noqa: E402
from engine.input.input_manager import Input  # noqa: E402
from engine.physics.layers import CollisionLayers  # noqa: E402
from engine.primitives import create_rectangle  # noqa: E402
from engine.rendering.tilemap import bake_tilemap  # noqa: E402
from engine.ui.canvas import Canvas  # noqa: E402
from engine.ui.ui_button import UIButton  # noqa: E402
from engine.ui.ui_health_bar import UIHealthBar  # noqa: E402
from engine.ui.ui_text import UIText  # noqa: E402

TILE = 32
GROUND_ROW = 17
SPAWN = (120, 400)
SKY = (120, 172, 226)


# -- generated assets -------------------------------------------------------------------

def make_tone(path, freq, seconds, volume=0.4, harmonics=(1.0,)):
    """Write a small mono WAV (integer cycles, so it loops without a click)."""
    rate = 22050
    frames = int(rate * seconds)
    data = bytearray()
    for i in range(frames):
        t = i / rate
        value = sum(math.sin(2 * math.pi * freq * (n + 1) * t) * amp for n, amp in enumerate(harmonics))
        value *= volume / max(1.0, sum(harmonics))
        fade = min(1.0, (frames - i) / 400.0) if seconds < 1 else 1.0          # de-click short blips
        data += struct.pack("<h", int(value * fade * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(data))


def make_sounds():
    folder = os.path.join(tempfile.gettempdir(), "engine_showcase_audio")
    os.makedirs(folder, exist_ok=True)
    sounds = {
        "coin": (os.path.join(folder, "coin.wav"), 880, 0.18, 0.5, (1.0, 0.4)),
        "jump": (os.path.join(folder, "jump.wav"), 330, 0.12, 0.4, (1.0,)),
        "shoot": (os.path.join(folder, "shoot.wav"), 180, 0.09, 0.4, (1.0, 0.5)),
        "hit": (os.path.join(folder, "hit.wav"), 90, 0.15, 0.5, (1.0, 0.6)),
        "music_a": (os.path.join(folder, "music_a.wav"), 110, 4.0, 0.5, (1.0, 0.5, 0.25)),
        "music_b": (os.path.join(folder, "music_b.wav"), 165, 4.0, 0.5, (1.0, 0.3, 0.15)),
    }
    paths = {}
    for key, (path, freq, seconds, volume, harmonics) in sounds.items():
        if not os.path.exists(path):
            make_tone(path, freq, seconds, volume, harmonics)
        paths[key] = path
    return paths


def make_tiles():
    rng = random.Random(3)
    tiles = {}
    for name, base in (("dirt", (122, 84, 52)), ("stone", (120, 124, 134)), ("grass", (122, 84, 52))):
        surface = pygame.Surface((TILE, TILE))
        surface.fill(base)
        for _ in range(18):
            shade = rng.randint(-14, 14)
            color = tuple(max(0, min(255, c + shade)) for c in base)
            surface.fill(color, (rng.randrange(TILE - 3), rng.randrange(TILE - 3), 3, 3))
        if name == "grass":
            surface.fill((84, 168, 76), (0, 0, TILE, 9))
            surface.fill((110, 196, 96), (0, 0, TILE, 3))
        tiles[name] = surface
    return tiles


def disc(radius, color, outline=None):
    surface = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    pygame.draw.circle(surface, color, (radius, radius), radius)
    if outline:
        pygame.draw.circle(surface, outline, (radius, radius), radius, 2)
    return surface


def player_surface():
    surface = pygame.Surface((28, 40), pygame.SRCALPHA)
    pygame.draw.rect(surface, (60, 116, 220), surface.get_rect(), border_radius=6)
    pygame.draw.rect(surface, (255, 255, 255), (16, 9, 8, 8))
    pygame.draw.rect(surface, (20, 30, 60), (20, 11, 4, 5))
    return surface


# -- gameplay components ----------------------------------------------------------------

class Health(Component):
    def __init__(self, hp):
        super().__init__()
        self.max_hp = hp
        self.hp = hp

    def take_damage(self, amount):
        self.hp = max(0, self.hp - amount)
        self.events.emit("health_changed", hp=self.hp, maximum=self.max_hp)
        if self.hp == 0:
            self.events.emit("died")


class Coin(Component):
    def on_trigger_enter(self, other):                      # Unity-style physics hook
        if other.game_object.name == "Player":
            x, y = self.game_object.transform.get_world_xy()
            EventBus.emit("coin", x=x + 10, y=y + 10)
            self.game_object.destroy()                       # safe mid-physics: deferred


class Patrol(Component):
    """Walks back and forth; turns when it bumps a wall; hurts the player on touch."""

    def __init__(self, speed=70):
        super().__init__()
        self.speed = speed
        self.direction = -1

    def start(self):
        self.body = self.game_object.get_component(Rigidbody2D)

    def update(self, dt):
        self.body.velocity.x = self.direction * self.speed

    def on_collision_enter(self, collision):
        if abs(collision.normal.x) > 0.5:
            self.direction *= -1
        if collision.game_object.name == "Player":
            EventBus.emit("player_hit", damage=12, push=-collision.normal.x)


class Bullet(Component):
    SPEED = 560

    def start(self):
        self.age = 0.0

    def on_spawn(self, **kwargs):
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        if self.age > 1.4:
            self.game_object.despawn()

    def on_trigger_enter(self, other):
        health = other.game_object.get_component(Health)
        if health is not None:
            health.take_damage(10)
            AudioManager.play_sfx(ShowcaseScene.sounds["hit"], volume=0.6,
                                  position=other.game_object.transform.get_world_xy())
        self.game_object.despawn()


# -- the scene --------------------------------------------------------------------------

class ShowcaseScene(Scene):
    sounds = {}

    def start(self):
        super().start()
        ShowcaseScene.sounds = make_sounds()
        for name, index in (("player", 1), ("enemy", 2), ("bullet", 3), ("pickup", 4), ("ground", 5)):
            CollisionLayers.register(name, index)
        self.mask_player = CollisionLayers.mask("ground", "enemy", "pickup")
        self.score = 0
        self.best = PlayerPrefs.get_int("high_score", 0)
        self.shot_cooldown = 0.0
        self.music_track = "music_a"
        self.tiles = {}

        self.build_level()
        self.build_player_and_camera()
        self.build_pickups_and_enemies()
        self.build_effects()
        self.build_hud()

        EventBus.subscribe("coin", self.on_coin, owner=self)          # owner= -> dropped when the scene is destroyed
        EventBus.subscribe("player_hit", self.on_player_hit, owner=self)
        EventBus.subscribe("enemy_killed", self.on_enemy_killed, owner=self)
        AudioManager.play_music(self.sounds["music_a"], fade_in=1.5, volume=0.3)
        Debug.log(f"Showcase loaded: {len(self.game_objects)} objects, best score {self.best}")

    # -- construction ---------------------------------------------------------------

    def add_solid(self, col, row, cols, rows, tile="dirt", top="grass"):
        """A static solid block of tiles: one collider, tiles recorded for baking."""
        for c in range(col, col + cols):
            for r in range(row, row + rows):
                self.tiles[(c, r)] = top if (r == row and top) else tile
        go = GameObject(col * TILE, row * TILE, name="Solid", layer="ground", is_static=True)
        go.add_component(BoxCollider2D(size=(cols * TILE, rows * TILE)))
        self.add_game_object(go)

    def build_level(self):
        self.add_solid(-12, GROUND_ROW, 103, 3)                                   # ground
        self.add_solid(-13, 5, 1, 15, tile="stone", top=None)                      # left wall
        for col, row, width in ((6, 14, 4), (14, 12, 5), (22, 10, 4), (30, 13, 6), (40, 11, 5),
                                (50, 14, 4), (58, 12, 6), (66, 9, 4), (74, 12, 5)):
            self.add_solid(col, row, width, 2)                                    # floating platforms
        for col in (16, 22, 32, 38, 52, 58, 68, 74):
            self.add_solid(col, GROUND_ROW - 2, 1, 2, tile="stone", top=None)      # enemy lane pillars

        cols = [c for c, _ in self.tiles]
        rows = [r for _, r in self.tiles]
        c0, r0 = min(cols), min(rows)
        grid = [[self.tiles.get((c, r)) for c in range(c0, max(cols) + 1)] for r in range(r0, max(rows) + 1)]
        self.add_game_object(bake_tilemap(grid, make_tiles(), TILE, origin=(c0 * TILE, r0 * TILE), z_index=-50))
        Debug.log(f"Baked {len(self.tiles)} tiles into one layer")

    def build_player_and_camera(self):
        self.player = create_rectangle(*SPAWN, 28, 40, name="Player", add_rigidbody=True, layer="player")
        self.player.get_component(SpriteRenderer).set_sprite(player_surface())
        self.player.get_component(BoxCollider2D).mask = self.mask_player
        self.body = self.player.get_component(Rigidbody2D)
        self.body.gravity = 900
        self.player.add_component(PlayerController(speed=230, jump_force=430, movement_type="platformer", max_jumps=2))
        self.health = self.player.add_component(Health(100))
        self.add_game_object(self.player)
        self.player.events.subscribe("jumped", lambda **k: AudioManager.play_sfx(self.sounds["jump"], volume=0.5),
                                     owner=self)

        camera_go = GameObject(name="Camera")
        self.camera = camera_go.add_component(Camera(target=self.player, follow_speed=6))
        self.add_game_object(camera_go)
        self.set_active_camera(self.camera)

    def build_pickups_and_enemies(self):
        coin_surface = disc(10, (255, 214, 60), (200, 140, 20))
        coin_spots = [(8 * TILE, 12 * TILE), (16 * TILE, 10 * TILE), (24 * TILE, 8 * TILE), (32 * TILE, 11 * TILE),
                      (42 * TILE, 9 * TILE), (52 * TILE, 12 * TILE), (60 * TILE, 10 * TILE), (68 * TILE, 7 * TILE),
                      (76 * TILE, 10 * TILE), (26 * TILE, 15 * TILE), (46 * TILE, 15 * TILE), (62 * TILE, 15 * TILE)]
        for x, y in coin_spots:
            coin = GameObject(x, y, name="Coin", layer="pickup", is_static=True)
            coin.add_component(SpriteRenderer(sprite=coin_surface, z_index=2))
            coin.add_component(CircleCollider2D(radius=10, is_trigger=True, mask=CollisionLayers.mask("player")))
            coin.add_component(Coin())
            self.add_game_object(coin)

        for lane in (19, 35, 55, 71):
            enemy = create_rectangle(lane * TILE, (GROUND_ROW - 1) * TILE, 30, 30, color=(214, 72, 72),
                                     name="Enemy", add_rigidbody=True, layer="enemy")
            enemy.get_component(BoxCollider2D).mask = CollisionLayers.mask("ground", "player", "bullet", "enemy")
            enemy.get_component(Rigidbody2D).gravity = 900
            enemy.add_component(Patrol())
            health = enemy.add_component(Health(30))
            self.add_game_object(enemy)
            bar = GameObject(15, -8, name="EnemyBar", parent=enemy)               # child: follows the enemy
            hp_bar = bar.add_component(UIHealthBar(36, 6, max_value=30, world_space=True, pivot="MidBottom",
                                                   border_width=1, fill_color=(220, 60, 60), low_color=(220, 60, 60)))
            enemy.events.subscribe("health_changed", lambda hp, maximum, bar=hp_bar: bar.set_value(hp), owner=self)
            enemy.events.subscribe("died", lambda go=enemy: self.kill_enemy(go), owner=self)

    def build_effects(self):
        sparks = GameObject(name="Sparks")
        self.sparks = sparks.add_component(ParticleSystem(
            play_on_start=False, lifetime=(0.35, 0.7), speed=(90, 260), direction=-90, spread=200,
            gravity=520, start_size=7, end_size=1, color_stops=[(255, 246, 170), (255, 170, 40), (150, 60, 20)],
            additive=True, max_particles=400, z_index=20, seed=7))
        self.add_game_object(sparks)

        def make_bullet():
            go = GameObject(name="Bullet", layer="bullet")
            go.add_component(SpriteRenderer(sprite=disc(4, (255, 240, 130)), z_index=5))
            go.add_component(BoxCollider2D(size=(8, 8), is_trigger=True, mask=CollisionLayers.mask("ground", "enemy")))
            go.add_component(Rigidbody2D(use_gravity=False, is_kinematic=True))
            go.add_component(Bullet())
            return go
        self.bullets = GameObjectPool(self, make_bullet, initial_size=24, max_size=48, name="Bullets")

    def build_hud(self):
        hud = GameObject(name="HUD")
        self.canvas = hud.add_component(Canvas())
        self.add_game_object(hud)

        def element(x, y, component):
            go = GameObject(x, y, parent=hud)
            go.add_component(component)
            return component

        self.hp_bar = element(12, 12, UIHealthBar(240, 22, max_value=100, anchor="TopLeft", show_text=True,
                                                  smooth_speed=3.0, trail_color=(255, 255, 255)))
        self.hp_bar.bind(lambda: self.health.hp)
        self.jump_text = element(12, 42, UIText("Jumps: 2/2", anchor="TopLeft"))
        self.score_text = element(-12, 12, UIText("", anchor="TopRight"))
        self.mute_button = element(-12, 44, UIButton("Mute", 96, 30, anchor="TopRight"))
        self.mute_button.on_click.append(self.toggle_mute)
        element(12, -10, UIText("A/D move   Space jump x2   Mouse shoot   M music   H HUD   R restart   F1-F4 debug",
                                anchor="BottomLeft"))
        self.player.events.subscribe(
            "jumps_changed", lambda remaining, maximum: self.jump_text.set_text(f"Jumps: {remaining}/{maximum}"),
            owner=self)
        self.refresh_score()

    # -- gameplay ------------------------------------------------------------------

    def refresh_score(self):
        self.score_text.set_text(f"Score {self.score}   Best {self.best}")

    def on_coin(self, x, y):
        self.score += 10
        if self.score > self.best:
            self.best = self.score
            PlayerPrefs.set_int("high_score", self.best)              # saved automatically when the engine exits
        self.refresh_score()
        self.sparks.game_object.transform.teleport(x, y)
        self.sparks.burst(16)
        AudioManager.play_sfx(self.sounds["coin"], volume=0.7, position=(x, y))

    def on_player_hit(self, damage, push):
        self.health.take_damage(damage)
        self.body.add_impulse(push * 260, -240)
        AudioManager.play_sfx(self.sounds["hit"], volume=0.8)

    def on_enemy_killed(self, x, y):
        self.score += 25
        self.refresh_score()
        self.sparks.game_object.transform.teleport(x, y)
        self.sparks.burst(30)

    def kill_enemy(self, enemy):
        x, y = enemy.transform.get_world_xy()
        EventBus.emit("enemy_killed", x=x + 15, y=y + 15)
        enemy.destroy()

    def toggle_mute(self, button):
        AudioManager.toggle_mute()
        button.text = "Unmute" if AudioManager.is_muted() else "Mute"

    def respawn(self):
        self.health.hp = self.health.max_hp
        self.body.teleport(*SPAWN)
        self.camera.snap_to_target()
        Debug.log_warning("Respawned")

    def shoot(self):
        mouse = Input.mouse_world_position()
        px, py = self.player.transform.get_world_xy()
        px, py = px + 14, py + 18
        dx, dy = mouse.x - px, mouse.y - py
        length = math.hypot(dx, dy) or 1.0
        bullet = self.bullets.spawn(x=px, y=py)                      # reuses an idle bullet: no allocation
        if bullet is not None:
            body = bullet.get_component(Rigidbody2D)
            body.velocity.x, body.velocity.y = dx / length * Bullet.SPEED, dy / length * Bullet.SPEED
            AudioManager.play_sfx(self.sounds["shoot"], volume=0.35, position=(px, py))

    def update(self, delta_time):
        super().update(delta_time)                                    # runs every component: keep this line
        self.shot_cooldown -= delta_time
        over_ui = self.mute_button.contains_point(*Input.mouse_position())
        if Input.is_key_down("mouse_left") and self.shot_cooldown <= 0 and not over_ui:
            self.shot_cooldown = 0.16
            self.shoot()
        if Input.is_key_pressed("m"):
            self.music_track = "music_b" if self.music_track == "music_a" else "music_a"
            AudioManager.crossfade_to(self.sounds[self.music_track], duration=2.0, volume=0.3)
        if Input.is_key_pressed("h"):
            self.canvas.visible = not self.canvas.visible
        if Input.is_key_pressed("r"):
            SceneManager.change_scene(ShowcaseScene)                 # deferred to the end of the frame
        if Input.is_key_pressed("escape"):
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        if self.health.hp <= 0 or self.player.transform.world_y > 1500:
            self.respawn()

    def destroy(self):
        Debug.log("Showcase scene destroyed")
        super().destroy()


# -- entry points -----------------------------------------------------------------------

def run_headless(frames, screenshot, show_debug):
    """Simulate the level with a scripted 'player', then render one frame to a PNG."""
    engine = Engine(1280, 720, "Showcase (headless)", fps=0, background_color=SKY)
    PlayerPrefs.set_path(os.path.join(tempfile.gettempdir(), "engine_showcase_prefs_headless.json"))
    SceneManager.change_scene(ShowcaseScene)
    scene = SceneManager.active_scene
    inp = engine.input
    inp.inject_mouse_position(900, 260)
    for frame in range(frames):
        inp.begin_frame()
        if frame == 5:
            inp.inject_key("d", True)                                 # run right...
        if frame % 40 == 32:
            inp.inject_key("space", True)                             # ...jumping now and then (open-loop, so
        if frame % 40 == 34:                                          # the phase must suit the exact jump arc)
            inp.inject_key("space", False)
        if frame % 30 == 10:
            inp.inject_key("mouse_left", True)                        # ...and shooting
        if frame % 30 == 12:
            inp.inject_key("mouse_left", False)
        inp.update()
        SceneManager.update(1 / 60)
        AudioManager.update(1 / 60)
        engine.debug.update(1 / 60)
    scene = SceneManager.active_scene
    engine.debug.show_overlay = engine.debug.show_colliders = show_debug
    engine.debug.show_console = show_debug
    engine.screen.fill(SKY)
    SceneManager.draw(engine.screen)
    engine.debug.draw_colliders(engine.screen, scene, scene.active_camera)
    engine.debug.draw_overlay(engine.screen, scene)
    engine.debug.draw_console(engine.screen)
    pygame.image.save(engine.screen, screenshot)
    stats = scene.render_system.stats
    print(f"frames={frames} score={scene.score} objects={scene.entity_count} draw_calls={scene.draw_calls} "
          f"sprites_drawn={stats.sprites_drawn} particles={scene.sparks.particle_count} "
          f"bullets_active={scene.bullets.active_count}/{scene.bullets.total_created} -> {screenshot}")
    engine._shutdown()


def main():
    args = sys.argv[1:]
    if "--headless" in args:
        i = args.index("--headless")
        run_headless(int(args[i + 1]), args[i + 2], "--debug" in args)
        return
    engine = Engine(1280, 720, "Engine Showcase", fps=144, background_color=SKY)
    PlayerPrefs.set_path(os.path.join(tempfile.gettempdir(), "engine_showcase_prefs.json"))
    engine.change_scene(ShowcaseScene)
    engine.run()


if __name__ == "__main__":
    main()
