class Component:
    """Base class for everything attachable to a GameObject.

    Lifecycle:
      - `start()` runs once, the moment the component's GameObject enters a
        running scene (or immediately, if attached to a GameObject that's
        already in one). Use it to grab references to sibling components.
      - `update(delta_time)` runs once per frame, as long as both the
        component and its GameObject are active/enabled.

    `update_order` controls the sequence components update in *regardless of
    the order they were attached in*. GameObject sorts by this value before
    every frame (ascending - lower runs first). The engine's built-in
    components use it like this:

        Rigidbody2D       -100   (apply physics first)
        BoxCollider2D      -90   (keep hitboxes in sync with physics)
        <gameplay code>       0   (default: PlayerController, Animator, ...)
        Camera             100   (follow *after* everything has moved)

    Relying on insertion order (the original design) meant reordering two
    `add_component()` calls could silently change behaviour - e.g. a
    PlayerController added before its Rigidbody2D would read a one-frame-old
    `is_grounded`. Sorting by an explicit, documented number removes that
    footgun and makes new components easy to slot in correctly.
    """

    update_order = 0

    def __init__(self):
        self.game_object = None
        self.enabled = True
        self._has_started = False

    def start(self):
        """Called once. Safe to call multiple times - only the first call
        does anything. Override to look up sibling components, etc."""
        if self._has_started:
            return
        self._has_started = True

    def update(self, delta_time):
        """Called once per frame while enabled. Override in subclasses."""
        pass

    def __repr__(self):
        name = getattr(self.game_object, "name", None)
        owner = f" on '{name}'" if name else ""
        return f"<{self.__class__.__name__}{owner}>"
