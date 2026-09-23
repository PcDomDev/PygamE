from engine.components.transform import Transform
from engine.core.debug_manager import DebugManager
from engine.core.event_bus import EventBus, EventDispatcher
from engine.physics.layers import CollisionLayers


class GameObject:
    """A named container of components, optionally parented to another
    GameObject. This class intentionally has almost no behaviour of its own -
    everything an object *does* (render, collide, move, follow a target, ...)
    lives in a Component. GameObject's jobs are: own a Transform and a component
    list, carry the flags the engine schedules work by (`active`, `is_static`,
    `layer`), and provide destruction and per-entity events.

    Flags:
      - `active`: inactive objects are skipped by update, physics and rendering.
        Deactivating a parent deactivates its whole subtree (`active_in_hierarchy`).
      - `is_static`: the object will not move. Static objects skip physics and
        transform work entirely; their colliders and sprites are registered once
        instead of being re-synced every step/frame. To move one, set
        `is_static = False` first.
      - `layer`: collision layer (name or 0..31), the default for its colliders.
    """

    def __init__(self, x=0.0, y=0.0, name="GameObject", layer=0, tag=None, is_static=False, parent=None):
        self.name = name
        self.tag = tag
        self._layer = CollisionLayers.index(layer)
        self._active = True
        self._is_static = False
        self._effective_active = True
        self._effective_static = False
        self.scene = None
        self.components = []
        self._started = False
        self._sorted_components = []
        self._order_dirty = True
        self._lookup = {}
        self._hook_cache = {}
        self._events = None
        self.pool = None
        self._destroyed = False
        self._pending_destroy = False
        self._static_warned = False

        # Every GameObject owns exactly one Transform, created up front so
        # `.transform` is always valid - components should never have to
        # null-check it.
        self.transform = Transform(x, y)
        self._attach(self.transform)

        if parent is not None:
            self.set_parent(parent)
        if is_static:
            self.is_static = True

    # -- flags ------------------------------------------------------------------

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, value):
        value = bool(value)
        if value == self._active:
            return
        self._active = value
        self._refresh_flags()

    @property
    def active_in_hierarchy(self):
        """True only if this object *and every ancestor* is active."""
        return self._effective_active

    @property
    def is_static(self):
        return self._is_static

    @is_static.setter
    def is_static(self, value):
        value = bool(value)
        if value == self._is_static:
            return
        self._is_static = value
        if not value:
            self._static_warned = False
        self._refresh_flags()

    @property
    def layer(self):
        return self._layer

    @layer.setter
    def layer(self, value):
        value = CollisionLayers.index(value)
        if value == self._layer:
            return
        self._layer = value
        for component in self.components:
            hook = getattr(component, "_on_layer_changed", None)
            if hook is not None:
                hook()

    def _refresh_flags(self):
        """Recompute effective active/static from own flags + ancestors, tell
        the Scene if either changed, and cascade to children."""
        parent = self.transform._parent
        parent_go = parent.game_object if parent is not None else None
        eff_active = self._active and (parent_go is None or parent_go._effective_active)
        eff_static = self._is_static and (parent_go is None or parent_go._effective_static)
        active_changed = eff_active != self._effective_active
        static_changed = eff_static != self._effective_static
        if not active_changed and not static_changed:
            return
        self._effective_active = eff_active
        self._effective_static = eff_static
        if self.scene is not None:
            self.scene._on_flags_changed(self, active_changed, static_changed)
        for child in self.transform._children:
            child.game_object._refresh_flags()

    def _warn_static_moved(self):
        if self._static_warned:
            return
        self._static_warned = True
        DebugManager.log_warning(
            f"'{self.name}' is is_static=True but its transform changed - its collider and sprite "
            f"won't follow. Set is_static = False before moving it.", source="GameObject")

    def _on_parent_changed(self):
        self._refresh_flags()
        parent = self.parent
        if parent is not None and parent.scene is not None and self.scene is None:
            parent.scene.add_game_object(self)

    # -- hierarchy --------------------------------------------------------------

    @property
    def parent(self):
        p = self.transform._parent
        return p.game_object if p is not None else None

    @property
    def children(self):
        return [t.game_object for t in self.transform._children]

    def set_parent(self, parent, keep_world_position=False):
        """Attach to another GameObject (or None to detach). See Transform.set_parent."""
        self.transform.set_parent(parent.transform if parent is not None else None, keep_world_position)

    def add_child(self, child, keep_world_position=False):
        child.set_parent(self, keep_world_position)
        return child

    def find_child(self, name):
        for child in self.children:
            if child.name == name:
                return child
        return None

    # -- component management ------------------------------------------------

    def _attach(self, component):
        component.game_object = self
        self.components.append(component)
        self._order_dirty = True
        self._lookup.clear()
        self._hook_cache.clear()

    def add_component(self, component):
        if component.game_object is not None and component.game_object is not self:
            raise ValueError(f"{component!r} is already attached to another GameObject.")
        self._attach(component)

        if self._started:
            component.start()

        if self.scene is not None and self._effective_active:
            self.scene._register_component(component)

        return component

    def get_component(self, component_class):
        try:
            return self._lookup[component_class]
        except KeyError:
            pass
        found = None
        for component in self.components:
            if isinstance(component, component_class):
                found = component
                break
        self._lookup[component_class] = found
        return found

    def get_components(self, component_class):
        return [comp for comp in self.components if isinstance(comp, component_class)]

    def has_component(self, component_class):
        return self.get_component(component_class) is not None

    def remove_component(self, component):
        if component is self.transform:
            raise ValueError("A GameObject's Transform can't be removed.")
        if component not in self.components:
            return
        if self.scene is not None and component._live:
            self.scene._unregister_component(component)
        self.components.remove(component)
        self._order_dirty = True
        self._lookup.clear()
        self._hook_cache.clear()
        try:
            component.on_destroy()
        except Exception as exc:  # noqa: BLE001 - cleanup hooks must not crash the game
            DebugManager.log_error(f"{component!r}.on_destroy raised {exc!r}")

    def _ordered_components(self):
        """Components sorted by `update_order`, ascending. Cached and only
        re-sorted when the component list actually changes."""
        if self._order_dirty:
            self._sorted_components = sorted(self.components, key=lambda c: c.update_order)
            self._order_dirty = False
        return self._sorted_components

    def _get_hooks(self, name):
        """Bound methods named `name` on this object's components (e.g.
        "on_trigger_enter"), cached. Non-callable attributes with the same name
        (the colliders' callback *lists*) are ignored."""
        hooks = self._hook_cache.get(name)
        if hooks is None:
            hooks = []
            for component in self.components:
                fn = getattr(component, name, None)
                if fn is not None and callable(fn):
                    hooks.append(fn)
            self._hook_cache[name] = hooks
        return hooks

    # -- events --------------------------------------------------------------

    @property
    def events(self):
        """This entity's own event bus (created on first use)."""
        if self._events is None:
            self._events = EventDispatcher(self.name)
        return self._events

    def clear_events(self):
        if self._events is not None:
            self._events.clear()

    # -- lifecycle --------------------------------------------------------------

    def start(self):
        if self._started:
            return
        self._started = True
        for component in self._ordered_components():
            component.start()

    def update(self, delta_time):
        """Runs *this object's* components once, in `update_order`. The Scene
        does not use this (it schedules globally by update_order); it exists
        for driving a lone GameObject by hand, e.g. in a test."""
        if not self._effective_active:
            return
        for component in self._ordered_components():
            if component.enabled:
                component.update(delta_time)

    def destroy(self):
        """Destroy this object and its children. Inside a running scene the
        actual removal happens at the end of the current update/physics phase,
        so it's always safe to call from a collision callback or a component's
        update. `on_destroy()` is called on every component."""
        if self._destroyed or self._pending_destroy:
            return
        if self.scene is not None:
            self.scene.destroy_game_object(self)
        else:
            self._destroy_now()

    def despawn(self):
        """Return to the owning pool, or destroy if this object isn't pooled."""
        if self.pool is not None:
            self.pool.despawn(self)
        else:
            self.destroy()

    def _destroy_now(self):
        if self._destroyed:
            return
        self._destroyed = True
        self._pending_destroy = False
        for child in list(self.transform._children):
            child.game_object._destroy_now()

        if self.scene is not None:
            self.scene._remove_now(self)

        for component in list(self.components):
            try:
                component.on_destroy()
            except Exception as exc:  # noqa: BLE001 - one bad hook must not stop teardown
                DebugManager.log_error(f"{component!r}.on_destroy raised {exc!r}")
            EventBus.unsubscribe_owner(component)
        EventBus.unsubscribe_owner(self)
        if self._events is not None:
            self._events.clear()

        if self.pool is not None:
            self.pool.forget(self)
        self.transform.set_parent(None)

    # -- convenience aliases ------------------------------------------------------

    @property
    def x(self):
        return self.transform._local.x

    @x.setter
    def x(self, value):
        self.transform._local.x = value

    @property
    def y(self):
        return self.transform._local.y

    @y.setter
    def y(self, value):
        self.transform._local.y = value

    def __repr__(self):
        return f"GameObject('{self.name}')"
