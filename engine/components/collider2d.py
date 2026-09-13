"""Collider2D: shared base for BoxCollider2D and CircleCollider2D.

Holds everything that doesn't depend on the actual shape - trigger state,
the on_trigger_enter/stay/exit callback lists, overlap tracking, and safe
dispatch - so both shapes participate in the exact same trigger system.
Each subclass provides:

  - `.rect` - an axis-aligned bounding box (used for broad-phase spatial
    queries and for DebugManager's collider outlines), kept up to date by
    the subclass's own update logic.
  - `.shape` - a class-level string ("box" or "circle"), and
  - `overlaps(other)` - the precise shape-vs-shape overlap test.

Dispatching by `.shape` string (rather than `isinstance(other,
BoxCollider2D)`/`isinstance(other, CircleCollider2D)`) means
box_collider2d.py and circle_collider2d.py never need to import each
other - each only needs to know its own shape's math, and reads the
other's `.shape` tag plus its public geometry (`.rect`, or `.center_x`/
`.center_y`/`.radius`) to test against it.
"""
from engine.components.component import Component


def _circle_circle_overlap(cx1, cy1, r1, cx2, cy2, r2):
    dx = cx1 - cx2
    dy = cy1 - cy2
    radius_sum = r1 + r2
    return (dx * dx + dy * dy) < (radius_sum * radius_sum)


def _circle_rect_overlap(cx, cy, radius, rect):
    # Closest point on the (axis-aligned) rect to the circle's center -
    # standard circle-vs-AABB test.
    closest_x = max(rect.left, min(cx, rect.right))
    closest_y = max(rect.top, min(cy, rect.bottom))
    dx = cx - closest_x
    dy = cy - closest_y
    return (dx * dx + dy * dy) < (radius * radius)


class Collider2D(Component):
    shape = None  # set by subclasses: "box" or "circle"

    def __init__(self, is_trigger=False):
        super().__init__()
        self.is_trigger = is_trigger
        self.rect = None  # subclasses set this in their own _update_*()
        self._last_synced_rect = None  # see _sync_spatial_hash()

        self._overlapping_colliders = set()

        # Lists of `callback(trigger, other)` - append to subscribe, more
        # than one listener is fine. See docs/CHANGELOG history: the
        # original design (a single overridable method) crashed with a
        # TypeError the instant anyone left it un-overridden.
        self.on_trigger_enter = []
        self.on_trigger_stay = []
        self.on_trigger_exit = []

    def overlaps(self, other):
        """Precise shape-vs-shape overlap test. Override in a subclass."""
        raise NotImplementedError

    @property
    def overlapping_colliders(self):
        """Read-only snapshot of colliders this one is currently (as of
        the last check_trigger_events call) overlapping. Only meaningful
        for a trigger."""
        return frozenset(self._overlapping_colliders)

    def _sync_spatial_hash(self):
        """Call this at the end of a subclass's shape/rect update - keeps
        the scene's SpatialHash (if any) matching this collider's current
        position, incrementally, so broad-phase queries never see a stale
        entry for an object that already moved earlier this same frame.

        Skips the actual remove+reinsert if the bounding box hasn't
        changed since the last sync - once an object is at rest, its rect
        is identical frame to frame, and re-registering it in the hash
        every single frame anyway would be pure overhead with nothing to
        show for it. This is purely a bookkeeping shortcut - it never
        changes what a query returns, since a rect that hasn't moved is
        already correctly placed in the hash from the last time it did.
        """
        scene = getattr(self.game_object, "scene", None)
        if scene is None or getattr(scene, "spatial_hash", None) is None:
            return

        current = (self.rect.x, self.rect.y, self.rect.width, self.rect.height)
        if current == self._last_synced_rect:
            return
        self._last_synced_rect = current
        scene.spatial_hash.update(self)

    def check_trigger_events(self, other_collider):
        if not self.is_trigger:
            return

        is_touching = self.overlaps(other_collider)
        was_touching = other_collider in self._overlapping_colliders

        if is_touching and not was_touching:
            self._overlapping_colliders.add(other_collider)
            self._dispatch(self.on_trigger_enter, other_collider)
        elif is_touching and was_touching:
            self._dispatch(self.on_trigger_stay, other_collider)
        elif not is_touching and was_touching:
            self._overlapping_colliders.remove(other_collider)
            self._dispatch(self.on_trigger_exit, other_collider)

    def _dispatch(self, callbacks, other_collider):
        from engine.core.debug_manager import DebugManager  # avoids a cycle: debug_manager imports colliders for outlines

        for callback in list(callbacks):  # copy: a callback may unsubscribe itself
            try:
                callback(self, other_collider)
            except Exception as exc:  # noqa: BLE001 - a bad user callback must not crash the game
                owner = getattr(self.game_object, "name", "?")
                DebugManager.log_error(f"Trigger callback on '{owner}' raised {exc!r}")
