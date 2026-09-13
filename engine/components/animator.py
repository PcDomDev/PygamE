from engine.components.component import Component
from engine.components.sprite_renderer import SpriteRenderer


class Animator(Component):
    """Frame-based sprite animation, driven by a dict of
    `{animation_name: [surface, surface, ...]}`.

    `play(name)` is meant to be safe to call every frame with the currently
    "intended" animation - which is exactly how PlayerController uses it
    (e.g. it calls play("walk_right") on every single update() while the
    right key is held). See docs/CHANGELOG.md: the original implementation
    reset the frame timer and frame index on *every* call regardless of
    whether the animation actually changed, which meant any animation driven
    this way never advanced past frame 0. `play()` now only resets state
    when the animation is actually changing (or restarting after finishing).
    """

    def __init__(self, animations=None, default_animation=None, frame_duration=0.1):
        super().__init__()
        self.animations = animations if animations is not None else {}
        self.current_animation = default_animation
        self.frame_duration = frame_duration

        self.frame_index = 0
        self.sprite_renderer = None
        self._timer = 0.0

        self.is_playing = True
        self.loop = True
        self.reverse = False

        # callback(animator, anim_name) - fires once, the frame a
        # non-looping animation reaches its last frame. Append to subscribe.
        self.on_finished = []

    def start(self):
        self.sprite_renderer = self.game_object.get_component(SpriteRenderer)
        self._apply_current_frame()

    def play(self, anim_name=None, loop=True, reverse=False):
        if anim_name is None or anim_name not in self.animations:
            return

        # Only reset playback position when we're actually (re)starting an
        # animation - switching to a different one, or restarting one that
        # had already finished. Repeated calls with the same, still-playing
        # name are now a no-op past the flag updates below, which is what
        # lets update() actually accumulate time and advance frames.
        is_new_playback = (anim_name != self.current_animation) or not self.is_playing

        self.current_animation = anim_name
        self.loop = loop
        self.reverse = reverse

        if is_new_playback:
            self.is_playing = True
            self._timer = 0.0
            frames = self.animations[anim_name]
            self.frame_index = (len(frames) - 1) if reverse else 0
            self._apply_current_frame()

    def pause(self):
        self.is_playing = False

    def stop(self):
        self.is_playing = False
        self.frame_index = 0
        self._timer = 0.0
        self._apply_current_frame()

    def update(self, delta_time):
        if not self.is_playing or not self.current_animation or self.sprite_renderer is None:
            return

        frames = self.animations.get(self.current_animation)
        if not frames or self.frame_duration <= 0:
            return

        self._timer += delta_time
        advanced = False

        # A while-loop (not `if`) so a large delta_time - e.g. after a brief
        # freeze - catches up by however many frames actually elapsed,
        # instead of the animation just running one frame per update no
        # matter how much time passed.
        while self._timer >= self.frame_duration and self.is_playing:
            self._timer -= self.frame_duration  # carry the remainder forward
            was_playing = self.is_playing
            self._advance_frame(frames)
            advanced = True
            if was_playing and not self.is_playing:
                self._dispatch_finished()

        if advanced:
            self._apply_current_frame()

    def _dispatch_finished(self):
        for callback in list(self.on_finished):  # copy: a callback may unsubscribe itself
            try:
                callback(self, self.current_animation)
            except Exception as exc:  # noqa: BLE001 - a bad callback must not crash the game
                from engine.core.debug_manager import DebugManager
                owner = getattr(self.game_object, "name", "?")
                DebugManager.log_error(f"Animator on_finished callback on '{owner}' raised {exc!r}")

    def _advance_frame(self, frames):
        if self.reverse:
            self.frame_index -= 1
            if self.frame_index < 0:
                if self.loop:
                    self.frame_index = len(frames) - 1
                else:
                    self.frame_index = 0
                    self.is_playing = False
        else:
            self.frame_index += 1
            if self.frame_index >= len(frames):
                if self.loop:
                    self.frame_index = 0
                else:
                    self.frame_index = len(frames) - 1
                    self.is_playing = False

    def _apply_current_frame(self):
        if self.sprite_renderer and self.current_animation in self.animations:
            frames = self.animations[self.current_animation]
            if frames and 0 <= self.frame_index < len(frames):
                self.sprite_renderer.sprite = frames[self.frame_index]
