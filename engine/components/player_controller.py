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
    "walk_down": "walk_down",
    "walk_up": "walk_up",
    "walk_left": "walk_left",
    "walk_right": "walk_right",
    "jump": "jump",
}

_MOVEMENT_TYPES = {"top_down", "platformer"}

_DIAGONAL_FACTOR = 0.7071067811865476  # 1 / sqrt(2), keeps diagonal speed == axis speed


class PlayerController(Component):
    """A small, extensible character controller with two built-in modes:

      - "top_down": 4/8-directional movement, no gravity.
      - "platformer": horizontal run + gravity-driven jump via Rigidbody2D,
        with optional multi-jump (see max_jumps below).

    Reads input through the Input/Key system (engine/input/) rather than
    calling pygame directly, so `keybinds` accepts Key.* constants, raw
    pygame.K_* constants, or key-name strings interchangeably - see
    engine/input/key.py.

    Extending it: rather than overriding update() wholesale, override one of
    the small hooks below:

      - `_on_jump()`               called the instant a jump fires
      - `_play_platformer_animation` / `_play_top_down_animation`
                                    to change animation-selection rules
      - `_read_move_axis`          to change how input maps to a direction
      - `_can_jump` / `_wants_to_jump`
                                    to change what counts as "allowed to jump"

    That keeps custom abilities (a dash, wall-slide, etc.) additive instead
    of requiring a copy-paste of the whole class.
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

        # "Coyote time": a short grace window after walking off a ledge
        # where the *first* jump still registers - matches what players
        # intuitively expect, and is standard in most platformers. Set to
        # 0 to disable. Only applies to the first jump in a chain - see
        # _can_jump(): once airborne, further jumps (double/triple jump)
        # are available immediately, since the player is deliberately
        # using them, not accidentally walking off a ledge.
        self.coyote_time = coyote_time
        # "Jump buffering": a jump pressed slightly *before* landing still
        # fires the instant the character touches down, instead of being
        # dropped because is_grounded wasn't true yet. Set to 0 to disable.
        self.jump_buffer_time = jump_buffer_time

        # How many times the character can jump before needing to touch
        # the ground again. 1 = a normal single jump (the default,
        # unchanged behaviour). 2 = a double jump, 3 = a triple jump, etc.
        self.max_jumps = max(1, max_jumps)
        self._jumps_used = 0

        # Large initial values so neither grace window is (incorrectly)
        # already active before the player has ever touched the ground once.
        self._time_since_grounded = 999.0
        self._time_since_jump_pressed = 999.0

        self.animator = None
        self.rigidbody = None
        self.is_grounded = True

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
        """How many more times the character can jump before needing to
        touch the ground again - handy for a UI readout (e.g. a UIText
        showing "Jumps: 2/2")."""
        return max(0, self.max_jumps - self._jumps_used)

    def update(self, delta_time):
        if self.movement_type == "top_down":
            self._update_top_down(delta_time)
        elif self.movement_type == "platformer":
            self._update_platformer(delta_time)
        # else: already warned about the bad movement_type in __init__.

    def _is_pressed(self, action):
        return any(Input.is_pressed(k) for k in self.keybinds.get(action, []))

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
        if move_y > 0:
            self.animator.play(self.anim_map["walk_down"])
        elif move_y < 0:
            self.animator.play(self.anim_map["walk_up"])
        elif move_x > 0:
            self.animator.play(self.anim_map["walk_right"])
        elif move_x < 0:
            self.animator.play(self.anim_map["walk_left"])
        else:
            self.animator.play(self.anim_map["idle"])

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

        if self.is_grounded:
            self._time_since_grounded = 0.0
            self._jumps_used = 0  # touching ground refills every jump
        else:
            self._time_since_grounded += delta_time

        if self._is_pressed("jump"):
            self._time_since_jump_pressed = 0.0
        else:
            self._time_since_jump_pressed += delta_time

    def _wants_to_jump(self):
        return self._time_since_jump_pressed <= self.jump_buffer_time

    def _can_jump(self):
        if self._jumps_used == 0:
            # The first jump in a chain: normal ground check, with the
            # coyote-time grace window for "just walked off a ledge".
            return self._time_since_grounded <= self.coyote_time
        # Every jump after the first (double/triple jump, ...) is available
        # immediately while airborne, up to max_jumps - the player is
        # deliberately using an extra jump, not accidentally leaving a
        # platform, so coyote time doesn't apply here.
        return self._jumps_used < self.max_jumps

    def _perform_jump(self):
        # Jump speed is set directly rather than added as an impulse on top
        # of current velocity, so every jump in a chain (including a
        # coyote-time jump, which starts already falling) launches to the
        # same height - more predictable and easier to tune than making it
        # velocity/mass dependent.
        self.rigidbody.velocity.y = -self.jump_force
        self.rigidbody.is_grounded = False
        self.is_grounded = False
        self._jumps_used += 1

        # Push both grace windows past their thresholds so this single press
        # can't also trigger a second jump next frame.
        self._time_since_grounded = self.coyote_time + 1.0
        self._time_since_jump_pressed = self.jump_buffer_time + 1.0

        self._on_jump()

    def _on_jump(self):
        """Hook for subclasses - called the instant a jump is executed."""
        pass

    def _play_platformer_animation(self, move_x):
        if not self.animator:
            return
        if not self.is_grounded and "jump" in self.anim_map:
            self.animator.play(self.anim_map["jump"], loop=False)
        elif move_x > 0:
            self.animator.play(self.anim_map["walk_right"])
        elif move_x < 0:
            self.animator.play(self.anim_map["walk_left"])
        else:
            self.animator.play(self.anim_map["idle"])
