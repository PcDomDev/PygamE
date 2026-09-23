from time import perf_counter

import pygame

from engine.audio.audio_manager import AudioManager
from engine.core.debug_manager import DebugManager
from engine.core.game_time import Time
from engine.core.player_prefs import PlayerPrefs
from engine.core.scene_manager import SceneManager
from engine.input.input_manager import Input


class Engine:
    """Owns the window, the clock, and the main loop. This is the only
    piece of engine code main.py should need to talk to directly - scene
    content belongs in scenes/, reusable gameplay in scripts/.

    The loop, once per rendered frame:

        events -> Input          (presses/releases/wheel as pygame delivers them)
        debug hotkeys            (F1 stats, F2 gizmos, F3 grid, F4 console)
        SceneManager.update()    fixed physics steps (60 Hz, catch-up on lag)
                                 then the variable update, then any scene change
        AudioManager.update()    fades and volume refresh
        draw                     background -> grid -> scene (world, UI) -> gizmos
                                 -> stats -> console -> flip

    Parameters beyond the window basics:
      fps          frame cap (0 = uncapped; use vsync or a high value for 144 Hz+ displays)
      fixed_fps    physics rate in Hz (default 60)
      vsync        ask for a vsynced display (needs pygame 2; implies the SCALED flag)
      resizable    let the user resize the window
      debug        False disables all debug hotkeys and overlays (release builds)
    """

    # Clamp on the *variable* update step so a debugger pause, window drag, or
    # other lag spike can't hand gameplay code a huge dt in one go. (Physics no
    # longer depends on this: it runs in fixed steps, and its own catch-up is
    # bounded by Time.max_frame_time / Time.max_fixed_steps.)
    MAX_DELTA_TIME = 0.05

    def __init__(self, width=1280, height=720, title="Pygame Engine", fps=60,
                 background_color=(30, 30, 35), fixed_fps=60, vsync=False,
                 resizable=False, debug=True):
        pygame.init()

        self.width = width
        self.height = height
        self.fps = fps
        self.background_color = background_color

        flags = pygame.RESIZABLE if resizable else 0
        if vsync:
            flags |= pygame.SCALED
        try:
            self.screen = pygame.display.set_mode((width, height), flags, vsync=1 if vsync else 0)
        except TypeError:               # pygame 1.x has no vsync argument
            self.screen = pygame.display.set_mode((width, height), flags)
        pygame.display.set_caption(title)

        Time.reset()
        Time.set_fixed_rate(fixed_fps)

        self.clock = pygame.time.Clock()
        self.scene_manager = SceneManager      # static: the class itself is the manager
        self.debug = DebugManager(enabled=debug)
        self.input = Input()
        self.audio = AudioManager

        self.running = False

    @property
    def active_scene(self):
        return self.scene_manager.active_scene

    def load_scene(self, name, scene):
        """Register `scene` under `name` and make it the active one (the
        previous scene, if any, is kept alive - see SceneManager.set_active)."""
        self.scene_manager.add_scene(name, scene)
        self.scene_manager.set_active(name)
        return scene

    def change_scene(self, target, *args, **kwargs):
        """`SceneManager.change_scene`: switch scenes, destroying the old one."""
        return self.scene_manager.change_scene(target, *args, **kwargs)

    def run(self):
        self.running = True
        Time.max_delta_time = self.MAX_DELTA_TIME
        try:
            while self.running:
                raw_dt = self.clock.tick(self.fps) / 1000.0

                self._process_events()
                self.debug.handle_input()
                self.debug.update(raw_dt)

                self.scene_manager.update(raw_dt)
                AudioManager.update(raw_dt)

                draw_start = perf_counter()
                self.screen.fill(self.background_color)
                scene = self.active_scene
                if scene:
                    self.debug.draw_grid(self.screen, scene.active_camera, scene)
                    self.scene_manager.draw(self.screen)
                    self.debug.draw_colliders(self.screen, scene, scene.active_camera)
                self.debug.draw_overlay(self.screen, scene)
                self.debug.draw_console(self.screen)
                self.debug.record("draw", (perf_counter() - draw_start) * 1000.0)

                pygame.display.flip()
        finally:
            self._shutdown()

    def _process_events(self):
        self.input.begin_frame()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            self.input.process_event(event)
        self.input.update()

    def _shutdown(self):
        """Orderly exit: destroy the scene (on_destroy hooks run), stop audio,
        save PlayerPrefs if there are unsaved changes (Unity does the same), quit pygame."""
        try:
            self.scene_manager.shutdown()
            AudioManager.shutdown()
            if PlayerPrefs.is_dirty():
                PlayerPrefs.save()
        finally:
            pygame.quit()

    def quit(self):
        self.running = False
