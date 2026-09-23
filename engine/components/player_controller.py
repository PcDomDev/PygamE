import warnings

from engine.components.animator import Animator
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.debug_manager import DebugManager
from engine.input.input_manager import Input
from engine.input.key import Key
from engine.utils.warnings import EngineWarning

DEFAULT_KEYBINDS = {
    "left": [Key.A, Key.LEFT],
    "right": [Key.D, Key.RIGHT],
    "up": [Key.W, Key.UP],
    "down": [Key.S, Key.DOWN],
    "jump": [Key.SPACE],
}

DEFAULT_ANIM_MAP = {
    "idle": "idle",
    "idle_left": "idle_left",
    "idle_right": "idle_right",
    "idle_up": "idle_up",
    "idle_down": "idle_down",

    "walk_down": "walk_down",
    "walk_up": "walk_up",
    "walk_left": "walk_left",
    "walk_right": "walk_right",

    "jump": "jump",
    "jump_left": "jump_left",
    "jump_right": "jump_right",
}

_MOVEMENT_TYPES = {"top_down", "platformer"}

_DIAGONAL_FACTOR = 0.7071067811865476  # 1 / sqrt(2), keeps diagonal speed == axis speed


class PlayerController(Component):
    """A small, extensible character controller with two built-in modes:

      - "top_down": 4/8-directional movement, no gravity.
      - "platformer": horizontal run + gravity-driven jump via Rigidbody2D,
        with optional multi-jump (see max_jumps below).

    Reads input through the Input/Key system (engine/input/) rather than
    calling pygame directly.

    Entity events (on `game_object.events`, only emitted if someone has
    subscribed): "jumped" (jumps_used, remaining), "landed", and
    "jumps_changed" (remaining, maximum) - e.g. to drive a double-jump HUD:

        player.events.subscribe("jumps_changed", lambda remaining, maximum: ...)
    """

    def __init__(
            self,
            speed=200,
            jump_force=350,
            movement_type="top_down",
            keybinds=None,
            anim_map=None,
            coyote_time=0.1,
            jump_buffer_time=0.1,
            max_jumps=1,
    ):
        super().__init__()

        if movement_type not in _MOVEMENT_TYPES:
            warnings.warn(
                f"PlayerController: unknown movement_type '{movement_type}', "
                f"expected one of {sorted(_MOVEMENT_TYPES)}. No movement will be applied.",
                EngineWarning,
                stacklevel=2,
            )

        self.speed = speed
        self.jump_force = jump_force
        self.movement_type = movement_type

        self.keybinds = keybinds or {k: list(v) for k, v in DEFAULT_KEYBINDS.items()}
        self.anim_map = anim_map or dict(DEFAULT_ANIM_MAP)

        self.coyote_time = coyote_time
        self.jump_buffer_time = jump_buffer_time
        self.max_jumps = max(1, max_jumps)
        self._jumps_used = 0

        self._time_since_grounded = 999.0
        self._time_since_jump_pressed = 999.0

        self.animator = None
        self.rigidbody = None
        self.is_grounded = True
        self._was_grounded = True

        # Tracks last horizontal/vertical orientation for idle/jump animations
        self.facing_x = 1
        self.facing_y = 1

    def start(self):
        self.animator = self.game_object.get_component(Animator)
        self.rigidbody = self.game_object.get_component(Rigidbody2D)
        if self.movement_type == "platformer" and self.rigidbody is None:
            DebugManager.log_warning(
                f"PlayerController on '{self.game_object.name}' is in 'platformer' mode "
                f"but has no Rigidbody2D - gravity and jumping will not work."
            )

    @property
    def jumps_remaining(self):
        return max(0, self.max_jumps - self._jumps_used)

    def update(self, delta_time):
        if self.movement_type == "top_down":
            self._update_top_down(delta_time)
        elif self.movement_type == "platformer":
            self._update_platformer(delta_time)

    def _is_pressed(self, action):
        """Checks if any key mapped to the action is currently held down."""
        return any(Input.is_pressed(k) for k in self.keybinds.get(action, []))

    def _is_just_pressed(self, action):
        """Checks if any key mapped to the action was pressed on this exact frame."""
        return any(Input.is_key_pressed(k) for k in self.keybinds.get(action, []))

    def _emit(self, event, **payload):
        """Fire an entity-scoped event (only if someone could be listening)."""
        events = self.game_object._events
        if events is not None:
            events.emit(event, **payload)

    def _set_jumps_used(self, count):
        if count != self._jumps_used:
            self._jumps_used = count
            self._emit("jumps_changed", remaining=self.jumps_remaining, maximum=self.max_jumps)

    def _read_move_axis(self):
        move_x, move_y = 0, 0
        if self._is_pressed("left"):
            move_x -= 1
        if self._is_pressed("right"):
            move_x += 1
        if self._is_pressed("up"):
            move_y -= 1
        if self._is_pressed("down"):
            move_y += 1
        return move_x, move_y

    # ---------------- top-down mode ----------------

    def _update_top_down(self, delta_time):
        move_x, move_y = self._read_move_axis()

        if move_x != 0 and move_y != 0:
            move_x *= _DIAGONAL_FACTOR
            move_y *= _DIAGONAL_FACTOR

        if self.rigidbody:
            self.rigidbody.velocity.x = move_x * self.speed
            self.rigidbody.velocity.y = move_y * self.speed
        else:
            transform = self.game_object.transform
            transform.position.x += move_x * self.speed * delta_time
            transform.position.y += move_y * self.speed * delta_time

        self._play_top_down_animation(move_x, move_y)

    def _play_top_down_animation(self, move_x, move_y):
        if not self.animator:
            return

        if move_x != 0: self.facing_x = 1 if move_x > 0 else -1
        if move_y != 0: self.facing_y = 1 if move_y > 0 else -1

        if move_y > 0:
            self.animator.play(self.anim_map.get("walk_down"))
        elif move_y < 0:
            self.animator.play(self.anim_map.get("walk_up"))
        elif move_x > 0:
            self.animator.play(self.anim_map.get("walk_right"))
        elif move_x < 0:
            self.animator.play(self.anim_map.get("walk_left"))
        else:
            idle_anim = self.anim_map.get(f"idle_{'right' if self.facing_x > 0 else 'left'}")
            if not idle_anim or not self.animator.has_animation(idle_anim):
                idle_anim = self.anim_map.get("idle")

            if idle_anim:
                self.animator.play(idle_anim)

    # ---------------- platformer mode ----------------

    def _update_platformer(self, delta_time):
        self._update_jump_timers(delta_time)

        move_x, _ = self._read_move_axis()

        if self.rigidbody:
            self.rigidbody.velocity.x = move_x * self.speed
            if self._wants_to_jump() and self._can_jump():
                self._perform_jump()
        else:
            self.game_object.transform.position.x += move_x * self.speed * delta_time

        self._play_platformer_animation(move_x)

    def _update_jump_timers(self, delta_time):
        if self.rigidbody:
            self.is_grounded = self.rigidbody.is_grounded

        if self.is_grounded and not self._was_grounded:
            self._emit("landed")
        self._was_grounded = self.is_grounded

        if self.is_grounded:
            self._time_since_grounded = 0.0
            self._set_jumps_used(0)
        else:
            self._time_since_grounded += delta_time

        # Only trigger jump timer reset on initial press event to prevent continuous multi-jumps while holding key
        if self._is_just_pressed("jump"):
            self._time_since_jump_pressed = 0.0
        else:
            self._time_since_jump_pressed += delta_time

    def _wants_to_jump(self):
        return self._time_since_jump_pressed <= self.jump_buffer_time

    def _can_jump(self):
        if self._jumps_used == 0:
            return self._time_since_grounded <= self.coyote_time
        return self._jumps_used < self.max_jumps

    def _perform_jump(self):
        self.rigidbody.velocity.y = -self.jump_force
        self.rigidbody.is_grounded = False
        self.is_grounded = False
        self._set_jumps_used(self._jumps_used + 1)
        self._emit("jumped", jumps_used=self._jumps_used, remaining=self.jumps_remaining)

        self._time_since_grounded = self.coyote_time + 1.0
        self._time_since_jump_pressed = self.jump_buffer_time + 1.0

        if self.animator and self._jumps_used > 1:
            jump_anim = self.anim_map.get("jump_right") if self.facing_x > 0 else self.anim_map.get("jump_left")
            if jump_anim and self.animator.has_animation(jump_anim):
                self.animator.play(jump_anim, loop=False, force_restart=True)

        self._on_jump()

    def _on_jump(self):
        pass

    def _play_platformer_animation(self, move_x):
        if not self.animator:
            return

        if move_x != 0:
            self.facing_x = 1 if move_x > 0 else -1

        if not self.is_grounded:
            target_anim = self.anim_map.get("jump_right") if self.facing_x > 0 else self.anim_map.get("jump_left")

            if not target_anim or not self.animator.has_animation(target_anim):
                target_anim = self.anim_map.get("jump")

            if target_anim:
                self.animator.play(target_anim, loop=False)

        elif move_x > 0:
            self.animator.play(self.anim_map.get("walk_right"))
        elif move_x < 0:
            self.animator.play(self.anim_map.get("walk_left"))

        else:
            target_anim = self.anim_map.get("idle_right") if self.facing_x > 0 else self.anim_map.get("idle_left")

            if not target_anim or not self.animator.has_animation(target_anim):
                target_anim = self.anim_map.get("idle")

            if target_anim:
                self.animator.play(target_anim)