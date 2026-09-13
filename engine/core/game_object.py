from engine.components.transform import Transform


class GameObject:
    """A named container of components. This class intentionally has almost
    no behaviour of its own - everything an object *does* (render, collide,
    move, follow a target, ...) lives in a Component. GameObject's only
    jobs are: own a Transform, own a component list, and run each
    component's start()/update() in a well-defined order.
    """

    def __init__(self, x=0.0, y=0.0, name="GameObject"):
        self.name = name
        self._active = True
        self.scene = None
        self.components = []
        self._started = False

        self._sorted_components = []
        self._order_dirty = True

        # Every GameObject owns exactly one Transform, created up front so
        # `.transform` is always valid - components should never have to
        # null-check it.
        self.transform = Transform(x, y)
        self._attach(self.transform)

    # -- active flag ----------------------------------------------------------
    # A property (not a plain attribute) so toggling it can notify the
    # owning Scene - which keeps Scene's component cache and SpatialHash
    # correct without either needing to poll every object every frame to
    # notice a change. See Scene._on_active_changed().

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, value):
        if value == self._active:
            return
        self._active = value
        if self.scene is not None:
            self.scene._on_active_changed(self)

    # -- component management ------------------------------------------------

    def _attach(self, component):
        component.game_object = self
        self.components.append(component)
        self._order_dirty = True

    def add_component(self, component):
        self._attach(component)

        if self._started:
            component.start()

        if self.scene is not None:
            self.scene._invalidate_component_cache()

        return component

    def get_component(self, component_class):
        for component in self.components:
            if isinstance(component, component_class):
                return component
        return None

    def get_components(self, component_class):
        return [comp for comp in self.components if isinstance(comp, component_class)]

    def remove_component(self, component):
        if component in self.components:
            self.components.remove(component)
            self._order_dirty = True
            if self.scene is not None:
                self.scene._invalidate_component_cache()

    def _ordered_components(self):
        """Components sorted by `update_order`, ascending. Cached and only
        re-sorted when the component list actually changes, so this is
        cheap to call every frame."""
        if self._order_dirty:
            self._sorted_components = sorted(self.components, key=lambda c: c.update_order)
            self._order_dirty = False
        return self._sorted_components

    # -- lifecycle --------------------------------------------------------------

    def start(self):
        if self._started:
            return
        self._started = True
        for component in self._ordered_components():
            component.start()

    def update(self, delta_time):
        if not self.active:
            return

        for component in self._ordered_components():
            if component.enabled:
                component.update(delta_time)

    # -- convenience aliases ------------------------------------------------------

    @property
    def x(self):
        return self.transform.position.x

    @x.setter
    def x(self, value):
        self.transform.position.x = value

    @property
    def y(self):
        return self.transform.position.y

    @y.setter
    def y(self, value):
        self.transform.position.y = value

    def __repr__(self):
        return f"GameObject('{self.name}')"
