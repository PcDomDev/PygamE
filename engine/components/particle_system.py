"""ParticleSystem: a lightweight emitter for dust, sparks, explosions and trails.

    dust = GameObject(x, y, name="Dust")
    dust.add_component(ParticleSystem(
        emission_rate=0, lifetime=(0.3, 0.6), speed=(40, 90), direction=-90, spread=60,
        gravity=200, start_size=6, end_size=1, color_stops=[(255, 240, 200), (150, 120, 90)]))
    scene.add_game_object(dust)
    dust.get_component(ParticleSystem).burst(12)       # one puff

Particles are not GameObjects (that would cost a component list, a transform
and scene bookkeeping per particle). They are small slotted structs recycled
through an `ObjectPool`, so a steady stream of sparks allocates nothing after
warm-up. They don't collide.

How it draws fast: colour, size and fade are all pure functions of a particle's
age fraction, so the system pre-renders one small surface per step of that
range (`lut_steps`, default 24) the first time it draws. Drawing a particle is
then a table lookup plus one batched blit - no per-particle drawing calls.
Randomness comes from a per-system `random.Random`, so pass `seed=` for
reproducible effects.

Coordinates: with `world_space=True` (default) particles stay where they were
emitted when the emitter moves (trails, explosions); with False they move with
the emitter (a flame on a torch). Angles use the engine convention: 0 = right,
positive = clockwise on screen, so `direction=-90` is straight up.
"""
import math
import random

import pygame

from engine.components.component import Component
from engine.core.game_time import Time
from engine.core.object_pool import ObjectPool


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "age", "lifetime")

    def __init__(self):
        self.x = self.y = self.vx = self.vy = 0.0
        self.age = 0.0
        self.lifetime = 1.0


def _lerp(a, b, t):
    return a + (b - a) * t


def _gradient(stops, t):
    """Colour at fraction t along evenly spaced RGB stops."""
    if len(stops) == 1:
        return stops[0]
    scaled = t * (len(stops) - 1)
    index = min(int(scaled), len(stops) - 2)
    local = scaled - index
    a, b = stops[index], stops[index + 1]
    return (int(_lerp(a[0], b[0], local)), int(_lerp(a[1], b[1], local)), int(_lerp(a[2], b[2], local)))


class ParticleSystem(Component):
    sort_y = float("inf")      # draws after ordinary sprites with the same z_index

    def __init__(self, emission_rate=0.0, lifetime=(0.5, 1.0), speed=(50.0, 100.0),
                 direction=-90.0, spread=360.0, gravity=0.0, drag=0.0,
                 start_size=6, end_size=None, start_color=(255, 255, 255), end_color=None,
                 color_stops=None, start_alpha=255, end_alpha=0, shape="circle", sprite=None,
                 additive=False, max_particles=500, world_space=True, z_index=10,
                 offset=(0.0, 0.0), spawn_radius=0.0, duration=None, loop=True,
                 play_on_start=True, lut_steps=24, seed=None):
        super().__init__()
        self.emission_rate = emission_rate
        self.lifetime = self._range(lifetime)
        self.speed = self._range(speed)
        self.direction = direction
        self.spread = spread
        self.gravity = gravity
        self.drag = drag
        self.start_size = start_size
        self.end_size = start_size if end_size is None else end_size
        self.color_stops = list(color_stops) if color_stops else [start_color, end_color or start_color]
        self.start_alpha = start_alpha
        self.end_alpha = end_alpha
        self.shape = shape
        self.sprite = sprite
        self.additive = additive
        self.world_space = world_space
        self.z_index = z_index
        self.offset = offset
        self.spawn_radius = spawn_radius
        self.duration = duration
        self.loop = loop
        self.play_on_start = play_on_start
        self.lut_steps = max(2, lut_steps)
        self.rng = random.Random(seed)

        self._pool = ObjectPool(Particle, on_spawn=self._init_particle, max_size=max_particles, name="ParticlePool")
        self._active = []
        self._playing = False
        self._elapsed = 0.0
        self._emit_accum = 0.0
        self._lut = None
        self._spawn_origin = (0.0, 0.0)

    @staticmethod
    def _range(value):
        if isinstance(value, (int, float)):
            return (float(value), float(value))
        return (float(value[0]), float(value[1]))

    # -- control -----------------------------------------------------------------

    def start(self):
        if self.play_on_start:
            self.play()

    def play(self):
        self._playing = True
        self._elapsed = 0.0

    def stop(self, clear=False):
        """Stop emitting. Live particles finish their lives unless `clear`."""
        self._playing = False
        if clear:
            self.clear()

    def clear(self):
        for particle in self._active:
            self._pool.despawn(particle)
        self._active = []

    @property
    def is_playing(self):
        return self._playing

    @property
    def particle_count(self):
        return len(self._active)

    @property
    def pool(self):
        return self._pool

    def invalidate(self):
        """Call after changing size/colour/alpha/shape settings at runtime."""
        self._lut = None

    def burst(self, count):
        """Emit `count` particles right now (an explosion, a puff of dust)."""
        self._refresh_origin()
        for _ in range(int(count)):
            if self._pool.spawn() is None:
                break

    emit = burst

    # -- particle lifecycle -----------------------------------------------------

    def _refresh_origin(self):
        transform = self.game_object.transform
        x, y = transform.get_render_xy(Time.alpha)
        self._spawn_origin = (x + self.offset[0], y + self.offset[1])

    def _init_particle(self, p):
        rng = self.rng
        angle = math.radians(self.direction + rng.uniform(-self.spread / 2.0, self.spread / 2.0))
        speed = rng.uniform(*self.speed)
        p.vx = math.cos(angle) * speed
        p.vy = math.sin(angle) * speed
        p.lifetime = max(1e-4, rng.uniform(*self.lifetime))
        p.age = 0.0
        ox, oy = self._spawn_origin if self.world_space else self.offset
        if self.spawn_radius:
            r = self.spawn_radius * math.sqrt(rng.random())
            a = rng.uniform(0.0, math.tau)
            ox += math.cos(a) * r
            oy += math.sin(a) * r
        p.x = ox
        p.y = oy
        self._active.append(p)

    # -- update -----------------------------------------------------------------

    def update(self, delta_time):
        if not self.enabled:
            return

        if self._playing:
            self._elapsed += delta_time
            if self.duration is not None and self._elapsed >= self.duration:
                if self.loop:
                    self._elapsed -= self.duration
                else:
                    self._playing = False
            if self._playing and self.emission_rate > 0:
                self._emit_accum += self.emission_rate * delta_time
                count = int(self._emit_accum)
                if count:
                    self._emit_accum -= count
                    self.burst(count)

        if not self._active:
            return
        gravity = self.gravity * delta_time
        damping = math.exp(-self.drag * delta_time) if self.drag else 1.0
        survivors = []
        despawn = self._pool.despawn
        for p in self._active:
            p.age += delta_time
            if p.age >= p.lifetime:
                despawn(p)
                continue
            p.vy += gravity
            if damping != 1.0:
                p.vx *= damping
                p.vy *= damping
            p.x += p.vx * delta_time
            p.y += p.vy * delta_time
            survivors.append(p)
        self._active = survivors

    # -- drawing -----------------------------------------------------------------

    def _build_lut(self):
        steps = self.lut_steps
        lut = []
        for i in range(steps):
            t = i / (steps - 1)
            size = max(1, round(_lerp(self.start_size, self.end_size, t)))
            color = _gradient(self.color_stops, t)
            alpha = max(0, min(255, int(_lerp(self.start_alpha, self.end_alpha, t))))
            lut.append((self._make_surface(size, color, alpha), size // 2))
        self._lut = lut

    def _make_surface(self, size, color, alpha):
        if self.sprite is not None:
            longest = max(self.sprite.get_size())
            factor = size / longest
            w = max(1, round(self.sprite.get_width() * factor))
            h = max(1, round(self.sprite.get_height() * factor))
            surface = pygame.transform.scale(self.sprite, (w, h))
            if self.additive:
                surface = surface.copy()
                surface.fill((alpha, alpha, alpha), special_flags=pygame.BLEND_RGB_MULT)
            else:
                surface = surface.convert_alpha() if pygame.display.get_surface() else surface.copy()
                surface.set_alpha(alpha)
            return surface
        if self.additive:
            scaled = tuple(int(c * alpha / 255) for c in color)
            surface = pygame.Surface((size, size))
            if self.shape == "square":
                surface.fill(scaled)
            else:
                pygame.draw.circle(surface, scaled, (size / 2.0, size / 2.0), max(0.5, size / 2.0))
            return surface.convert() if pygame.display.get_surface() else surface
        surface = pygame.Surface((size, size), pygame.SRCALPHA)
        rgba = (color[0], color[1], color[2], alpha)
        if self.shape == "square":
            surface.fill(rgba)
        else:
            pygame.draw.circle(surface, rgba, (size / 2.0, size / 2.0), max(0.5, size / 2.0))
        return surface.convert_alpha() if pygame.display.get_surface() else surface

    def draw_world(self, screen, offset_x, offset_y, alpha):
        if not self._active:
            return 0
        if self._lut is None:
            self._build_lut()
        lut = self._lut
        last = len(lut) - 1

        if self.world_space:
            base_x, base_y = -offset_x, -offset_y
        else:
            ex, ey = self.game_object.transform.get_render_xy(alpha)
            base_x, base_y = ex - offset_x, ey - offset_y

        blits = []
        add = blits.append
        additive = self.additive
        flag = pygame.BLEND_RGB_ADD
        for p in self._active:
            index = int(p.age / p.lifetime * last)
            surface, half = lut[index if index < last else last]
            pos = (int(p.x + base_x) - half, int(p.y + base_y) - half)
            add((surface, pos, None, flag) if additive else (surface, pos))
        screen.blits(blits, False)
        return len(blits)

    def on_destroy(self):
        self.clear()
