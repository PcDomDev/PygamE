from engine.components.component import Component
from engine.components.sprite_renderer import SpriteRenderer
from engine.rendering.surface_cache import prepare_surface


class Animator(Component):
    """
    Frame-based sprite animation, driven by a dictionary of
    `{animation_name: [surface, surface, ...]}`.

    `play(name)` is designed to be safely called every frame with the currently
    "intended" animation - which is exactly how PlayerController uses it
    (e.g., calling play("walk_right") on every single update() while the
    right key is held).

    The implementation ensures that:
    1. Calling `play()` with the same animation won't reset it to frame 0.
    2. Non-looping animations (like jump) will freeze on their last frame,
       even if `play()` is continuously polled.
    3. You can force an animation to restart from the beginning using `force_restart=True`.

    Performance:
      - Frames are converted to the display pixel format once (see
        engine/rendering/surface_cache.py), not on every blit.
      - Playback advances by `delta_time * speed`, so animation speed is tied to
        real time (never to frame rate); `speed` is a playback multiplier.
      - With `cull_offscreen=True` (default) a *looping* animation whose sprite
        was not drawn recently doesn't tick at all - a hundred off-screen
        enemies cost nothing. Non-looping animations and animations with
        `on_finished` listeners always tick, so gameplay logic that waits for
        "attack animation finished" still fires when the object is off-screen.
    """

    def __init__(self, animations=None, default_animation=None, frame_duration=0.1,
                 speed=1.0, cull_offscreen=True):
        super().__init__()
        self.animations = animations if animations is not None else {}
        self._prepare_frames()
        self.current_animation = default_animation
        self.frame_duration = frame_duration
        self.speed = speed
        self.cull_offscreen = cull_offscreen

        self.frame_index = 0
        self.sprite_renderer = None
        self._timer = 0.0

        self.is_playing = True
        self.loop = True
        self.reverse = False

        # callback(animator, anim_name) - fires once on the exact frame a
        # non-looping animation reaches its last frame. Append to subscribe.
        self.on_finished = []

    def _prepare_frames(self):
        """Convert every frame to the display format (in place, so the dict
        and lists you passed in stay the same objects)."""
        for name, frames in list(self.animations.items()):
            converted = [prepare_surface(frame) for frame in frames]
            if isinstance(frames, list):
                frames[:] = converted
            else:
                self.animations[name] = converted

    def set_animations(self, animations):
        """Replace the animation dictionary (frames are converted once)."""
        self.animations = animations
        self._prepare_frames()
        self.frame_index = 0
        self._timer = 0.0
        self._apply_current_frame()

    def start(self):
        """Called automatically when the component is initialized in the scene."""
        self.sprite_renderer = self.game_object.get_component(SpriteRenderer)
        self._prepare_frames()   # the display may not have existed at construction
        self._apply_current_frame()

    def has_animation(self, anim_name):
        """Checks if the animation exists in the dictionary.
        Useful for safely falling back to default animations."""
        return anim_name in self.animations

    def play(self, anim_name=None, loop=True, reverse=False, force_restart=False):
        """
        Starts or ensures the playback of an animation.

        Args:
            anim_name (str): Key of the animation in the animations dict.
            loop (bool): If True, animation repeats indefinitely.
            reverse (bool): If True, plays frames from last to first.
            force_restart (bool): If True, forces the animation to reset to frame 0,
                                  even if it is already the current animation.
        """
        if anim_name is None or anim_name not in self.animations:
            return

        is_new_playback = (anim_name != self.current_animation) or force_restart

        if is_new_playback:
            self.current_animation = anim_name
            self.loop = loop
            self.reverse = reverse
            self.is_playing = True
            self._timer = 0.0

            frames = self.animations[anim_name]
            self.frame_index = (len(frames) - 1) if reverse else 0
            self._apply_current_frame()

        else:
            self.loop = loop
            self.reverse = reverse

            frames = self.animations[anim_name]
            is_at_last_frame = (self.frame_index == 0) if self.reverse else (self.frame_index == len(frames) - 1)

            if not self.loop and is_at_last_frame:
                # Let it remain frozen on the last frame (prevents jumping
                # animations from resetting every frame).
                pass
            else:
                # Ensure it's playing (useful if it was previously paused via pause())
                self.is_playing = True

    def pause(self):
        """Pauses the current animation at the current frame."""
        self.is_playing = False

    def stop(self):
        """Stops the animation and resets it to the first frame."""
        self.is_playing = False
        self.frame_index = 0
        self._timer = 0.0
        self._apply_current_frame()

    def _can_skip_offscreen(self):
        return self.cull_offscreen and self.loop and not self.on_finished

    def update(self, delta_time):
        """Advances animation frames based on elapsed time."""
        if not self.is_playing or not self.current_animation or self.sprite_renderer is None:
            return

        frames = self.animations.get(self.current_animation)
        if not frames or self.frame_duration <= 0:
            return

        if self._can_skip_offscreen() and not self.sprite_renderer.is_visible:
            return

        self._timer += delta_time * self.speed
        advanced = False

        # A while-loop (not `if`) so a large delta_time - e.g., after a brief
        # freeze - catches up by however many frames actually elapsed.
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
        """Safely fires all subscribed callbacks when a non-looping animation ends."""
        for callback in list(self.on_finished):  # copy: a callback may unsubscribe itself
            try:
                callback(self, self.current_animation)
            except Exception as exc:  # noqa: BLE001 - a bad callback must not crash the game
                from engine.core.debug_manager import DebugManager
                owner = getattr(self.game_object, "name", "?")
                DebugManager.log_error(f"Animator on_finished callback on '{owner}' raised {exc!r}")

    def _advance_frame(self, frames):
        """Handles frame increment/decrement logic and looping rules."""
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
        """Passes the active frame (Surface/Texture) to the SpriteRenderer."""
        if self.sprite_renderer and self.current_animation in self.animations:
            frames = self.animations[self.current_animation]
            if frames and 0 <= self.frame_index < len(frames):
                self.sprite_renderer.set_sprite(frames[self.frame_index])
