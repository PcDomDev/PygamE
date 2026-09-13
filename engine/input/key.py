"""Friendly names for keyboard keys.

Instead of memorizing pygame.K_w, pygame.K_LEFT, etc., you can use:

    Key.W          # attribute access
    "w"            # a plain string (case-insensitive)
    "space"        # named special keys work as strings too
    pygame.K_w     # raw pygame constants still work everywhere - Key.W
                   # literally *is* pygame.K_w, just under a clearer name

See normalize_key() at the bottom - that's what actually turns any of the
above into the underlying pygame key code, and it's what Input (in
input_manager.py) calls internally.
"""
import pygame


class Key:
    """Every attribute here is just `pygame.K_*` under a name that doesn't
    require looking up pygame's docs. Extending this is a one-line addition
    - see the bottom of this class for the pattern.
    """

    # Letters
    A = pygame.K_a
    B = pygame.K_b
    C = pygame.K_c
    D = pygame.K_d
    E = pygame.K_e
    F = pygame.K_f
    G = pygame.K_g
    H = pygame.K_h
    I = pygame.K_i
    J = pygame.K_j
    K = pygame.K_k
    L = pygame.K_l
    M = pygame.K_m
    N = pygame.K_n
    O = pygame.K_o
    P = pygame.K_p
    Q = pygame.K_q
    R = pygame.K_r
    S = pygame.K_s
    T = pygame.K_t
    U = pygame.K_u
    V = pygame.K_v
    W = pygame.K_w
    X = pygame.K_x
    Y = pygame.K_y
    Z = pygame.K_z

    # Digits - `Key.0` isn't legal Python syntax, so these are spelled out.
    # The string forms "0".."9" work directly (see normalize_key), so this
    # naming only matters for attribute-style access.
    NUM_0 = pygame.K_0
    NUM_1 = pygame.K_1
    NUM_2 = pygame.K_2
    NUM_3 = pygame.K_3
    NUM_4 = pygame.K_4
    NUM_5 = pygame.K_5
    NUM_6 = pygame.K_6
    NUM_7 = pygame.K_7
    NUM_8 = pygame.K_8
    NUM_9 = pygame.K_9

    # Arrows
    LEFT = pygame.K_LEFT
    RIGHT = pygame.K_RIGHT
    UP = pygame.K_UP
    DOWN = pygame.K_DOWN

    # Whitespace / editing / control
    SPACE = pygame.K_SPACE
    ENTER = pygame.K_RETURN
    RETURN = pygame.K_RETURN
    TAB = pygame.K_TAB
    BACKSPACE = pygame.K_BACKSPACE
    DELETE = pygame.K_DELETE
    ESCAPE = pygame.K_ESCAPE

    # Modifiers (left/right variants are distinct keys in pygame; the
    # generic string names "shift"/"ctrl"/"alt" in _STRING_ALIASES below
    # map to the left-hand one, which is what most games mean by default)
    LSHIFT = pygame.K_LSHIFT
    RSHIFT = pygame.K_RSHIFT
    LCTRL = pygame.K_LCTRL
    RCTRL = pygame.K_RCTRL
    LALT = pygame.K_LALT
    RALT = pygame.K_RALT

    # Function keys, in case a game/tool wants them
    F1 = pygame.K_F1
    F2 = pygame.K_F2
    F3 = pygame.K_F3
    F4 = pygame.K_F4
    F5 = pygame.K_F5
    F6 = pygame.K_F6
    F7 = pygame.K_F7
    F8 = pygame.K_F8
    F9 = pygame.K_F9
    F10 = pygame.K_F10
    F11 = pygame.K_F11
    F12 = pygame.K_F12


# Friendly string names that don't map to a single letter/digit and aren't
# already covered by pygame's own name parser (see normalize_key) - kept
# small and readable rather than exhaustive. Add more here as needed; that
# is the "easy to extend" story for the string form.
_STRING_ALIASES = {
    "space": Key.SPACE,
    "enter": Key.ENTER,
    "return": Key.RETURN,
    "esc": Key.ESCAPE,
    "escape": Key.ESCAPE,
    "tab": Key.TAB,
    "backspace": Key.BACKSPACE,
    "delete": Key.DELETE,
    "left": Key.LEFT,
    "right": Key.RIGHT,
    "up": Key.UP,
    "down": Key.DOWN,
    "shift": Key.LSHIFT,
    "ctrl": Key.LCTRL,
    "control": Key.LCTRL,
    "alt": Key.LALT,
}


def normalize_key(key):
    """Turn a Key.* constant, a raw pygame.K_* constant, or a
    case-insensitive string (a single letter/digit, or a name like
    "space"/"left"/"shift") into the underlying pygame key code (an int).

    Raises ValueError for anything unrecognized, so a typo'd key name
    fails loudly and immediately, rather than a keybind silently never
    triggering.
    """
    if isinstance(key, bool):
        raise ValueError(f"Unrecognized key: {key!r}")

    if isinstance(key, int):
        return key  # Key.* constants and raw pygame.K_* constants are both just ints

    if isinstance(key, str):
        normalized = key.strip().lower()
        if normalized in _STRING_ALIASES:
            return _STRING_ALIASES[normalized]
        try:
            # Falls back to pygame's own name table, so any key pygame
            # recognizes works even if it isn't in the alias table above
            # (numpad keys, media keys, punctuation, etc).
            return pygame.key.key_code(normalized)
        except (ValueError, TypeError):
            pass

    raise ValueError(
        f"Unrecognized key: {key!r}. Use a Key.* constant, a raw pygame.K_* "
        f"constant, or a string like \"w\", \"space\", or \"left\"."
    )
