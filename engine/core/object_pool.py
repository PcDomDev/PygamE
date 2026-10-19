"""Object pooling: reuse instances instead of allocating/collecting them.

Creating and discarding thousands of short-lived objects (bullets, particles,
floating damage numbers) is what makes Python games stutter - the allocator
and garbage collector run at unpredictable moments. A pool creates objects
once and hands them back out:

    bullets = ObjectPool(factory=Bullet, on_spawn=Bullet.reset, initial_size=32)
    b = bullets.spawn(x, y)       # reuses an idle Bullet, or creates one
    bullets.despawn(b)            # returns it to the pool

`GameObjectPool` does the same for GameObjects living in a Scene: idle ones
stay in the scene but inactive (skipped by update, physics and rendering), so
spawning is just flipping `active` - no scene list churn.
"""
from engine.core.debug_manager import DebugManager


class ObjectPool:
    def __init__(self, factory, on_spawn=None, on_despawn=None, initial_size=0,
                 max_size=None, name="ObjectPool"):
        self.name = name
        self.factory = factory
        self.on_spawn = on_spawn
        self.on_despawn = on_despawn
        self.max_size = max_size

        self._free = []
        self._active = {}          # id(obj) -> obj  (ordered: spawn order)
        self.total_created = 0
        self.dropped = 0           # spawn() calls refused because max_size was reached

        if initial_size:
            self.prewarm(initial_size)

    # -- creation ---------------------------------------------------------------

    def _create(self):
        obj = self.factory()
        self.total_created += 1
        return obj

    def prewarm(self, count):
        """Create up to `count` idle instances now (e.g. during scene load) so
        the first spawns in gameplay don't allocate."""
        for _ in range(count):
            if self.max_size is not None and self.total_created >= self.max_size:
                break
            self._free.append(self._create())

    # -- spawn / despawn -----------------------------------------------------------

    def spawn(self, *args, **kwargs):
        """An active instance, or None if `max_size` is exhausted."""
        if self._free:
            obj = self._free.pop()
        elif self.max_size is not None and self.total_created >= self.max_size:
            self.dropped += 1
            return None
        else:
            obj = self._create()

        self._active[id(obj)] = obj
        if self.on_spawn is not None:
            self.on_spawn(obj, *args, **kwargs)
        return obj

    def despawn(self, obj):
        """Return `obj` to the pool. Returns False (and warns) if it isn't an
        active instance of this pool - e.g. a double despawn."""
        if self._active.pop(id(obj), None) is None:
            DebugManager.log_warning(f"{self.name}: despawn() of an object that isn't active in this pool.")
            return False
        if self.on_despawn is not None:
            self.on_despawn(obj)
        self._free.append(obj)
        return True

    def despawn_all(self):
        for obj in list(self._active.values()):
            self.despawn(obj)

    def forget(self, obj):
        """Drop `obj` from the pool entirely (it was destroyed elsewhere)."""
        self._active.pop(id(obj), None)
        try:
            self._free.remove(obj)
        except ValueError:
            pass

    # -- introspection ---------------------------------------------------------

    @property
    def active_count(self):
        return len(self._active)

    @property
    def free_count(self):
        return len(self._free)

    def active_objects(self):
        return list(self._active.values())

    def __len__(self):
        return len(self._active)


class GameObjectPool(ObjectPool):
    """A pool of GameObjects inside one Scene.

    `factory()` builds a fully-configured GameObject (components attached);
    the pool adds it to the scene, inactive. Components can implement
    `on_spawn(**kwargs)` / `on_despawn()` to reset their own state (the
    built-in Rigidbody2D stops moving on despawn).
    """

    def __init__(self, scene, factory, initial_size=0, max_size=None, name="GameObjectPool",
                 clear_events_on_despawn=False):
        self.scene = scene
        self.clear_events_on_despawn = clear_events_on_despawn
        super().__init__(factory, initial_size=initial_size, max_size=max_size, name=name)

    def _create(self):
        go = super()._create()
        go.pool = self
        go.active = False
        if go.scene is None:
            self.scene.add_game_object(go)
        return go

    def spawn(self, x=None, y=None, **kwargs):
        go = super().spawn()
        if go is None:
            return None
        if x is not None or y is not None:
            cur = go.transform.world_position
            go.transform.teleport(cur.x if x is None else x, cur.y if y is None else y)
        else:
            go.transform.reset_interpolation()
        for component in go.components:
            hook = getattr(component, "on_spawn", None)
            if callable(hook):
                hook(**kwargs)
        go.active = True                      # activate last: components are fully reset by now
        return go

    def despawn(self, go):
        if id(go) not in self._active:
            DebugManager.log_warning(f"{self.name}: despawn() of an object that isn't active in this pool.")
            return False
        go.active = False
        for component in go.components:
            hook = getattr(component, "on_despawn", None)
            if callable(hook):
                hook()
        if self.clear_events_on_despawn:
            go.clear_events()
        del self._active[id(go)]
        self._free.append(go)
        return True
