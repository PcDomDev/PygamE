"""Micro-benchmarks: frame cost of common scenes, optionally against another
copy of the engine (e.g. the version before the overhaul).

    python tests/benchmark.py                          # benchmark this engine
    python tests/benchmark.py --compare /path/to/old   # ...and an older copy too
                                                       # (/path/to/old must contain an `engine/` package)

Each scenario runs in its own process against the chosen engine using only API
that both versions share, so the numbers are like-for-like. Headless (SDL dummy
video driver): absolute milliseconds depend on your machine and include no GPU;
read the *ratios*. Not collected by the test runners (name doesn't start with test_).
"""
import argparse
import json
import math
import os
import subprocess
import sys

CHILD = r'''
import math, os, sys, time, json
os.environ["SDL_VIDEODRIVER"] = "dummy"; os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, ROOT)
import pygame
pygame.init()
screen = pygame.display.set_mode((1280, 720))
from engine.core.scene import Scene
from engine.core.game_object import GameObject
from engine.components.sprite_renderer import SpriteRenderer
from engine.components.box_collider2d import BoxCollider2D
from engine.components.rigidbody2d import Rigidbody2D
from engine.components.camera import Camera
NEW = hasattr(Scene, "tick")
try:
    from engine.core.debug_manager import DebugManager
    DebugManager(print_to_console=False)
except Exception:
    pass
step = scene_tick = None
DT = 1 / 60

def surf(color=(90, 160, 90)):
    s = pygame.Surface((32, 32)); s.fill(color); return s

def camera_rig(scene, cx, cy):
    target = GameObject(cx, cy, name="target"); scene.add_game_object(target)
    cam = target.add_component(Camera(target=target, smooth_follow=False)); scene.set_active_camera(cam)
    return target

def measure(scene, frames=120, warmup=20, mover=None):
    drive = scene.tick if NEW else scene.update
    times = {"update": 0.0, "draw": 0.0}
    for i in range(warmup + frames):
        if mover: mover(i)
        t0 = time.perf_counter(); drive(DT); t1 = time.perf_counter()
        screen.fill((20, 20, 30)); scene.render(screen); t2 = time.perf_counter()
        if i >= warmup:
            times["update"] += t1 - t0; times["draw"] += t2 - t1
    return {k: 1000 * v / frames for k, v in times.items()}

def scenario_static_tiles():
    scene = Scene(); tile = surf()
    for r in range(80):
        for c in range(80):
            go = GameObject(c * 32, r * 32)
            go.add_component(SpriteRenderer(sprite=tile))
            if NEW: go.is_static = True
            scene.add_game_object(go)
    target = camera_rig(scene, 1280, 1280)
    def mover(i): target.transform.position.x = 1280 + 600 * math.sin(i / 30); target.transform.position.y = 1280 + 300 * math.cos(i / 40)
    return scene, mover

def scenario_baked_tiles():
    scene, mover = scenario_static_tiles()
    from engine.rendering.tilemap import bake_static_sprites
    bake_static_sprites(scene)
    return scene, mover

def scenario_dynamic_sprites():
    scene = Scene(); tile = surf((160, 90, 90))
    for r in range(50):
        for c in range(60):
            go = GameObject(c * 40, r * 40); go.add_component(SpriteRenderer(sprite=tile)); scene.add_game_object(go)
    target = camera_rig(scene, 1200, 1000)
    def mover(i): target.transform.position.x = 1200 + 500 * math.sin(i / 30)
    return scene, mover

def scenario_physics():
    scene = Scene(); tile = surf((120, 120, 200))
    for c in range(60):                                   # a floor
        go = GameObject(c * 32, 700); go.add_component(SpriteRenderer(sprite=tile)); go.add_component(BoxCollider2D(size=(32, 32)))
        if NEW: go.is_static = True
        scene.add_game_object(go)
    for i in range(2000):                                 # lots of unrelated static scenery colliders
        go = GameObject(3000 + (i % 50) * 32, (i // 50) * 32); go.add_component(BoxCollider2D(size=(32, 32)))
        if NEW: go.is_static = True
        scene.add_game_object(go)
    body = surf((230, 80, 80))
    for i in range(300):
        go = GameObject(20 + (i % 30) * 60, 100 + (i // 30) * 50)
        go.add_component(SpriteRenderer(sprite=body)); go.add_component(BoxCollider2D(size=(32, 32))); go.add_component(Rigidbody2D())
        scene.add_game_object(go)
    return scene, None

def scenario_particles():
    from engine.components.particle_system import ParticleSystem
    scene = Scene()
    go = GameObject(640, 360); go.add_component(ParticleSystem(emission_rate=6000, lifetime=(0.5, 0.5), speed=(50, 300),
                                                             max_particles=4000, seed=1, gravity=200))
    scene.add_game_object(go)
    return scene, None

SCENARIOS = {f[len("scenario_"):]: f_ for f, f_ in globals().items() if f.startswith("scenario_")}
scene, mover = SCENARIOS[NAME]()
result = measure(scene, mover=mover, warmup=60 if NAME == "physics" else 20)
result["scenario"] = NAME
print("BENCH " + json.dumps(result))
'''

SCENARIOS = {
    "static_tiles": "6,400 static 32px tiles, camera panning (about 900 visible)",
    "baked_tiles": "same tiles after bake_static_sprites() [new engine only]",
    "dynamic_sprites": "3,000 dynamic sprites, camera panning (about 700 visible)",
    "physics": "300 resting bodies + 60 floor tiles + 2,000 far static colliders",
    "particles": "4,000 live particles [new engine only]",
}
NEW_ONLY = {"baked_tiles", "particles"}


def run_one(root, name):
    script = CHILD.replace("ROOT", repr(root)).replace("NAME", repr(name))
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=600)
    for line in proc.stdout.splitlines():
        if line.startswith("BENCH "):
            return json.loads(line[6:])
    return {"error": (proc.stderr or proc.stdout)[-300:]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", help="directory containing another `engine/` package to compare against")
    args = parser.parse_args()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    engines = [("new", here)] + ([("old", os.path.abspath(args.compare))] if args.compare else [])

    print(f"{'scenario':<18}{'engine':<6}{'update ms':>11}{'draw ms':>10}{'total ms':>10}   what")
    for name, description in SCENARIOS.items():
        totals = {}
        for label, root in engines:
            if label == "old" and name in NEW_ONLY:
                continue
            r = run_one(root, name)
            if "error" in r:
                print(f"{name:<18}{label:<6}  failed: {r['error']}")
                continue
            total = r["update"] + r["draw"]
            totals[label] = total
            print(f"{name:<18}{label:<6}{r['update']:>11.2f}{r['draw']:>10.2f}{total:>10.2f}   {description if label == 'new' else ''}")
        if "old" in totals and "new" in totals:
            print(f"{'':<18}{'':<6}{'':>11}{'':>10}{totals['old'] / totals['new']:>9.1f}x   faster")


if __name__ == "__main__":
    main()
