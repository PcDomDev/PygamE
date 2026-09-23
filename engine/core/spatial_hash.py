"""A uniform grid for fast "what's near this box" broad-phase queries.

Used twice per Scene: colliders register here for physics/trigger queries, and
static sprites register in a second instance for camera-visibility queries.
Only *broad*-phase: query results are candidates that share a grid cell with
the query box; callers still run an exact test on them.

Design notes:
  - Items are registered with explicit float bounds (`update_bounds`), so
    physics can use exact float geometry instead of pixel-rounded Rects.
  - An item's cell range is compared before touching the grid: an object that
    moved but stayed inside the same cells costs one tuple comparison.
  - Cells are insertion-ordered dicts, not sets, so iteration order never
    depends on object memory addresses - simulations stay deterministic.
  - An item spanning more than MAX_CELLS cells (a level-sized trigger, say) is
    kept in a small "oversized" list checked on every query instead of being
    registered in thousands of cells.
"""
import math

MAX_CELLS_PER_ITEM = 256


class SpatialHash:
    def __init__(self, cell_size=128):
        if cell_size <= 0:
            raise ValueError("SpatialHash cell_size must be > 0")
        self.cell_size = cell_size
        self._inv = 1.0 / cell_size
        self._cells = {}       # (cx, cy) -> {item: None}
        self._entries = {}     # item -> (cx0, cy0, cx1, cy1)
        self._oversized = {}   # item -> (left, top, right, bottom)

    def __len__(self):
        return len(self._entries) + len(self._oversized)

    def __contains__(self, item):
        return item in self._entries or item in self._oversized

    def clear(self):
        self._cells.clear()
        self._entries.clear()
        self._oversized.clear()

    # -- registration --------------------------------------------------------------

    def update_bounds(self, item, left, top, right, bottom):
        """(Re)register `item` at the given float bounds. Returns True if the
        item's grid footprint changed (False = nothing to do)."""
        inv = self._inv
        cx0 = math.floor(left * inv)
        cy0 = math.floor(top * inv)
        cx1 = math.floor(right * inv)
        cy1 = math.floor(bottom * inv)

        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > MAX_CELLS_PER_ITEM:
            if item in self._entries:
                self._remove_from_cells(item, self._entries.pop(item))
            self._oversized[item] = (left, top, right, bottom)
            return True

        if item in self._oversized:
            del self._oversized[item]

        new = (cx0, cy0, cx1, cy1)
        old = self._entries.get(item)
        if old == new:
            return False
        if old is not None:
            self._remove_from_cells(item, old)
        self._entries[item] = new

        cells = self._cells
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                bucket = cells.get((cx, cy))
                if bucket is None:
                    cells[(cx, cy)] = {item: None}
                else:
                    bucket[item] = None
        return True

    def update(self, item, rect=None):
        """Legacy form: register `item` at `rect` (a pygame.Rect), or at
        `item.rect` when omitted."""
        rect = item.rect if rect is None else rect
        return self.update_bounds(item, rect.left, rect.top, rect.right, rect.bottom)

    def remove(self, item):
        cells = self._entries.pop(item, None)
        if cells is not None:
            self._remove_from_cells(item, cells)
        self._oversized.pop(item, None)

    def _remove_from_cells(self, item, cell_range):
        cx0, cy0, cx1, cy1 = cell_range
        cells = self._cells
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                bucket = cells.get((cx, cy))
                if bucket is not None:
                    bucket.pop(item, None)
                    if not bucket:
                        del cells[(cx, cy)]

    # -- queries ---------------------------------------------------------------

    def query_bounds(self, left, top, right, bottom):
        """Candidate items near the box, as a de-duplicated list in a
        deterministic order."""
        inv = self._inv
        cx0 = math.floor(left * inv)
        cy0 = math.floor(top * inv)
        cx1 = math.floor(right * inv)
        cy1 = math.floor(bottom * inv)
        cells = self._cells

        if cx0 == cx1 and cy0 == cy1:
            bucket = cells.get((cx0, cy0))
            result = list(bucket) if bucket else []
        else:
            merged = {}
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    bucket = cells.get((cx, cy))
                    if bucket:
                        merged.update(bucket)
            result = list(merged)

        if self._oversized:
            for item, (l, t, r, b) in self._oversized.items():
                if l <= right and r >= left and t <= bottom and b >= top and item not in result:
                    result.append(item)
        return result

    def query(self, rect):
        """Legacy form: a *set* of candidates near a pygame.Rect."""
        return set(self.query_bounds(rect.left, rect.top, rect.right, rect.bottom))

    def items(self):
        return list(self._entries) + list(self._oversized)
