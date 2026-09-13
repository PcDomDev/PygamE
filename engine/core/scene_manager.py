from engine.core.debug_manager import DebugManager


class SceneManager:
    """Owns every loaded Scene by name and tracks which one is active.

    (In the original project this class existed but was never actually
    used - main.py talked to scenes/game.py's Scene directly, so
    scene_manager.py was dead code with an incompatible, half-finished API.
    It's now the real thing, and Engine owns one.)
    """

    def __init__(self):
        self.scenes = {}
        self.active_scene = None
        self._active_name = None

    def add_scene(self, name, scene):
        scene.name = name
        self.scenes[name] = scene
        return scene

    def set_active(self, name):
        if name not in self.scenes:
            DebugManager.log_error(f"SceneManager: no scene registered as '{name}'.")
            return None

        self.active_scene = self.scenes[name]
        self._active_name = name
        self.active_scene.start()
        return self.active_scene

    def get_scene(self, name):
        return self.scenes.get(name)

    def update(self, delta_time):
        if self.active_scene:
            self.active_scene.update(delta_time)

    def render(self, screen):
        if self.active_scene:
            self.active_scene.render(screen)
