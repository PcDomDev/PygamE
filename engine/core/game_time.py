"""Global clock state shared by the main loop, physics and gameplay code.

Mirrors Unity's `Time` class. Everything here is plain class-level state, so
any component can read it without holding a reference to the Engine:

    Time.delta_time          seconds since last frame (scaled, clamped)
    Time.fixed_delta_time    the fixed physics step (default 1/60 s)
    Time.alpha               0..1 progress between the last two physics steps;
                             render code uses it to interpolate transforms
    Time.time_scale          0 pauses gameplay, 0.5 is slow motion, ...

The loop itself lives in `SceneManager.update()` - see docs/CODEBASE_GUIDE.md.
"""


class Time:
    # -- configuration ---------------------------------------------------------
    fixed_delta_time = 1.0 / 60.0
    max_delta_time = 0.05     # clamp for the variable `update(dt)` step
    max_frame_time = 0.25     # clamp on real time fed to the physics accumulator
    max_fixed_steps = 8       # cap on catch-up steps per frame (spiral-of-death guard)
    time_scale = 1.0

    # -- per-frame state (written by SceneManager.update) --------------------------
    delta_time = 0.0
    unscaled_delta_time = 0.0
    time = 0.0
    unscaled_time = 0.0
    fixed_time = 0.0
    frame_count = 0
    fixed_frame_count = 0
    alpha = 1.0
    in_fixed_step = False

    @classmethod
    def set_fixed_rate(cls, hz):
        """Set the physics rate in Hz (60 -> 1/60 s steps)."""
        if hz <= 0:
            raise ValueError("Time.set_fixed_rate: hz must be > 0")
        cls.fixed_delta_time = 1.0 / float(hz)

    @classmethod
    def reset(cls):
        """Back to defaults. Used by tests and when a game restarts."""
        cls.fixed_delta_time = 1.0 / 60.0
        cls.max_delta_time = 0.05
        cls.max_frame_time = 0.25
        cls.max_fixed_steps = 8
        cls.time_scale = 1.0
        cls.delta_time = 0.0
        cls.unscaled_delta_time = 0.0
        cls.time = 0.0
        cls.unscaled_time = 0.0
        cls.fixed_time = 0.0
        cls.frame_count = 0
        cls.fixed_frame_count = 0
        cls.alpha = 1.0
        cls.in_fixed_step = False
