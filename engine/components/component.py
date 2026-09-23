import itertools

_sequence = itertools.count()


class Component:
    """Base class for everything attachable to a GameObject.

    Lifecycle hooks (override any of them; the engine only calls the ones you
    actually override, so an unused hook costs nothing per frame):

      - `start()`            once, when the owner enters a running scene (or
                             immediately if attached to an object already in one).
                             Look up sibling components here.
      - `update(dt)`         every rendered frame (variable dt). Input, animation,
                             camera, visuals.
      - `fixed_update(dt)`   every physics step (fixed dt, default 60 Hz). Apply
                             forces here; the physics step runs right after all
                             fixed_update hooks.
      - `draw_world(...)`    custom world-space drawing (particles, baked layers).
      - `on_destroy()`       once, as the owner is destroyed.

    Physics hook methods (Unity-style, optional): `on_collision_enter/stay/exit
    (collision)` and `on_trigger_enter/stay/exit(other_collider)`.

    `update_order` decides the sequence components run in - **globally across
    the whole scene**, not just within one GameObject:

        Rigidbody2D       -100   (physics bodies)
        colliders          -90
        <gameplay code>      0   (default: PlayerController, Animator, ...)
        Camera             100   (follows *after* everything has moved)

    (Before this was global, a Camera sitting on an earlier GameObject than its
    target read the target's previous-frame position and jittered.)

    `updates_when_static`: set False on components that only matter for moving
    objects (physics); they are skipped entirely on `is_static` GameObjects.
    """

    update_order = 0
    updates_when_static = True

    def __init__(self):
        self.game_object = None
        self.enabled = True
        self._has_started = False
        self._live = False              # True while registered in a running Scene
        self._reg = None                # how the Scene registered it (buckets); Scene-internal
        self._seq = next(_sequence)     # creation order: stable tie-break for sorting

    def start(self):
        """Called once. Safe to call multiple times - only the first call
        does anything. Override to look up sibling components, etc."""
        if self._has_started:
            return
        self._has_started = True

    def update(self, delta_time):
        """Called once per frame while enabled. Override in subclasses."""

    def fixed_update(self, fixed_delta_time):
        """Called once per physics step while enabled. Override in subclasses."""

    def draw_world(self, screen, offset_x, offset_y, alpha):
        """Custom world-space drawing, called by the scene's render pass in
        (z_index, sort_y) order. Return the number of blits performed (used
        for the draw-call counter), or None."""

    def on_destroy(self):
        """Called once when the owning GameObject is destroyed or this
        component is removed. Release external resources here."""

    # -- internal scene hooks (engine plumbing; subclasses register their
    #    physics/render bookkeeping here) ----------------------------------------------

    def _on_scene_enter(self, scene):
        pass

    def _on_scene_exit(self, scene):
        pass

    # -- conveniences ------------------------------------------------------------

    @property
    def transform(self):
        return self.game_object.transform

    @property
    def events(self):
        """The owning GameObject's entity-scoped event bus."""
        return self.game_object.events

    def __repr__(self):
        name = getattr(self.game_object, "name", None)
        owner = f" on '{name}'" if name else ""
        return f"<{self.__class__.__name__}{owner}>"
