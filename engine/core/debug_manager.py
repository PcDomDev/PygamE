"""Runtime diagnostics for the engine: logging, plus in-game debug overlays
(FPS/log panel, collider outlines, a world-space coordinate grid).

Two ways to use it:

    debug = DebugManager()          # normally created once by Engine
    debug.log_warning("...")        # instance access

    from engine.core.debug_manager import DebugManager
    DebugManager.log_warning("...") # static-style access from anywhere,
                                     # e.g. inside a Component that has no
                                     # direct reference to the Engine

Both call paths land on the same instance: whichever DebugManager was
created most recently makes itself the shared instance, and the classmethods
below apply to that one. This mirrors Unity's `Debug.Log(...)` - convenient
for a component-based engine where threading a logger reference through
every single class would be a lot of ceremony for little benefit.

Note the distinction from `engine/utils/warnings.py`: that module is for
construction-time misconfiguration caught once via Python's `warnings`
module (bad anchor string, etc). This module is for runtime, in-game events
- the kind of thing you want visible in an on-screen overlay while the game
is actually running.
"""

import math
import time
from collections import deque

import pygame

from engine.components.collider2d import Collider2D


class LogEntry:
    __slots__ = ("level", "message", "source", "timestamp")

    def __init__(self, level, message, source, timestamp):
        self.level = level
        self.message = message
        self.source = source
        self.timestamp = timestamp

    def format(self):
        label = f"[{self.level}]"
        if self.source:
            label += f"[{self.source}]"
        return f"{label} {self.message}"


class DebugManager:
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

    _LEVEL_COLORS = {
        INFO: (150, 220, 255),
        WARNING: (255, 210, 90),
        ERROR: (255, 110, 110),
    }

    _instance = None

    def __init__(self, history_size=200, overlay_lines=8, print_to_console=True, grid_size=100):
        DebugManager._instance = self

        self.print_to_console = print_to_console
        self.overlay_lines = overlay_lines
        self.logs = deque(maxlen=history_size)

        self.show_overlay = False
        self.show_colliders = False
        self.show_grid = False
        self.grid_size = grid_size  # world-space pixels between grid lines

        self.fps = 0.0
        self._fps_timer = 0.0
        self._fps_frame_count = 0

        self._font = None
        self._grid_font = None

    # -- singleton-style access --------------------------------------------------

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = DebugManager()
        return cls._instance

    @classmethod
    def log_info(cls, message, source=None):
        cls.instance()._log(cls.INFO, message, source)

    @classmethod
    def log_warning(cls, message, source=None):
        cls.instance()._log(cls.WARNING, message, source)

    @classmethod
    def log_error(cls, message, source=None):
        cls.instance()._log(cls.ERROR, message, source)

    def _log(self, level, message, source):
        entry = LogEntry(level, message, source, time.time())
        self.logs.append(entry)
        if self.print_to_console:
            print(entry.format())

    # -- overlay toggles ----------------------------------------------------------

    def toggle_overlay(self):
        self.show_overlay = not self.show_overlay

    def toggle_colliders(self):
        self.show_colliders = not self.show_colliders

    def toggle_grid(self):
        self.show_grid = not self.show_grid

    # -- per-frame bookkeeping --------------------------------------------------

    def update(self, delta_time):
        self._fps_frame_count += 1
        self._fps_timer += delta_time
        if self._fps_timer >= 0.5:
            self.fps = self._fps_frame_count / self._fps_timer
            self._fps_frame_count = 0
            self._fps_timer = 0.0

    # -- drawing --------------------------------------------------------------------

    def draw_overlay(self, screen, scene=None):
        if not self.show_overlay:
            return

        if self._font is None:
            self._font = pygame.font.SysFont("consolas", 16)

        lines = [f"FPS: {self.fps:.1f}"]
        if scene is not None:
            lines.append(f"Scene: {scene.name}  |  Objects: {len(scene.game_objects)}")
        lines.append("F1 overlay  |  F2 colliders  |  F3 grid")
        lines.append("-" * 32)

        for entry in list(self.logs)[-self.overlay_lines:]:
            lines.append(entry.format())

        padding = 8
        line_height = self._font.get_linesize()
        box_width = 460
        box_height = padding * 2 + line_height * len(lines)

        overlay_surface = pygame.Surface((box_width, box_height), pygame.SRCALPHA)
        overlay_surface.fill((15, 15, 20, 180))
        screen.blit(overlay_surface, (10, 10))

        for i, line in enumerate(lines):
            color = (235, 235, 235)
            for level, level_color in self._LEVEL_COLORS.items():
                if line.startswith(f"[{level}]"):
                    color = level_color
                    break
            text_surface = self._font.render(line, True, color)
            screen.blit(text_surface, (10 + padding, 10 + padding + i * line_height))

    def draw_colliders(self, screen, scene, camera=None):
        """Outlines every collider in the scene - box or circle - green for
        solid, red for trigger. Works with any Collider2D subclass via its
        `.shape` tag, not just BoxCollider2D."""
        if not self.show_colliders or scene is None:
            return

        offset = (0, 0)
        if camera is not None:
            cam_offset = camera.get_offset(screen.get_width(), screen.get_height())
            offset = (round(cam_offset.x), round(cam_offset.y))

        for collider in scene.get_components(Collider2D):
            color = (255, 90, 90) if collider.is_trigger else (90, 255, 120)
            if collider.shape == "circle":
                center = (round(collider.center_x - offset[0]), round(collider.center_y - offset[1]))
                pygame.draw.circle(screen, color, center, round(collider.radius), width=2)
            else:
                draw_rect = collider.rect.move(-offset[0], -offset[1])
                pygame.draw.rect(screen, color, draw_rect, width=2)

    def draw_grid(self, screen, camera=None):
        """A world-space coordinate grid, drawn under everything else's
        outlines but useful for eyeballing positions/distances while
        debugging - press F3. Lines are spaced `self.grid_size` world
        pixels apart and labelled with their world coordinate; the x=0
        and y=0 axes are highlighted so the origin is easy to spot."""
        if not self.show_grid:
            return

        if self._grid_font is None:
            self._grid_font = pygame.font.SysFont("consolas", 12)

        offset_x, offset_y = 0.0, 0.0
        if camera is not None:
            cam_offset = camera.get_offset(screen.get_width(), screen.get_height())
            offset_x, offset_y = cam_offset.x, cam_offset.y

        screen_w, screen_h = screen.get_size()
        size = self.grid_size

        grid_color = (70, 70, 80)
        axis_color = (230, 100, 100)
        label_color = (170, 170, 180)

        world_left, world_top = offset_x, offset_y
        world_right, world_bottom = offset_x + screen_w, offset_y + screen_h

        start_x = math.floor(world_left / size) * size
        x = start_x
        while x <= world_right:
            screen_x = round(x - offset_x)
            on_axis = abs(x) < 1e-6
            pygame.draw.line(screen, axis_color if on_axis else grid_color,
                              (screen_x, 0), (screen_x, screen_h), 2 if on_axis else 1)
            label = self._grid_font.render(str(int(round(x))), True, label_color)
            screen.blit(label, (screen_x + 2, 2))
            x += size

        start_y = math.floor(world_top / size) * size
        y = start_y
        while y <= world_bottom:
            screen_y = round(y - offset_y)
            on_axis = abs(y) < 1e-6
            pygame.draw.line(screen, axis_color if on_axis else grid_color,
                              (0, screen_y), (screen_w, screen_y), 2 if on_axis else 1)
            label = self._grid_font.render(str(int(round(y))), True, label_color)
            screen.blit(label, (2, screen_y + 2))
            y += size
