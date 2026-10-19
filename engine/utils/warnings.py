"""Engine-specific warning category.

Used for *construction-time* misconfiguration (bad anchor string, unknown
movement type, etc) - the kind of mistake a developer makes once while
writing code, which Python's standard `warnings` module is designed to
surface immediately (with a file/line number) rather than silently ignoring.

This is deliberately separate from DebugManager, which is for *runtime*,
in-game diagnostics (things that happen while the game loop is running -
see engine/debug_manager.py for that side of things).
"""


class EngineWarning(UserWarning):
    """Raised (via warnings.warn) for engine-level misconfiguration."""
