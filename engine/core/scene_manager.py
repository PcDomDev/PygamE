from engine.core.debug_manager import DebugManager
from engine.core.game_time import Time


class SceneManager:
    """Static scene management: owns which Scene is running and moves between
    scenes cleanly. Everything is a classmethod - `SceneManager.change_scene(...)`
    works from anywhere, with no reference to the Engine.

        SceneManager.change_scene(Level1Scene)            # a Scene subclass...
        SceneManager.change_scene(Level1Scene, difficulty=2)   # ...with constructor args
        SceneManager.change_scene(my_scene_instance)      # ...or a ready-made instance
        SceneManager.register("menu", MenuScene)          # ...or a registered name:
        SceneManager.change_scene("menu")

    Transitions: the outgoing scene's `destroy()` runs (every object gets
    `on_destroy`, event subscriptions are dropped, physics/render structures are
    cleared - nothing lingers to be garbage-collected late), then the incoming
    scene's `start()` runs. Called while a frame is being simulated (from a
    button click, a collision callback...), the change is *deferred* to the end
    of that frame, so a scene is never torn down under its own update loop.
    Called at any other time (startup, between frames, tests) it happens at once;
    pass `immediate=True/False` to force either.

    Legacy named-scene API (what `Engine.load_scene` uses): `add_scene(name, scene)`
    and `set_active(name)` switch scenes *without* destroying the previous one,
    so a scene you registered can be switched back to with its state intact.
    (`start()` runs only the first time a scene is activated.) Remove and
    destroy a retained scene with `remove_scene(name)`.
    """

    _scenes = {}            # name -> Scene instance | Scene subclass (factory)
    active_scene = None
    _pending = None         # (target, args, kwargs, destroy_previous)
    _in_frame = False

    # -- registry ---------------------------------------------------------------

    @classmethod
    def register(cls, name, scene_or_class):
        """Register a Scene subclass (instantiated fresh on each change_scene)
        or a Scene instance under `name`."""
        cls._scenes[name] = scene_or_class
        if not isinstance(scene_or_class, type):
            scene_or_class.name = name
        return scene_or_class

    @classmethod
    def add_scene(cls, name, scene):
        """Legacy: register a scene *instance* under `name`."""
        return cls.register(name, scene)

    @classmethod
    def get_scene(cls, name):
        entry = cls._scenes.get(name)
        return None if isinstance(entry, type) else entry

    @classmethod
    def remove_scene(cls, name):
        """Forget a registered scene; a retained instance is destroyed."""
        entry = cls._scenes.pop(name, None)
        if entry is not None and not isinstance(entry, type):
            if entry is cls.active_scene:
                cls.active_scene = None
            entry.destroy()

    # -- switching ----------------------------------------------------------------

    @classmethod
    def set_active(cls, name):
        """Legacy: make the registered scene `name` active, keeping the previous
        one alive. Returns the scene, or None if `name` isn't registered."""
        if name not in cls._scenes:
            DebugManager.log_error(f"SceneManager: no scene registered as '{name}'.")
            return None
        scene = cls._resolve(name, (), {})
        return cls._activate(scene, destroy_previous=False)

    @classmethod
    def change_scene(cls, target, *args, immediate=None, destroy_previous=True, **kwargs):
        """Switch to `target` (Scene subclass, Scene instance, or registered name).
        Extra positional/keyword arguments go to the scene's constructor when
        `target` is a class. Returns the new scene if the change happened now,
        or None if it was deferred to the end of the frame."""
        if immediate is None:
            immediate = cls.active_scene is None or not cls._in_frame
        if immediate:
            return cls._activate(cls._resolve(target, args, kwargs), destroy_previous)
        cls._pending = (target, args, kwargs, destroy_previous)
        return None

    @classmethod
    def _resolve(cls, target, args, kwargs):
        if isinstance(target, str):
            entry = cls._scenes.get(target)
            if entry is None:
                raise KeyError(f"SceneManager: no scene registered as '{target}'.")
            target = entry
        if isinstance(target, type):
            scene = target(*args, **kwargs)
            if getattr(scene, "name", "Scene") == "Scene":
                scene.name = getattr(target, "scene_name", target.__name__)
            return scene
        return target

    @classmethod
    def _activate(cls, scene, destroy_previous):
        old = cls.active_scene
        if old is scene:
            return scene
        if old is not None and destroy_previous:
            old.destroy()
        cls.active_scene = scene
        scene._accumulator = 0.0
        Time.alpha = 1.0
        if not scene.is_started:
            scene.start()
            scene.is_started = True
        return scene

    @classmethod
    def _apply_pending(cls):
        if cls._pending is None:
            return
        target, args, kwargs, destroy_previous = cls._pending
        cls._pending = None
        cls._activate(cls._resolve(target, args, kwargs), destroy_previous)

    # -- per frame ----------------------------------------------------------------

    @classmethod
    def update(cls, delta_time):
        """Advance the active scene by one rendered frame (fixed physics steps +
        variable update), then apply any scene change requested during it."""
        scene = cls.active_scene
        if scene is not None:
            cls._in_frame = True
            try:
                scene.tick(delta_time)
            finally:
                cls._in_frame = False
        cls._apply_pending()

    @classmethod
    def draw(cls, screen):
        if cls.active_scene is not None:
            cls.active_scene.render(screen)

    render = draw

    # -- teardown -------------------------------------------------------------------

    @classmethod
    def shutdown(cls):
        """Destroy the active scene (Engine calls this on exit)."""
        scene = cls.active_scene
        cls.active_scene = None
        cls._pending = None
        if scene is not None:
            scene.destroy()

    @classmethod
    def reset(cls):
        """Forget everything (tests, or restarting the game from scratch)."""
        cls.shutdown()
        cls._scenes = {}
        cls._in_frame = False
