"""A uniform grid for fast "what's near this rect" broad-phase queries.

Without this, Rigidbody2D asks the Scene for every solid collider in the
whole scene, on every axis, for every rigidbody, every frame - an O(n)
scan repeated roughly 2n times a frame, i.e. O(n^2) overall. That's fine
for a handful of objects and clearly noticeable (frame-rate-dropping) once
a scene has a few hundred. SpatialHash buckets colliders into fixed-size
cells so a query only has to look at colliders sharing a cell with the
query rect - for reasonably spread-out objects this turns collision
broad-phase into roughly O(n) overall instead of O(n^2).

This is *broad*-phase only: query() returns candidates that MIGHT overlap
(anything sharing a cell), never a guarantee - callers still run an exact
test (BoxCollider2D.rect.colliderect(), Collider2D.overlaps(), etc.) on
whatever comes back.

Kept up to date incrementally (update()/remove() as each collider's shape
changes, not a single rebuild-once-per-frame) specifically so it never
goes stale *within* a single frame - if object B already moved earlier
this frame, object A's query later in the same frame must see B's new
position, not a snapshot from before the frame started. See
Collider2D._update_rect()/_update_shape(), which call update() every time
a collider's shape/position is recomputed.
"""


class SpatialHash:
    def __init__(self, cell_size=128):
        self.cell_size = cell_size
        self._cells = {}           # (cx, cy) -> set of colliders
        self._collider_cells = {}  # collider -> set of (cx, cy) it's currently registered in

    def clear(self):
        self._cells.clear()
        self._collider_cells.clear()

    def _cells_for_rect(self, rect):
        cs = self.cell_size
        min_cx, max_cx = rect.left // cs, rect.right // cs
        min_cy, max_cy = rect.top // cs, rect.bottom // cs
        return [(cx, cy) for cx in range(min_cx, max_cx + 1) for cy in range(min_cy, max_cy + 1)]

    def update(self, collider):
        """(Re)insert `collider` to match its current `.rect`. Safe to call
        every frame regardless of whether it actually moved - cheap no-op
        cost aside, correctness never depends on skipping this."""
        self.remove(collider)
        cells = self._cells_for_rect(collider.rect)
        for cell in cells:
            self._cells.setdefault(cell, set()).add(collider)
        self._collider_cells[collider] = set(cells)

    def remove(self, collider):
        old_cells = self._collider_cells.pop(collider, None)
        if not old_cells:
            return
        for cell in old_cells:
            bucket = self._cells.get(cell)
            if bucket is not None:
                bucket.discard(collider)
                if not bucket:
                    del self._cells[cell]

    def query(self, rect):
        """Every collider sharing a cell with `rect` - a broad-phase
        candidate set. Always confirm with an exact overlap test."""
        result = set()
        for cell in self._cells_for_rect(rect):
            result.update(self._cells.get(cell, ()))
        return result
