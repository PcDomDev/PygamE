from engine.components.component import Component
from engine.components.box_collider2d import BoxCollider2D
from engine.core.debug_manager import DebugManager
from engine.utils.vector2 import Vector2


class Rigidbody2D(Component):
    """Simple gravity + drag + AABB collision physics.

    Movement is resolved one axis at a time (move X, resolve X collisions,
    then move Y, resolve Y collisions) rather than both at once. This is a
    standard simplification for axis-aligned physics: it avoids diagonal
    "corner" ambiguity when both axes move into something in the same frame,
    at the cost of not handling very thin/fast-moving obstacles perfectly
    (not a concern for this engine's scale).
    """

    update_order = -100  # physics runs before anything reacts to its results

    # How far below the collider to probe for "still resting on something"
    # when there's no *actual* overlap this frame. Needed because gravity
    # nudges a resting body down by a fraction of a pixel every frame, and
    # pygame's Rect rounds to the nearest whole pixel - some frames that
    # rounds back to "still touching", others it rounds to "just barely
    # clear", which without this probe flickers is_grounded True/False
    # every other frame even though nothing is actually moving on screen.
    # See docs/CHANGELOG.md for the full trace.
    GROUND_PROBE_DISTANCE = 4

    def __init__(self, gravity=500, gravity_scale=1.0, drag=0.0, mass=1.0,
                 use_gravity=True, is_kinematic=False, terminal_velocity=1000):
        super().__init__()
        self.velocity = Vector2(0.0, 0.0)

        self.gravity = gravity
        self.gravity_scale = gravity_scale
        self.drag = drag
        self.mass = mass if mass > 0 else 1.0

        self.use_gravity = use_gravity
        self.is_kinematic = is_kinematic
        self.terminal_velocity = terminal_velocity

        self.is_grounded = False
        self.collider = None

    def start(self):
        self.collider = self.game_object.get_component(BoxCollider2D)
        if self.collider is None:
            DebugManager.log_warning(
                f"Rigidbody2D on '{self.game_object.name}' has no BoxCollider2D - "
                f"gravity/velocity will apply but nothing will collide."
            )

    # -- back-compat scalar accessors ---------------------------------------------
    # The original API exposed velocity_x/velocity_y as plain floats. Kept as
    # thin aliases over the new Vector2 so any existing external scripts that
    # touch them directly don't break; `velocity` is the canonical form now.

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
        """Instant change in velocity: delta_v = impulse / mass.

        Divides by mass so this is consistent with add_force below (a
        heavier body needs a bigger impulse for the same delta_v) - the
        original engine did not divide by mass here, which meant `mass` had
        no effect on impulses (only on add_force, which is inconsistent).
        """
        if self.is_kinematic:
            return
        self.velocity.x += impulse_x / self.mass
        self.velocity.y += impulse_y / self.mass

    def add_force(self, force_x, force_y, delta_time):
        """A continuous force integrated over one frame: delta_v = (force / mass) * dt.

        Note the added `delta_time` parameter - the original signature had
        no way to integrate over time, so calling it once produced an
        instant, framerate-dependent velocity jump despite the "force"
        naming implying a per-second, continuously-applied quantity. Call
        this every frame (e.g. from update(delta_time)) for a sustained
        force such as wind or thrust.
        """
        if self.is_kinematic:
            return
        self.velocity.x += (force_x / self.mass) * delta_time
        self.velocity.y += (force_y / self.mass) * delta_time

    def stop(self):
        self.velocity.x = 0.0
        self.velocity.y = 0.0

    # -- simulation --------------------------------------------------------------

    def update(self, delta_time):
        transform = self.game_object.transform

        if self.is_kinematic:
            transform.position += self.velocity * delta_time
            self._sync_collider()
            return

        if self.use_gravity:
            self.velocity.y += self.gravity * self.gravity_scale * delta_time

        if self.velocity.y > self.terminal_velocity:
            self.velocity.y = self.terminal_velocity

        if self.drag > 0:
            damping = max(0.0, 1.0 - self.drag * delta_time)
            self.velocity.x *= damping

        transform.position.x += self.velocity.x * delta_time
        self._sync_collider()
        self._resolve_collisions_x()

        self.is_grounded = False
        transform.position.y += self.velocity.y * delta_time
        self._sync_collider()
        self._resolve_collisions_y()

    def _sync_collider(self):
        if self.collider:
            self.collider.update(0)

    def _solid_colliders_near(self, rect):
        """Broad-phase-filtered candidates that could physically collide
        with this body near `rect` - only non-trigger BoxCollider2D
        instances belonging to active objects (Rigidbody2D only resolves
        solid collisions against boxes; see CircleCollider2D's docstring
        for why circles are trigger/overlap-only for now).

        Queries the scene's SpatialHash instead of every collider in the
        scene, so this stays fast as object count grows - see
        engine/spatial_hash.py for why that matters and how it stays
        correct (never stale within a frame).
        """
        if not self.collider or self.game_object.scene is None:
            return []
        candidates = self.game_object.scene.spatial_hash.query(rect)
        return [
            c for c in candidates
            if c is not self.collider and isinstance(c, BoxCollider2D)
            and not c.is_trigger and c.game_object.active
        ]

    def _resolve_collisions_x(self):
        if not self.collider:
            return
        for other in self._solid_colliders_near(self.collider.rect):
            if self.collider.rect.colliderect(other.rect):
                # Snap to the other collider's exact edge using the
                # transform's true float position, rather than subtracting
                # an already-rounded rect overlap from it. The two are
                # *not* equivalent: pygame's Rect rounds each edge to the
                # nearest pixel, and that rounding error doesn't cancel out
                # when you later subtract an integer overlap from a float
                # position - it accumulates into a small but real, visible
                # jitter. See the README's Physics section for the full
                # derivation.
                if self.velocity.x > 0:
                    self.collider.snap_right_to(other.rect.left)
                elif self.velocity.x < 0:
                    self.collider.snap_left_to(other.rect.right)
                self.velocity.x = 0
                self._sync_collider()

    def _resolve_collisions_y(self):
        if not self.collider:
            return

        collided = False
        for other in self._solid_colliders_near(self.collider.rect):
            if self.collider.rect.colliderect(other.rect):
                collided = True
                if self.velocity.y > 0:
                    self.collider.snap_bottom_to(other.rect.top)
                    self.is_grounded = True
                elif self.velocity.y < 0:
                    self.collider.snap_top_to(other.rect.bottom)
                self.velocity.y = 0
                self._sync_collider()

        if not collided and self.velocity.y >= 0:
            self._probe_for_ground()

    def _probe_for_ground(self):
        """No overlap was detected this frame, but check a few pixels below
        the collider for solid ground before declaring the body airborne -
        see GROUND_PROBE_DISTANCE above for why."""
        probe_rect = self.collider.rect.move(0, self.GROUND_PROBE_DISTANCE)
        self.is_grounded = any(
            probe_rect.colliderect(other.rect)
            for other in self._solid_colliders_near(probe_rect)
        )
