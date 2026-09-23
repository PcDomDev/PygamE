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

    # -- simulation helpers (tests, replays, bots) ------------------------------------

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
