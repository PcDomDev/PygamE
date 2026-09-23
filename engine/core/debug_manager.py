"""Runtime diagnostics: Unity-style logging plus in-game debug overlays.

Logging - static-style, from anywhere (no reference to the Engine needed):

    from engine.core.debug_manager import Debug
    Debug.log("Spawned 12 enemies")
    Debug.log_warning("Texture missing, using placeholder")
    Debug.log_error("Save file corrupt")

(`Debug` is an alias of `DebugManager`; `log_info` is the same as `log`.)

Overlays - toggled with function keys while the game runs (all remappable
through `debug.keys`, and disabled entirely with `debug.enabled = False` or
`Engine(debug=False)` for release builds):

    F1  Performance stats: FPS, frame time (avg/worst), where the time goes
        (fixed/update/draw), entity count, draw calls, physics counts
    F2  Gizmos: collider hitboxes (green solid, red trigger, blue static),
        rigidbody velocity vectors, object pivots
    F3  World grid with labelled lines and highlighted X/Y axes through the origin
    F4  Console: scrollable on-screen log window (mouse wheel / PageUp / PageDown)

Two ways to reach the instance - `Engine.debug`, or the classmethods above;
whichever DebugManager was created most recently is the shared one. Note the
distinction from `engine/utils/warnings.py`: that module is for
construction-time misconfiguration caught once via Python's `warnings` module;
this one is for runtime events you want visible while the game runs.

The debug tools try not to distort what they measure: overlay text is rendered
at ~4 Hz into a cached surface, and grid labels are cached.
"""
import math
import time
from collections import deque

import pygame

from engine.utils.fonts import get_font, render_text


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

    def __init__(self, history_size=500, overlay_lines=8, print_to_console=True, grid_size=100,
                 enabled=True):
        DebugManager._instance = self

        self.enabled = enabled
        self.print_to_console = print_to_console
        self.overlay_lines = overlay_lines
        self.console_lines = 14
        self.logs = deque(maxlen=history_size)

        # Overlay switches. (`show_overlay` = F1 stats, `show_colliders` = F2
        # gizmos: the pre-existing names, kept.)
        self.show_overlay = False
        self.show_colliders = False
        self.show_grid = False
        self.show_console = False
        self.grid_size = grid_size  # world-space pixels between grid lines

        # Remap freely, e.g. debug.keys["console"] = "grave"
        self.keys = {"stats": "f1", "gizmos": "f2", "grid": "f3", "console": "f4"}

        self.fps = 0.0
        self.frame_ms = 0.0          # average frame time over the last window
        self.worst_ms = 0.0          # slowest frame in the last window
        self.timings = {}            # section name -> smoothed ms (Engine records "fixed", "update", "draw")
        self._fps_timer = 0.0
        self._fps_frame_count = 0
        self._window_worst = 0.0

        self._t0 = time.time()
        self._console_scroll = 0
        self._console_cache = None
        self._console_key = None
        self._overlay_cache = None
        self._overlay_age = 1e9
        self._label_cache = {}
        self._extra_stats = {}

    # -- logging (static-style access) ---------------------------------------------

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = DebugManager()
        return cls._instance

    @classmethod
    def log(cls, message, source=None):
        """Unity-style `Debug.Log`."""
        cls.instance()._log(cls.INFO, message, source)

    @classmethod
    def log_info(cls, message, source=None):
        cls.instance()._log(cls.INFO, message, source)

    @classmethod
    def log_warning(cls, message, source=None):
        cls.instance()._log(cls.WARNING, message, source)

    @classmethod
    def log_error(cls, message, source=None):
        cls.instance()._log(cls.ERROR, message, source)

    @classmethod
    def log_exception(cls, exc, source=None):
        cls.instance()._log(cls.ERROR, f"{type(exc).__name__}: {exc}", source)

    @classmethod
    def clear_logs(cls):
        instance = cls.instance()
        instance.logs.clear()
        instance._console_scroll = 0

    def _log(self, level, message, source):
        entry = LogEntry(level, str(message), source, time.time())
        self.logs.append(entry)
        if self.print_to_console:
            print(entry.format())

    # -- toggles / input -------------------------------------------------------------

    def toggle_overlay(self):
        self.show_overlay = not self.show_overlay

    def toggle_colliders(self):
        self.show_colliders = not self.show_colliders

    def toggle_grid(self):
        self.show_grid = not self.show_grid

    def toggle_console(self):
        self.show_console = not self.show_console

    def handle_input(self):
        """Poll the debug hotkeys. Engine calls this once per frame."""
        if not self.enabled:
            return
        from engine.input.input_manager import Input
        if Input.is_key_pressed(self.keys["stats"]):
            self.toggle_overlay()
        if Input.is_key_pressed(self.keys["gizmos"]):
            self.toggle_colliders()
        if Input.is_key_pressed(self.keys["grid"]):
            self.toggle_grid()
        if Input.is_key_pressed(self.keys["console"]):
            self.toggle_console()

        if self.show_console:
            scroll = Input.mouse_scroll()
            if Input.is_key_pressed("pageup"):
                scroll += self.console_lines - 1
            if Input.is_key_pressed("pagedown"):
                scroll -= self.console_lines - 1
            if scroll:
                self.scroll_console(scroll)

    def scroll_console(self, lines):
        """Scroll the console back (positive) or forward (negative) by `lines`."""
        limit = max(0, len(self.logs) - self.console_lines)
        self._console_scroll = max(0, min(limit, self._console_scroll + int(lines)))

    # -- per-frame bookkeeping -----------------------------------------------------

    def update(self, delta_time):
        self._fps_frame_count += 1
        self._fps_timer += delta_time
        self._overlay_age += delta_time
        if delta_time > self._window_worst:
            self._window_worst = delta_time
        if self._fps_timer >= 0.5:
            self.fps = self._fps_frame_count / self._fps_timer
            self.frame_ms = 1000.0 * self._fps_timer / self._fps_frame_count
            self.worst_ms = 1000.0 * self._window_worst
            self._fps_frame_count = 0
            self._fps_timer = 0.0
            self._window_worst = 0.0

    def record(self, section, milliseconds):
        """Record how long a section of the frame took (smoothed for display)."""
        previous = self.timings.get(section)
        self.timings[section] = milliseconds if previous is None else previous + (milliseconds - previous) * 0.1

    # -- F1: performance stats -------------------------------------------------------

    def _stat_lines(self, scene):
        lines = [f"FPS: {self.fps:5.1f}   frame: {self.frame_ms:5.2f} ms (worst {self.worst_ms:5.2f})"]
        if self.timings:
            parts = "  ".join(f"{name} {ms:4.2f}" for name, ms in self.timings.items())
            lines.append(f"ms  {parts}")
        if scene is not None:
            lines.append(f"Scene: {scene.name}   Entities: {scene.active_entity_count}/{len(scene.game_objects)}")
            rs = scene.render_system.stats
            lines.append(f"Draw calls: {scene.draw_calls}   sprites: {rs.sprites_drawn} drawn / {rs.sprites_culled} culled")
            ps = scene.physics.stats
            lines.append(f"Physics: {ps.bodies} bodies  {ps.colliders} colliders  {ps.pairs} contacts")
        for key, value in self._extra_stats.items():
            lines.append(f"{key}: {value}")
        keys = self.keys
        lines.append(f"{keys['stats'].upper()} stats | {keys['gizmos'].upper()} gizmos | "
                     f"{keys['grid'].upper()} grid | {keys['console'].upper()} console")
        return lines

    def set_stat(self, name, value):
        """Show a custom line in the F1 overlay (None removes it)."""
        if value is None:
            self._extra_stats.pop(name, None)
        else:
            self._extra_stats[name] = value

    def draw_overlay(self, screen, scene=None):
        if not (self.enabled and self.show_overlay):
            return

        # The overlay text changes every frame but nobody can read it that
        # fast: rebuild the panel ~4x/second, blit the cached one otherwise.
        if self._overlay_cache is None or self._overlay_age >= 0.25:
            self._overlay_age = 0.0
            font = get_font("consolas", 16)
            lines = self._stat_lines(scene)
            padding = 8
            line_height = font.get_linesize()
            surfaces = [render_text(font, line, (235, 235, 235)) for line in lines]
            width = max(s.get_width() for s in surfaces) + padding * 2
            height = padding * 2 + line_height * len(lines)
            panel = pygame.Surface((width, height), pygame.SRCALPHA)
            panel.fill((15, 15, 20, 180))
            for i, surface in enumerate(surfaces):
                panel.blit(surface, (padding, padding + i * line_height))
            self._overlay_cache = panel
        screen.blit(self._overlay_cache, (10, 10))

    # -- F2: gizmos -----------------------------------------------------------------

    @staticmethod
    def _view_offset(screen, scene, camera):
        if scene is not None:
            return scene.view_offset
        if camera is not None:
            cam_offset = camera.get_offset(screen.get_width(), screen.get_height())
            return round(cam_offset.x), round(cam_offset.y)
        return 0, 0

    def draw_colliders(self, screen, scene, camera=None):
        """Gizmos: outlines every collider - box or circle - green for solid,
        red for trigger, blue for static solids; a yellow line for each
        rigidbody's velocity; a small cross at each collider owner's pivot.
        Hitboxes show the *physics* position, which under interpolation can
        differ from the drawn sprite by up to one physics step."""
        if not (self.enabled and self.show_colliders) or scene is None:
            return

        ox, oy = self._view_offset(screen, scene, camera)
        view = screen.get_rect().inflate(64, 64)

        for collider in scene.physics.colliders:
            collider.refresh()
            if collider.is_trigger:
                color = (255, 90, 90)
            elif collider.is_static:
                color = (90, 150, 255)
            else:
                color = (90, 255, 120)
            if collider.shape == "circle":
                center = (round(collider._cx - ox), round(collider._cy - oy))
                if view.collidepoint(center):
                    pygame.draw.circle(screen, color, center, max(1, round(collider._radius)), width=2)
            else:
                rect = collider.rect.move(-ox, -oy)
                if view.colliderect(rect):
                    pygame.draw.rect(screen, color, rect, width=2)
            if not collider.is_static:
                px, py = collider.game_object.transform.get_world_xy()
                px, py = round(px - ox), round(py - oy)
                pygame.draw.line(screen, (255, 255, 255), (px - 4, py), (px + 4, py))
                pygame.draw.line(screen, (255, 255, 255), (px, py - 4), (px, py + 4))

        for body in scene.physics.bodies:
            v = body.velocity
            if v.x or v.y:
                cx, cy = body.game_object.transform.get_world_xy()
                start = (round(cx - ox), round(cy - oy))
                end = (round(cx - ox + v.x * 0.25), round(cy - oy + v.y * 0.25))
                pygame.draw.line(screen, (255, 230, 80), start, end, 2)

    # -- F3: world grid ------------------------------------------------------------

    def _label(self, text):
        surface = self._label_cache.get(text)
        if surface is None:
            surface = get_font("consolas", 12).render(text, True, (170, 170, 180))
            if len(self._label_cache) > 512:
                self._label_cache.clear()
            self._label_cache[text] = surface
        return surface

    def draw_grid(self, screen, camera=None, scene=None):
        """A world-space coordinate grid, drawn under everything else's
        outlines but useful for eyeballing positions/distances while
        debugging - press F3. Lines are spaced `self.grid_size` world
        pixels apart and labelled with their world coordinate; the x=0
        and y=0 axes are highlighted so the origin is easy to spot."""
        if not (self.enabled and self.show_grid):
            return

        offset_x, offset_y = self._view_offset(screen, scene, camera)
        screen_w, screen_h = screen.get_size()
        size = self.grid_size

        grid_color = (70, 70, 80)
        axis_color = (230, 100, 100)

        world_right, world_bottom = offset_x + screen_w, offset_y + screen_h

        x = math.floor(offset_x / size) * size
        while x <= world_right:
            screen_x = round(x - offset_x)
            on_axis = abs(x) < 1e-6
            pygame.draw.line(screen, axis_color if on_axis else grid_color,
                             (screen_x, 0), (screen_x, screen_h), 2 if on_axis else 1)
            screen.blit(self._label(str(int(round(x)))), (screen_x + 2, 2))
            x += size

        y = math.floor(offset_y / size) * size
        while y <= world_bottom:
            screen_y = round(y - offset_y)
            on_axis = abs(y) < 1e-6
            pygame.draw.line(screen, axis_color if on_axis else grid_color,
                             (0, screen_y), (screen_w, screen_y), 2 if on_axis else 1)
            screen.blit(self._label(str(int(round(y)))), (2, screen_y + 2))
            y += size

        # Mark the origin itself.
        origin = (round(-offset_x), round(-offset_y))
        if 0 <= origin[0] < screen_w and 0 <= origin[1] < screen_h:
            pygame.draw.circle(screen, axis_color, origin, 5, width=2)
            screen.blit(self._label("(0,0)"), (origin[0] + 8, origin[1] + 6))

    # -- F4: console ---------------------------------------------------------------

    def draw_console(self, screen):
        if not (self.enabled and self.show_console):
            return

        font = get_font("consolas", 15)
        line_height = font.get_linesize()
        padding = 6
        width = min(screen.get_width() - 20, 940)
        rows = self.console_lines
        height = padding * 2 + line_height * (rows + 1)

        logs = list(self.logs)
        end = len(logs) - self._console_scroll
        window = logs[max(0, end - rows):end]
        key = (id(logs[-1]) if logs else None, len(logs), self._console_scroll, width, rows)
        if self._console_cache is None or key != self._console_key:
            panel = pygame.Surface((width, height), pygame.SRCALPHA)
            panel.fill((10, 10, 14, 215))
            scroll_note = f"  (scrolled back {self._console_scroll})" if self._console_scroll else ""
            header = render_text(font, f"Console - {len(logs)} messages{scroll_note}", (200, 200, 210))
            panel.blit(header, (padding, padding))
            pygame.draw.line(panel, (70, 70, 85), (padding, padding + line_height),
                             (width - padding, padding + line_height))
            for i, entry in enumerate(window):
                text = f"{entry.timestamp - self._t0:7.2f} {entry.format()}"
                while font.size(text)[0] > width - padding * 2 and len(text) > 8:
                    text = text[:-4] + "..."
                color = self._LEVEL_COLORS.get(entry.level, (235, 235, 235))
                panel.blit(render_text(font, text, color), (padding, padding + line_height * (i + 1) + 2))
            self._console_cache, self._console_key = panel, key
        screen.blit(self._console_cache, (10, screen.get_height() - height - 10))


# Unity-style alias:  Debug.log("...")
Debug = DebugManager
