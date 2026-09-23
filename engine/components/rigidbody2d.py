import math

from engine.components.box_collider2d import BoxCollider2D
from engine.components.component import Component
from engine.core.debug_manager import DebugManager
from engine.utils.vector2 import Vector2

# Two edges closer than this count as touching. It is also how deep an overlap
# may get before depenetration kicks in, so resting contact is stable.
_TOL = 0.01

# Extra room around a body's motion path in its one per-step broad-phase query,
# so small depenetration shifts don't need a second query.
_QUERY_MARGIN = 2.0


class Rigidbody2D(Component):
    """Velocity, acceleration, gravity, drag, friction and mass, with
    swept-AABB collision against solid BoxCollider2Ds.

    Runs in the **fixed** physics step (`Time.fixed_delta_time`, 60 Hz by
    default), never in the variable `update()`: the same inputs always produce
    the same motion no matter what the frame rate does, and a frame-time spike
    just means several steps run back to back.

    Movement is resolved one axis at a time (X, then Y), and each axis move is
    *swept*: the body travels only as far as the nearest obstacle in its path,
    then stops exactly flush against it. Consequences:
      - no tunneling, at any speed - a fast body cannot skip over a thin wall;
      - no landing jitter and no "ground probe" fudge - resting on a surface is
        an exact zero-gap contact, so `is_grounded` is stable frame to frame;
      - sliding along walls and floors works naturally.

    Per-step order: forces/acceleration/gravity -> drag -> ground friction ->
    terminal velocity -> depenetration -> swept move X -> swept move Y.

    Units are pixels and seconds. Parameters:
      gravity, gravity_scale   downward acceleration (px/s^2) and a per-body multiplier
      drag                     linear air drag, 1/s (velocity decays like exp(-drag*t)), both axes
      friction                 ground friction coefficient: while grounded, horizontal velocity
                               decelerates by friction * gravity px/s^2 (0 = frictionless)
      mass                     divides forces and impulses
      acceleration             constant extra acceleration (Vector2, px/s^2), e.g. wind or thrust
      is_kinematic             moves by `velocity`, ignores forces and collisions (moving platforms,
                               bullets) - still fires trigger/collision events
      interpolate              render smoothly between physics steps (see Transform)

    Limits worth knowing: bodies only stop against `BoxCollider2D` obstacles
    (circles are trigger/overlap-only), a dynamic body treats other bodies as
    immovable walls (no momentum transfer), and kinematic platforms don't carry
    riders. Put a Rigidbody2D on a root object; on a child it works in the
    parent's local space and is only correct if the parent doesn't move.
    """

    update_order = -100
    updates_when_static = False   # static objects are never simulated
    _is_rigidbody = True

    # Kept for API compatibility: contact detection now uses exact swept
    # geometry, so no probe distance is needed to keep is_grounded stable.
    GROUND_PROBE_DISTANCE = 0

    def __init__(self, gravity=500, gravity_scale=1.0, drag=0.0, mass=1.0,
                 use_gravity=True, is_kinematic=False, terminal_velocity=1000,
                 friction=0.0, acceleration=None, interpolate=True):
        super().__init__()
        self.velocity = Vector2(0.0, 0.0)
        if acceleration is None:
            self.acceleration = Vector2(0.0, 0.0)
        elif isinstance(acceleration, Vector2):
            self.acceleration = acceleration.copy()
        else:
            self.acceleration = Vector2(*acceleration)

        self.gravity = gravity
        self.gravity_scale = gravity_scale
        self.drag = drag
        self.friction = friction
        self.mass = mass if mass > 0 else 1.0

        self.use_gravity = use_gravity
        self.is_kinematic = is_kinematic
        self.terminal_velocity = terminal_velocity
        self.interpolate = interpolate

        self.is_grounded = False
        self.collider = None
        self._fx = 0.0
        self._fy = 0.0
        self._world = None

    def start(self):
        self.collider = self.game_object.get_component(BoxCollider2D)
        if self.collider is None:
            DebugManager.log_warning(
                f"Rigidbody2D on '{self.game_object.name}' has no BoxCollider2D - "
                f"gravity/velocity will apply but nothing will collide."
            )
        transform = self.game_object.transform
        if transform.parent is not None:
            DebugManager.log_warning(
                f"Rigidbody2D on '{self.game_object.name}' is on a child object: it moves in its "
                f"parent's local space, which is only correct while the parent doesn't move.")
        elif self.interpolate:
            transform.interpolate = True

    # -- scene registration -------------------------------------------------------

    def _on_scene_enter(self, scene):
        self._world = scene.physics
        scene.physics.add_body(self)
        for component in self.game_object.components:
            if hasattr(component, "_body") and hasattr(component, "shape"):
                component._body = self
        self.game_object.transform.reset_interpolation()

    def _on_scene_exit(self, scene):
        scene.physics.remove_body(self)
        for component in self.game_object.components:
            if getattr(component, "_body", None) is self:
                component._body = None
        self._world = None

    # -- pooling hooks -----------------------------------------------------------

    def on_spawn(self, **kwargs):
        self.stop()
        self.is_grounded = False

    def on_despawn(self):
        self.stop()

    # -- back-compat scalar accessors -----------------------------------------------

    @property
    def velocity_x(self):
        return self.velocity.x

    @velocity_x.setter
    def velocity_x(self, value):
        self.velocity.x = value

    @property
    def velocity_y(self):
        return self.velocity.y

    @velocity_y.setter
    def velocity_y(self, value):
        self.velocity.y = value

    # -- forces -----------------------------------------------------------------

    def add_impulse(self, impulse_x, impulse_y):
        """Instant change in velocity: delta_v = impulse / mass."""
        if self.is_kinematic:
            return
        self.velocity.x += impulse_x / self.mass
        self.velocity.y += impulse_y / self.mass

    def add_force(self, force_x, force_y, delta_time=None):
        """Apply a force (in px*mass/s^2).

        Without `delta_time` (the normal form) the force is accumulated and
        integrated by the next physics step - call it every frame or every
        `fixed_update` for a sustained push; it is cleared after each step.
        Passing `delta_time` keeps the legacy behaviour of an immediate
        `velocity += force / mass * delta_time`.
        """
        if self.is_kinematic:
            return
        if delta_time is not None:
            self.velocity.x += (force_x / self.mass) * delta_time
            self.velocity.y += (force_y / self.mass) * delta_time
        else:
            self._fx += force_x
            self._fy += force_y

    def stop(self):
        self.velocity.x = 0.0
        self.velocity.y = 0.0
        self._fx = 0.0
        self._fy = 0.0

    def teleport(self, x, y):
        """Move to a world position and clear velocity, without interpolating across the gap."""
        self.game_object.transform.teleport(x, y)
        self.stop()

    # -- simulation ---------------------------------------------------------------

    def _simulate(self, dt):
        """One fixed physics step. Called by PhysicsWorld.step()."""
        transform = self.game_object.transform
        local = transform._local
        if transform._interp_active:
            transform.reset_interpolation()   # previous := where we are now
        velocity = self.velocity

        if self.is_kinematic:
            if velocity.x or velocity.y:
                local.set_xy(local.x + velocity.x * dt, local.y + velocity.y * dt)
            collider = self.collider
            if collider is not None:
                collider.refresh()
            return

        inv_mass = 1.0 / self.mass
        ax = self.acceleration.x + self._fx * inv_mass
        ay = self.acceleration.y + self._fy * inv_mass
        self._fx = 0.0
        self._fy = 0.0
        g = self.gravity * self.gravity_scale if self.use_gravity else 0.0
        ay += g

        vx = velocity.x + ax * dt
        vy = velocity.y + ay * dt

        if self.drag > 0:
            damping = math.exp(-self.drag * dt)
            vx *= damping
            vy *= damping

        if self.friction > 0 and self.is_grounded and vx:
            decel = self.friction * abs(g) * dt
            vx = 0.0 if abs(vx) <= decel else vx - math.copysign(decel, vx)

        if vy > self.terminal_velocity:
            vy = self.terminal_velocity

        velocity.x = vx
        velocity.y = vy
        self.is_grounded = False

        collider = self.collider
        if collider is None or self._world is None:
            local.set_xy(local.x + vx * dt, local.y + vy * dt)
            return

        collider.refresh()
        dx = velocity.x * dt
        dy = velocity.y * dt

        # ONE broad-phase query per body per step, covering the whole motion
        # path (both axes) plus a margin for depenetration; depenetration and
        # both sweeps reuse it. Nothing solid nearby (an airborne body) means no
        # geometry work at all.
        candidates = self._gather(collider, dx, dy)
        if not candidates:
            local.set_xy(local.x + dx, local.y + dy)
            collider.refresh()
            return

        if self._depenetrate(collider, local, candidates):
            candidates = self._gather(collider, dx, dy)      # we moved: re-gather (rare path)
        if dx:
            self._move_x(collider, local, dx, candidates)
        if dy:
            self._move_y(collider, local, dy, candidates)
        collider.refresh()

    def _gather(self, collider, dx, dy):
        margin = _QUERY_MARGIN
        return self._world.solid_candidates(
            collider,
            collider._l + (dx if dx < 0 else 0.0) - margin, collider._t + (dy if dy < 0 else 0.0) - margin,
            collider._r + (dx if dx > 0 else 0.0) + margin, collider._b + (dy if dy > 0 else 0.0) + margin)

    def _depenetrate(self, collider, local, candidates):
        """If the body starts the step overlapping a solid (spawned inside one,
        teleported, squeezed), push it out along the axis of least penetration.
        Returns True if it had to move the body."""
        moved = False
        for _ in range(4):
            l, t, r, b = collider._l, collider._t, collider._r, collider._b
            shift = None
            for other in candidates:
                # cheap rejection first: almost every neighbour merely touches
                if l >= other._r - _TOL or r <= other._l + _TOL or t >= other._b - _TOL or b <= other._t + _TOL:
                    continue
                pen_x_left = r - other._l        # distance to clear by moving left
                pen_x_right = other._r - l       # ... by moving right
                pen_y_up = b - other._t
                pen_y_down = other._b - t
                pen_x = pen_x_left if pen_x_left < pen_x_right else pen_x_right
                pen_y = pen_y_up if pen_y_up < pen_y_down else pen_y_down
                if pen_x < pen_y:
                    shift = (-pen_x_left, 0.0) if pen_x_left < pen_x_right else (pen_x_right, 0.0)
                else:
                    shift = (0.0, -pen_y_up) if pen_y_up < pen_y_down else (0.0, pen_y_down)
                break
            if shift is None:
                return moved
            local.set_xy(local.x + shift[0], local.y + shift[1])
            collider.refresh()
            moved = True
        return moved

    def _move_x(self, collider, local, dx, candidates):
        l, t, r, b = collider._l, collider._t, collider._r, collider._b
        limit = abs(dx)
        hit = False
        for other in candidates:
            if other._t >= b - _TOL or other._b <= t + _TOL:
                continue                         # no vertical overlap: not in the way
            gap = (other._l - r) if dx > 0 else (l - other._r)
            if gap < -_TOL:
                continue                         # behind us / already deeply inside
            if gap < limit:
                limit = gap if gap > 0.0 else 0.0
                hit = True
        move = limit if dx > 0 else -limit
        if move:
            local.set_xy(local.x + move, local.y)
            collider._l += move                  # the Y sweep needs the new x-range;
            collider._r += move                  # the final refresh() re-derives everything exactly
        if hit:
            self.velocity.x = 0.0

    def _move_y(self, collider, local, dy, candidates):
        l, t, r, b = collider._l, collider._t, collider._r, collider._b
        limit = abs(dy)
        hit = False
        for other in candidates:
            if other._l >= r - _TOL or other._r <= l + _TOL:
                continue
            gap = (other._t - b) if dy > 0 else (t - other._b)
            if gap < -_TOL:
                continue
            if gap < limit:
                limit = gap if gap > 0.0 else 0.0
                hit = True
        move = limit if dy > 0 else -limit
        if move:
            local.set_xy(local.x, local.y + move)
        if hit:
            if dy > 0:
                self.is_grounded = True
            self.velocity.y = 0.0
