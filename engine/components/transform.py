import math

from engine.components.component import Component
from engine.core.game_time import Time
from engine.utils.vector2 import Vector2

_set_x = Vector2.x.__set__
_set_y = Vector2.y.__set__


class _WatchedVector2(Vector2):
    """A Vector2 that tells its Transform whenever x or y is written.

    This is what lets `transform.position.x += 5` (in-place mutation, the
    pattern the whole engine uses) keep the hierarchy's cached world values
    honest without polling. Reads are as fast as a plain Vector2 (slot access);
    only writes pay for the notification. Arithmetic (`a + b`, `.copy()`)
    returns ordinary Vector2s.
    """

    __slots__ = ("_owner",)

    def __init__(self, x, y, owner):
        _set_x(self, x)
        _set_y(self, y)
        object.__setattr__(self, "_owner", owner)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name == "x" or name == "y":
            self._owner._local_changed()

    def set_xy(self, x, y):
        """Set both components with a single change notification."""
        _set_x(self, x)
        _set_y(self, y)
        self._owner._local_changed()


class Transform(Component):
    """Position, rotation, scale - and the parent/child hierarchy.

    Every GameObject gets exactly one of these automatically.

    Local vs world:
      - `local_position` / `rotation` / `scale` are relative to the parent
        (or to the world when there is no parent). These are the stored values.
      - `world_position` / `world_rotation` / `world_scale` are the composed
        result (parent's world transform applied to the local one).
      - `position` is an alias of `local_position`. For an object without a
        parent - which is every object unless you call `set_parent` - local
        and world are identical, so code written before the hierarchy existed
        behaves exactly as before.

    Rotation is in degrees, clockwise-positive on screen (Y points down).

    Caching: world values are computed lazily and cached behind an `is_dirty`
    flag. Changing a transform marks it and its whole subtree dirty (O(subtree),
    only if it wasn't already dirty); reading a world value recomputes it only
    if dirty. An object that isn't moving - and neither is anything above it -
    never recomputes anything, no matter how often it's read.

    Interpolation (see Rigidbody2D): physics moves bodies in fixed steps; for
    smooth rendering on high-refresh displays `get_render_xy(alpha)` blends
    between the previous and current step. Children of an interpolated root
    are composed from the parent's *render* position, so a weapon held by a
    player stays glued to it.
    """

    def __init__(self, x=0.0, y=0.0, rotation=0.0, scale_x=1.0, scale_y=1.0):
        super().__init__()
        self._parent = None
        self._children = []
        self._dirty = True
        self._world_version = 0
        self._interpolate = False
        self._interp_active = False
        self._external_move = False

        self._local = _WatchedVector2(x, y, self)
        self._scale = _WatchedVector2(scale_x, scale_y, self)
        self._rotation = float(rotation)

        self._world_x = float(x)
        self._world_y = float(y)
        self._world_rot = float(rotation)
        self._world_sx = float(scale_x)
        self._world_sy = float(scale_y)
        self._wcos = 1.0
        self._wsin = 0.0
        self._prev_x = self._world_x
        self._prev_y = self._world_y

    # -- change tracking ---------------------------------------------------------

    def _local_changed(self):
        if not self._dirty:
            self._dirty = True
            for child in self._children:
                child._mark_dirty()
        if self._interp_active and not Time.in_fixed_step:
            # Moved by gameplay code between physics steps: a teleport as far
            # as interpolation is concerned - never smear it across frames.
            self._external_move = True
        go = self.game_object
        if go is not None and go._effective_static and go.scene is not None:
            go._warn_static_moved()

    def _mark_dirty(self):
        # Invariant: a dirty node's descendants are all dirty, so a node that
        # is already dirty needs no propagation.
        if self._dirty:
            return
        self._dirty = True
        for child in self._children:
            child._mark_dirty()

    def _ensure_world(self):
        if not self._dirty:
            return
        parent = self._parent
        local = self._local
        scale = self._scale
        if parent is None:
            self._world_x = local.x
            self._world_y = local.y
            self._world_rot = self._rotation
            self._world_sx = scale.x
            self._world_sy = scale.y
        else:
            parent._ensure_world()
            psx = parent._world_sx
            psy = parent._world_sy
            lx = local.x * psx
            ly = local.y * psy
            if parent._world_rot:
                c = parent._wcos
                s = parent._wsin
                self._world_x = parent._world_x + lx * c - ly * s
                self._world_y = parent._world_y + lx * s + ly * c
            else:
                self._world_x = parent._world_x + lx
                self._world_y = parent._world_y + ly
            self._world_rot = parent._world_rot + self._rotation
            self._world_sx = psx * scale.x
            self._world_sy = psy * scale.y

        if self._world_rot:
            radians = math.radians(self._world_rot)
            self._wcos = math.cos(radians)
            self._wsin = math.sin(radians)
        else:
            self._wcos = 1.0
            self._wsin = 0.0
        self._dirty = False
        self._world_version += 1

    @property
    def is_dirty(self):
        """True if cached world values are stale (they'll be recomputed on next read)."""
        return self._dirty

    @property
    def world_version(self):
        """Increments every time the world values are recomputed - compare it
        to detect "did this object move?" without comparing positions."""
        self._ensure_world()
        return self._world_version

    # -- local values ---------------------------------------------------------

    @property
    def position(self):
        return self._local

    @position.setter
    def position(self, value):
        if value is not self._local:
            self._local.set_xy(value.x, value.y)

    local_position = position

    @property
    def rotation(self):
        return self._rotation

    @rotation.setter
    def rotation(self, value):
        value = float(value)
        if value != self._rotation:
            self._rotation = value
            self._local_changed()

    local_rotation = rotation

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, value):
        if value is self._scale:
            return
        if isinstance(value, (int, float)):
            self._scale.set_xy(value, value)
        else:
            self._scale.set_xy(value.x, value.y)

    local_scale = scale

    def translate(self, dx, dy):
        """Move by (dx, dy) in the parent's space."""
        local = self._local
        local.set_xy(local.x + dx, local.y + dy)

    # -- world values ----------------------------------------------------------

    @property
    def world_x(self):
        if self._dirty:
            self._ensure_world()
        return self._world_x

    @property
    def world_y(self):
        if self._dirty:
            self._ensure_world()
        return self._world_y

    def get_world_xy(self):
        if self._dirty:
            self._ensure_world()
        return self._world_x, self._world_y

    @property
    def world_position(self):
        """The world-space position as a *copy*. Assign to move the object:
        `t.world_position = Vector2(...)` (mutating the copy does nothing)."""
        if self._dirty:
            self._ensure_world()
        return Vector2(self._world_x, self._world_y)

    @world_position.setter
    def world_position(self, value):
        self.set_world_position(value.x, value.y)

    def set_world_position(self, x, y):
        parent = self._parent
        if parent is None:
            self._local.set_xy(x, y)
            return
        parent._ensure_world()
        dx = x - parent._world_x
        dy = y - parent._world_y
        if parent._world_rot:
            c = parent._wcos
            s = parent._wsin
            dx, dy = dx * c + dy * s, -dx * s + dy * c
        self._local.set_xy(dx / (parent._world_sx or 1.0), dy / (parent._world_sy or 1.0))

    @property
    def world_rotation(self):
        if self._dirty:
            self._ensure_world()
        return self._world_rot

    @property
    def world_scale(self):
        if self._dirty:
            self._ensure_world()
        return Vector2(self._world_sx, self._world_sy)

    def transform_point(self, x, y):
        """A point given in this transform's local space, as a world-space Vector2."""
        self._ensure_world()
        lx = x * self._world_sx
        ly = y * self._world_sy
        if self._world_rot:
            c, s = self._wcos, self._wsin
            return Vector2(self._world_x + lx * c - ly * s, self._world_y + lx * s + ly * c)
        return Vector2(self._world_x + lx, self._world_y + ly)

    def inverse_transform_point(self, x, y):
        """A world-space point, expressed in this transform's local space."""
        self._ensure_world()
        dx = x - self._world_x
        dy = y - self._world_y
        if self._world_rot:
            c, s = self._wcos, self._wsin
            dx, dy = dx * c + dy * s, -dx * s + dy * c
        return Vector2(dx / (self._world_sx or 1.0), dy / (self._world_sy or 1.0))

    # -- interpolation ---------------------------------------------------------

    @property
    def interpolate(self):
        return self._interpolate

    @interpolate.setter
    def interpolate(self, value):
        self._interpolate = bool(value)
        self._refresh_interp()

    def _refresh_interp(self):
        parent = self._parent
        active = parent._interp_active if parent is not None else self._interpolate
        if active == self._interp_active:
            return
        self._interp_active = active
        if active:
            self.reset_interpolation()
        for child in self._children:
            child._refresh_interp()

    def reset_interpolation(self):
        """Forget the previous physics-step position (previous := current), so
        the next rendered frame shows the object exactly where it is."""
        self._ensure_world()
        self._prev_x = self._world_x
        self._prev_y = self._world_y
        self._external_move = False

    def teleport(self, x, y):
        """Move to a world position *without* being interpolated across the gap."""
        self.set_world_position(x, y)
        self.reset_interpolation()

    def get_render_xy(self, alpha):
        """World position to draw at, given the interpolation factor `alpha`
        (fraction of a physics step elapsed). Equal to the world position for
        anything that isn't physics-driven."""
        if self._dirty:
            self._ensure_world()
        if not self._interp_active or alpha >= 1.0:
            return self._world_x, self._world_y

        parent = self._parent
        if parent is None:
            if self._external_move:
                self._external_move = False
                self._prev_x = self._world_x
                self._prev_y = self._world_y
                return self._world_x, self._world_y
            px = self._prev_x
            py = self._prev_y
            return px + (self._world_x - px) * alpha, py + (self._world_y - py) * alpha

        rx, ry = parent.get_render_xy(alpha)
        local = self._local
        lx = local.x * parent._world_sx
        ly = local.y * parent._world_sy
        if parent._world_rot:
            c, s = parent._wcos, parent._wsin
            return rx + lx * c - ly * s, ry + lx * s + ly * c
        return rx + lx, ry + ly

    @property
    def render_position(self):
        return Vector2(*self.get_render_xy(Time.alpha))

    # -- hierarchy --------------------------------------------------------------

    @property
    def parent(self):
        return self._parent

    @parent.setter
    def parent(self, value):
        self.set_parent(value)

    @property
    def children(self):
        return tuple(self._children)

    @property
    def child_count(self):
        return len(self._children)

    @property
    def root(self):
        node = self
        while node._parent is not None:
            node = node._parent
        return node

    @property
    def depth(self):
        depth = 0
        node = self._parent
        while node is not None:
            depth += 1
            node = node._parent
        return depth

    def set_parent(self, parent, keep_world_position=False):
        """Attach to `parent` (a Transform, a GameObject, or None to detach).

        By default the *local* values are kept, so the object jumps to the same
        offset relative to its new parent (what you want for "attach the sword
        to the player at (20, 0)"). With `keep_world_position=True` the local
        values are recomputed so the object stays where it is in the world.
        """
        if parent is not None and not isinstance(parent, Transform):
            parent = parent.transform
        if parent is self._parent:
            return

        ancestor = parent
        while ancestor is not None:
            if ancestor is self:
                raise ValueError("Transform.set_parent: this would make an object its own ancestor.")
            ancestor = ancestor._parent

        kept = None
        if keep_world_position:
            self._ensure_world()
            kept = (self._world_x, self._world_y, self._world_rot, self._world_sx, self._world_sy)

        if self._parent is not None:
            self._parent._children.remove(self)
        self._parent = parent
        if parent is not None:
            parent._children.append(self)
        self._refresh_interp()
        self._mark_dirty()

        if kept is not None:
            wx, wy, wrot, wsx, wsy = kept
            if parent is None:
                self._rotation = wrot
                self._scale.set_xy(wsx, wsy)
                self._local.set_xy(wx, wy)
            else:
                parent._ensure_world()
                self._rotation = wrot - parent._world_rot
                self._scale.set_xy(wsx / (parent._world_sx or 1.0), wsy / (parent._world_sy or 1.0))
                self.set_world_position(wx, wy)

        go = self.game_object
        if go is not None:
            go._on_parent_changed()

    def detach(self, keep_world_position=True):
        self.set_parent(None, keep_world_position=keep_world_position)

    def __repr__(self):
        return f"Transform(pos={self._local}, rot={self._rotation:.1f}, scale={self._scale})"
