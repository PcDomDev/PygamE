"""Keyboard and mouse input, queried from anywhere.

    Input.is_key_down("space")       # True every frame the key is held
    Input.is_key_pressed("space")    # True only on the frame it went down
    Input.is_key_up("space")         # True only on the frame it was released
    Input.is_key_down("mouse_left")  # mouse buttons are keys too
    Input.mouse_position()           # (x, y) in screen pixels
    Input.mouse_delta()              # movement since last frame
    Input.mouse_scroll()             # wheel ticks this frame (+ = away from you)

Keys can be `Key.W`, raw `pygame.K_w`, or strings ("w", "space", "left_shift",
"mouse_left") - see engine/input/key.py. Like DebugManager, everything is a
classmethod, so any component can read input without holding a reference.

How it works: Engine feeds every pygame event to `process_event()`, so presses
and releases are *events*, not polled snapshots. A key tapped and released
within one frame still registers (polling would miss it), and a window
losing focus releases all held keys instead of leaving them stuck.

Edge queries and the physics step: `is_key_pressed/is_key_up` are per-*frame*
edges. Physics runs in fixed steps, which don't line up with frames: a frame
may run two steps or none. So inside a fixed step (`Time.in_fixed_step`) the
same queries read a separate edge set that is consumed after each step - every
press is seen by exactly one fixed step, never dropped and never duplicated.
Read input in `update()` where you can; this makes `fixed_update()` safe too.

Gamepads (opt-in - nothing is polled until you ask for it):

    Input.enable_gamepad()                       # or Engine(..., gamepad=True)
    Input.is_gamepad_pressed("a")                # edge: the frame the button went down
    Input.is_gamepad_down("right_shoulder")      # held; is_gamepad_up() for the release edge
    Input.gamepad_axis("left_x")                 # -1..1 with a deadzone; triggers are 0..1
    Input.gamepad_stick("left")                  # (x, y), radial deadzone, up = negative y like the screen
    Input.gamepad_count()                        # how many are connected right now

The second argument of every gamepad call is the player slot (0 = first pad). Slots are stable: if pad 0 is
unplugged, pad 1 stays pad 1. Pads can be hot-plugged. Button names: a b x y back guide start left_stick
right_stick left_shoulder right_shoulder dpad_up dpad_down dpad_left dpad_right. Axis names: left_x left_y
right_x right_y left_trigger right_trigger. Names follow SDL's Xbox-style game-controller layout, so "a" is
the bottom face button on Xbox and PlayStation (Cross) pads; on Nintendo pads SDL may follow the printed labels
instead. PlayerController reads the pad for you when it is enabled (see use_gamepad there).

Legacy names still work: `is_pressed` = `is_key_down`, `is_just_pressed` =
`is_key_pressed`, `is_just_released` = `is_key_up`. (Note the different
meaning of the *new* `is_key_pressed` - edge only - vs the old `is_pressed`.)
"""
import pygame

from engine.core.game_time import Time
from engine.input.key import normalize_key

_MOUSE_EVENT_BUTTONS = {1: "mouse_left", 2: "mouse_middle", 3: "mouse_right", 6: "mouse_x1", 7: "mouse_x2"}
_LEGACY_MOUSE_INDEX = ("mouse_left", "mouse_middle", "mouse_right")
_FOCUS_LOST = getattr(pygame, "WINDOWFOCUSLOST", None)

try:                                    # SDL's game-controller layer: one button/axis layout for every pad
    from pygame._sdl2 import controller as _sdl_controller
except Exception:                       # noqa: BLE001 - very old pygame builds: gamepads simply stay unavailable
    _sdl_controller = None

GAMEPAD_BUTTONS = {
    "a": "CONTROLLER_BUTTON_A", "b": "CONTROLLER_BUTTON_B", "x": "CONTROLLER_BUTTON_X",
    "y": "CONTROLLER_BUTTON_Y", "back": "CONTROLLER_BUTTON_BACK", "guide": "CONTROLLER_BUTTON_GUIDE",
    "start": "CONTROLLER_BUTTON_START", "left_stick": "CONTROLLER_BUTTON_LEFTSTICK",
    "right_stick": "CONTROLLER_BUTTON_RIGHTSTICK", "left_shoulder": "CONTROLLER_BUTTON_LEFTSHOULDER",
    "right_shoulder": "CONTROLLER_BUTTON_RIGHTSHOULDER", "dpad_up": "CONTROLLER_BUTTON_DPAD_UP",
    "dpad_down": "CONTROLLER_BUTTON_DPAD_DOWN", "dpad_left": "CONTROLLER_BUTTON_DPAD_LEFT",
    "dpad_right": "CONTROLLER_BUTTON_DPAD_RIGHT",
}
GAMEPAD_AXES = {
    "left_x": "CONTROLLER_AXIS_LEFTX", "left_y": "CONTROLLER_AXIS_LEFTY",
    "right_x": "CONTROLLER_AXIS_RIGHTX", "right_y": "CONTROLLER_AXIS_RIGHTY",
    "left_trigger": "CONTROLLER_AXIS_TRIGGERLEFT", "right_trigger": "CONTROLLER_AXIS_TRIGGERRIGHT",
}
_BUTTON_BY_CODE = {getattr(pygame, const): name for name, const in GAMEPAD_BUTTONS.items() if hasattr(pygame, const)}
_AXIS_BY_CODE = {getattr(pygame, const): name for name, const in GAMEPAD_AXES.items() if hasattr(pygame, const)}
_PAD_EVENTS = tuple(getattr(pygame, n) for n in (
    "CONTROLLERDEVICEADDED", "CONTROLLERDEVICEREMOVED", "CONTROLLERBUTTONDOWN", "CONTROLLERBUTTONUP")
    if hasattr(pygame, n))
_TRIGGERS = ("left_trigger", "right_trigger")
_AXIS_MAX = 32767.0


class Input:
    _instance = None

    def __init__(self):
        Input._instance = self
        self.reset()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = Input()
        return cls._instance

    def reset(self):
        self._held = set()
        self._pressed = set()
        self._released = set()
        self._fixed_pressed = set()
        self._fixed_released = set()
        self._mouse_position = (0, 0)
        self._last_mouse_position = (0, 0)
        self._mouse_delta = (0, 0)
        self._scroll_x = 0
        self._scroll_y = 0
        self._mouse_override = False
        for entry in getattr(self, "_pads", {}).values():
            try:
                entry[0].quit()
            except Exception:  # noqa: BLE001 - the pad may already be unplugged
                pass
        self._gamepad_enabled = False
        self._deadzone = 0.2
        self._pads = {}              # slot -> (sdl Controller, instance_id), slots are stable while plugged in
        self._pad_axes = {}          # slot -> {axis name: raw value in -1..1}
        self._virtual_slots = set()  # slots that only exist because of inject_gamepad_*()

    # -- per-frame plumbing (Engine calls these) -----------------------------------

    def begin_frame(self):
        """Start a new frame: forget last frame's press/release edges and wheel ticks."""
        self._pressed.clear()
        self._released.clear()
        self._scroll_x = 0
        self._scroll_y = 0

    def process_event(self, event):
        """Feed one pygame event. Engine does this for every event each frame."""
        kind = event.type
        if kind == pygame.KEYDOWN:
            self._press(event.key)
        elif kind == pygame.KEYUP:
            self._release(event.key)
        elif kind == pygame.MOUSEBUTTONDOWN:
            token = _MOUSE_EVENT_BUTTONS.get(event.button)
            if token is not None:
                self._press(token)
        elif kind == pygame.MOUSEBUTTONUP:
            token = _MOUSE_EVENT_BUTTONS.get(event.button)
            if token is not None:
                self._release(token)
        elif kind == pygame.MOUSEWHEEL:
            self._scroll_x += event.x
            self._scroll_y += event.y
        elif _FOCUS_LOST is not None and kind == _FOCUS_LOST:
            self.release_all()
        elif self._gamepad_enabled and kind in _PAD_EVENTS:
            self._process_gamepad_event(event)

    def update(self):
        """Sample the mouse position and compute this frame's movement. Call
        once per frame after all events were processed (Engine does)."""
        if not self._mouse_override:
            try:
                self._mouse_position = pygame.mouse.get_pos()
            except pygame.error:
                pass          # no video system (headless): keep the last position
        self._mouse_delta = (self._mouse_position[0] - self._last_mouse_position[0],
                             self._mouse_position[1] - self._last_mouse_position[1])
        self._last_mouse_position = self._mouse_position
        if self._pads:
            self._poll_gamepad_axes()

    def end_fixed_step(self):
        """Called after every physics step: fixed-step edges are consumed."""
        self._fixed_pressed.clear()
        self._fixed_released.clear()

    def release_all(self):
        """Treat every held key as released (window lost focus)."""
        for token in list(self._held):
            self._release(token)

    def _press(self, token):
        if token in self._held:
            return                   # OS key-repeat: not a new press
        self._held.add(token)
        self._pressed.add(token)
        self._fixed_pressed.add(token)

    def _release(self, token):
        if token not in self._held:
            return
        self._held.discard(token)
        self._released.add(token)
        self._fixed_released.add(token)

    # -- gamepad plumbing --------------------------------------------------------------

    def _scan_gamepads(self):
        """Open every attached SDL game controller we don't hold yet (startup and hot-plug)."""
        if _sdl_controller is None:
            return
        try:
            if not _sdl_controller.get_init():
                _sdl_controller.init()
            known = {instance_id for _, instance_id in self._pads.values()}
            for device_index in range(_sdl_controller.get_count()):
                if not _sdl_controller.is_controller(device_index):
                    continue
                pad = _sdl_controller.Controller(device_index)
                instance_id = pad.as_joystick().get_instance_id()
                if instance_id in known:
                    continue
                slot = 0
                while slot in self._pads or slot in self._virtual_slots:
                    slot += 1
                self._pads[slot] = (pad, instance_id)
                self._pad_axes[slot] = {}
                known.add(instance_id)
        except Exception:  # noqa: BLE001 - a flaky driver must never take the game loop down
            pass

    def _slot_of(self, instance_id):
        for slot, (_, known_id) in self._pads.items():
            if known_id == instance_id:
                return slot
        return None

    def _process_gamepad_event(self, event):
        kind = event.type
        if kind == pygame.CONTROLLERDEVICEADDED:
            self._scan_gamepads()
        elif kind == pygame.CONTROLLERDEVICEREMOVED:
            slot = self._slot_of(getattr(event, "instance_id", None))
            if slot is not None:
                for token in [t for t in self._held if isinstance(t, tuple) and t[1] == slot]:
                    self._release(token)
                try:
                    self._pads[slot][0].quit()
                except Exception:  # noqa: BLE001
                    pass
                del self._pads[slot]
                self._pad_axes.pop(slot, None)
        else:
            slot = self._slot_of(getattr(event, "instance_id", None))
            name = _BUTTON_BY_CODE.get(getattr(event, "button", None))
            if slot is None or name is None:
                return
            if kind == pygame.CONTROLLERBUTTONDOWN:
                self._press(("pad", slot, name))
            else:
                self._release(("pad", slot, name))

    def _poll_gamepad_axes(self):
        for slot, (pad, _) in self._pads.items():
            axes = self._pad_axes.setdefault(slot, {})
            try:
                for code, name in _AXIS_BY_CODE.items():
                    axes[name] = max(-1.0, min(1.0, pad.get_axis(code) / _AXIS_MAX))
            except pygame.error:
                pass                 # unplugged mid-frame: the DEVICEREMOVED event cleans up

    # -- simulation helpers (tests, replays, bots) ------------------------------------

    def inject_gamepad_button(self, button, down=True, slot=0):
        """Simulate a gamepad button press/release (also makes `slot` count as connected)."""
        self._check_pad_name(button, GAMEPAD_BUTTONS, "button")
        self._virtual_slots.add(slot)
        token = ("pad", slot, button)
        self._press(token) if down else self._release(token)

    def inject_gamepad_axis(self, axis, value, slot=0):
        """Simulate an axis position in -1..1 (also makes `slot` count as connected)."""
        self._check_pad_name(axis, GAMEPAD_AXES, "axis")
        self._virtual_slots.add(slot)
        self._pad_axes.setdefault(slot, {})[axis] = max(-1.0, min(1.0, float(value)))

    @staticmethod
    def _check_pad_name(name, table, what):
        if name not in table:
            raise ValueError(f"unknown gamepad {what} {name!r}; valid names: {', '.join(sorted(table))}")

    def inject_key(self, key, down=True):
        """Simulate a key/mouse-button press or release without a pygame event."""
        token = normalize_key(key)
        if down:
            self._press(token)
        else:
            self._release(token)

    def inject_mouse_position(self, x, y):
        """Pin the mouse position (stops polling the real mouse)."""
        self._mouse_override = True
        self._mouse_position = (x, y)

    def inject_scroll(self, y, x=0):
        self._scroll_y += y
        self._scroll_x += x

    # -- keyboard / mouse buttons --------------------------------------------------------

    @classmethod
    def is_key_down(cls, key):
        """True every frame the key (or "mouse_*" button) is held. A key that
        went down and up within one frame still reads True for that frame."""
        inp = cls.instance()
        token = normalize_key(key)
        return token in inp._held or token in inp._pressed

    @classmethod
    def is_key_pressed(cls, key):
        """True only on the frame the key went down (once per physics step
        inside fixed_update)."""
        inp = cls.instance()
        edges = inp._fixed_pressed if Time.in_fixed_step else inp._pressed
        return normalize_key(key) in edges

    @classmethod
    def is_key_up(cls, key):
        """True only on the frame the key was released."""
        inp = cls.instance()
        edges = inp._fixed_released if Time.in_fixed_step else inp._released
        return normalize_key(key) in edges

    @classmethod
    def get_axis(cls, negative, positive):
        """-1, 0 or 1 from a pair of keys, e.g. Input.get_axis("a", "d")."""
        return int(cls.is_key_down(positive)) - int(cls.is_key_down(negative))

    # legacy names
    @classmethod
    def is_pressed(cls, key):
        """True every frame the key is held down (same as is_key_down)."""
        return cls.is_key_down(key)

    @classmethod
    def is_just_pressed(cls, key):
        """True only on the frame the key went down (same as is_key_pressed)."""
        return cls.is_key_pressed(key)

    @classmethod
    def is_just_released(cls, key):
        """True only on the frame the key was released (same as is_key_up)."""
        return cls.is_key_up(key)

    # -- gamepad -------------------------------------------------------------------

    @classmethod
    def enable_gamepad(cls, enabled=True, deadzone=0.2):
        """Turn gamepad support on (or off). Off by default, so a game that doesn't want pads pays nothing.
        `deadzone` (0..0.95) is the fraction of stick travel ignored around the centre, to hide drift."""
        inp = cls.instance()
        inp._deadzone = max(0.0, min(0.95, float(deadzone)))
        if enabled and not inp._gamepad_enabled:
            inp._gamepad_enabled = True
            inp._scan_gamepads()
        elif not enabled and inp._gamepad_enabled:
            inp._gamepad_enabled = False
            for token in [t for t in inp._held if isinstance(t, tuple)]:
                inp._release(token)

    @classmethod
    def is_gamepad_enabled(cls):
        return cls.instance()._gamepad_enabled

    @classmethod
    def gamepad_count(cls):
        """How many pads are connected right now (0 while gamepad support is off)."""
        inp = cls.instance()
        return len(set(inp._pads) | inp._virtual_slots) if inp._gamepad_enabled else 0

    @classmethod
    def gamepad_name(cls, slot=0):
        inp = cls.instance()
        entry = inp._pads.get(slot)
        if entry is None:
            return None
        try:
            return entry[0].name
        except Exception:  # noqa: BLE001
            return "Gamepad"

    @classmethod
    def is_gamepad_down(cls, button, slot=0):
        """True every frame the button is held."""
        inp = cls.instance()
        cls._check_pad_name(button, GAMEPAD_BUTTONS, "button")
        token = ("pad", slot, button)
        return inp._gamepad_enabled and (token in inp._held or token in inp._pressed)

    @classmethod
    def is_gamepad_pressed(cls, button, slot=0):
        """True only on the frame the button went down (once per physics step inside fixed_update)."""
        inp = cls.instance()
        cls._check_pad_name(button, GAMEPAD_BUTTONS, "button")
        edges = inp._fixed_pressed if Time.in_fixed_step else inp._pressed
        return inp._gamepad_enabled and ("pad", slot, button) in edges

    @classmethod
    def is_gamepad_up(cls, button, slot=0):
        """True only on the frame the button was released."""
        inp = cls.instance()
        cls._check_pad_name(button, GAMEPAD_BUTTONS, "button")
        edges = inp._fixed_released if Time.in_fixed_step else inp._released
        return inp._gamepad_enabled and ("pad", slot, button) in edges

    @classmethod
    def gamepad_axis(cls, axis, slot=0):
        """One axis, -1..1, with the deadzone removed and the rest rescaled so it still reaches +-1.
        Triggers run 0..1. 0.0 when gamepads are off or the slot is empty."""
        inp = cls.instance()
        cls._check_pad_name(axis, GAMEPAD_AXES, "axis")
        if not inp._gamepad_enabled:
            return 0.0
        value = inp._pad_axes.get(slot, {}).get(axis, 0.0)
        if axis in _TRIGGERS:
            value = max(0.0, value)
        zone = inp._deadzone
        magnitude = abs(value)
        if magnitude <= zone:
            return 0.0
        return (1.0 if value > 0 else -1.0) * min(1.0, (magnitude - zone) / (1.0 - zone))

    @classmethod
    def gamepad_stick(cls, side="left", slot=0):
        """(x, y) of the "left" or "right" stick with a *radial* deadzone (so diagonals aren't clipped);
        length never exceeds 1. Up is negative y, matching screen coordinates."""
        inp = cls.instance()
        if side not in ("left", "right"):
            raise ValueError("gamepad_stick side must be 'left' or 'right'")
        if not inp._gamepad_enabled:
            return (0.0, 0.0)
        axes = inp._pad_axes.get(slot, {})
        x, y = axes.get(f"{side}_x", 0.0), axes.get(f"{side}_y", 0.0)
        length = (x * x + y * y) ** 0.5
        zone = inp._deadzone
        if length <= zone:
            return (0.0, 0.0)
        scale = min(1.0, (length - zone) / (1.0 - zone)) / length
        return (x * scale, y * scale)

    # -- mouse ---------------------------------------------------------------------

    @classmethod
    def mouse_position(cls):
        """(x, y) in screen pixels."""
        return cls.instance()._mouse_position

    @classmethod
    def mouse_delta(cls):
        """(dx, dy) the mouse moved since the previous frame."""
        return cls.instance()._mouse_delta

    @classmethod
    def mouse_scroll(cls):
        """Vertical wheel ticks this frame; positive = scrolled up/away from you."""
        return cls.instance()._scroll_y

    @classmethod
    def mouse_scroll_x(cls):
        return cls.instance()._scroll_x

    @classmethod
    def mouse_world_position(cls):
        """The mouse position in world coordinates, through the active scene's camera."""
        from engine.core.scene_manager import SceneManager
        scene = SceneManager.active_scene
        if scene is None:
            return None
        return scene.screen_to_world(cls.mouse_position())

    @classmethod
    def is_mouse_pressed(cls, button=0):
        """0 = left, 1 = middle, 2 = right. True while held."""
        return cls.is_key_down(_LEGACY_MOUSE_INDEX[button])

    @classmethod
    def is_mouse_just_pressed(cls, button=0):
        return cls.is_key_pressed(_LEGACY_MOUSE_INDEX[button])

    @classmethod
    def is_mouse_just_released(cls, button=0):
        return cls.is_key_up(_LEGACY_MOUSE_INDEX[button])
