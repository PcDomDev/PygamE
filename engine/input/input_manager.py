"""Keyboard and mouse input, queried from anywhere, with "just pressed this
frame" edge detection on top of pygame's raw "currently held" state.

Two ways to use it - same pattern as DebugManager, and for the same
reason (avoiding threading a reference through every component that
wants to read input):

    Input.is_pressed(Key.W)          # from anywhere, no reference needed
    engine.input.is_pressed(Key.W)   # via the instance Engine created

Engine calls Input.update() once per frame, before the scene updates, so
whatever a component reads during its own update() reflects this frame's
state.
"""
import pygame

from engine.input.key import normalize_key


class Input:
    _instance = None

    def __init__(self):
        Input._instance = self

        self._current_keys = pygame.key.get_pressed()
        self._previous_keys = self._current_keys

        self._current_mouse = (False, False, False)
        self._previous_mouse = (False, False, False)
        self._mouse_position = (0, 0)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = Input()
        return cls._instance

    def update(self):
        """Snapshots the current keyboard/mouse state, remembering the
        previous frame's snapshot for edge detection. Call this once per
        frame, after pumping pygame's event queue (Engine does this for
        you) and before anything reads input for the frame."""
        self._previous_keys = self._current_keys
        self._current_keys = pygame.key.get_pressed()

        self._previous_mouse = self._current_mouse
        self._current_mouse = pygame.mouse.get_pressed()
        self._mouse_position = pygame.mouse.get_pos()

    # -- keyboard: classmethods, so `Input.is_pressed(...)` works from anywhere --

    @classmethod
    def is_pressed(cls, key):
        """True every frame the key is held down."""
        code = normalize_key(key)
        return cls.instance()._current_keys[code]

    @classmethod
    def is_just_pressed(cls, key):
        """True only on the single frame the key transitions up -> down."""
        code = normalize_key(key)
        inst = cls.instance()
        return inst._current_keys[code] and not inst._previous_keys[code]

    @classmethod
    def is_just_released(cls, key):
        """True only on the single frame the key transitions down -> up."""
        code = normalize_key(key)
        inst = cls.instance()
        return (not inst._current_keys[code]) and inst._previous_keys[code]

    # -- mouse: button indices match pygame.mouse.get_pressed() - 0=left, 1=middle, 2=right --

    @classmethod
    def mouse_position(cls):
        return cls.instance()._mouse_position

    @classmethod
    def is_mouse_pressed(cls, button=0):
        return cls.instance()._current_mouse[button]

    @classmethod
    def is_mouse_just_pressed(cls, button=0):
        inst = cls.instance()
        return inst._current_mouse[button] and not inst._previous_mouse[button]

    @classmethod
    def is_mouse_just_released(cls, button=0):
        inst = cls.instance()
        return (not inst._current_mouse[button]) and inst._previous_mouse[button]
