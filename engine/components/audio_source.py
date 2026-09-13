"""AudioSource: plays a sound effect or a looping track, Unity-style -
one component type covers both a one-shot "coin pickup" sound and a
looping "background music" track, the way Unity's AudioSource does.

Uses `pygame.mixer.Sound`, which `pygame.init()` (called by Engine)
already initializes as part of setting up every pygame subsystem - no
extra setup needed. See the README's "Audio" section for why this engine
uses pygame.mixer rather than adding a separate audio dependency: it
already covers what a typical 2D game needs (effects, music, per-source
volume, looping), so pulling in another library would be extra
complexity for no real capability gained. If your game needs something
pygame.mixer genuinely can't do (e.g. advanced DSP/effects), swapping in
another library (e.g. `pyo`) here is the natural extension point - this
class is intentionally the only place in the engine that touches audio.
"""
import pygame

from engine.components.component import Component
from engine.core.debug_manager import DebugManager


class AudioSource(Component):
    def __init__(self, path=None, volume=1.0, loop=False, play_on_start=False):
        super().__init__()
        self.volume = volume
        self.loop = loop
        self.play_on_start = play_on_start

        self._sound = None
        self._channel = None

        if path is not None:
            self.load(path)

    def load(self, path):
        """Load (or replace) the sound this source plays. Failures (a
        missing file, an unsupported format, no audio device available)
        are logged via DebugManager rather than raised - a missing sound
        file shouldn't crash the whole game."""
        try:
            self._sound = pygame.mixer.Sound(path)
            self._sound.set_volume(self.volume)
        except (pygame.error, FileNotFoundError) as exc:
            owner = getattr(self.game_object, "name", "?")
            DebugManager.log_error(f"AudioSource on '{owner}' failed to load '{path}': {exc!r}")
            self._sound = None

    def start(self):
        if self.play_on_start:
            self.play()

    def play(self):
        """Starts playback from the beginning. Safe to call with no sound
        loaded (logs a warning, does nothing) or while already playing
        (restarts it)."""
        if self._sound is None:
            owner = getattr(self.game_object, "name", "?")
            DebugManager.log_warning(f"AudioSource on '{owner}' has no sound loaded - call load(path) first.")
            return
        self._channel = self._sound.play(loops=-1 if self.loop else 0)

    def stop(self):
        if self._channel is not None:
            self._channel.stop()

    def pause(self):
        if self._channel is not None:
            self._channel.pause()

    def resume(self):
        if self._channel is not None:
            self._channel.unpause()

    def set_volume(self, volume):
        self.volume = volume
        if self._sound is not None:
            self._sound.set_volume(volume)

    @property
    def is_playing(self):
        return self._channel is not None and self._channel.get_busy()
