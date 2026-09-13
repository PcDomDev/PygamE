import pygame

from engine.core.debug_manager import DebugManager
from engine.input.input_manager import Input
from engine.core.scene_manager import SceneManager


class Engine:
    """Owns the window, the clock, and the main loop. This is the only
    piece of engine code main.py should need to talk to directly - scene
    content belongs in scenes/, reusable gameplay in scripts/.
    """

    # Clamp the frame delta so a debugger pause, window drag, or other lag
    # spike can't hand physics a huge dt in one go (which can fling a fast
    # rigidbody clean through a thin collider, or apply a giant burst of
    # gravity). 0.05s = a floor of 20 "effective" FPS for physics purposes,
    # even if the real frame rate momentarily drops far below that.
    MAX_DELTA_TIME = 0.05

    def __init__(self, width=1280, height=720, title="Pygame Engine", fps=60,
                 background_color=(30, 30, 35)):
        pygame.init()

        self.width = width
        self.height = height
        self.fps = fps
        self.background_color = background_color

        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)

        self.clock = pygame.time.Clock()
        self.scene_manager = SceneManager()
        self.debug = DebugManager()
        self.input = Input()

        self.running = False

    @property
    def active_scene(self):
        return self.scene_manager.active_scene

    def load_scene(self, name, scene):
        """Register `scene` under `name` and make it the active one."""
        self.scene_manager.add_scene(name, scene)
        self.scene_manager.set_active(name)
        return scene

    def run(self):
        self.running = True

        while self.running:
            raw_dt = self.clock.tick(self.fps) / 1000.0
            delta_time = min(raw_dt, self.MAX_DELTA_TIME)

            self._handle_events()
            self.input.update()
            self.debug.update(delta_time)

            if self.active_scene:
                self.active_scene.update(delta_time)

            self.screen.fill(self.background_color)
            if self.active_scene:
                self.debug.draw_grid(self.screen, self.active_scene.active_camera)
                self.active_scene.render(self.screen)
                self.debug.draw_colliders(self.screen, self.active_scene, self.active_scene.active_camera)
            self.debug.draw_overlay(self.screen, self.active_scene)

            pygame.display.flip()

        pygame.quit()

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F1:
                    self.debug.toggle_overlay()
                elif event.key == pygame.K_F2:
                    self.debug.toggle_colliders()
                elif event.key == pygame.K_F3:
                    self.debug.toggle_grid()

    def quit(self):
        self.running = False
