"""AudioSource: plays a sound effect or a looping sound attached to an object,
Unity-style - one component type covers both a one-shot "coin pickup" sound and
a looping engine hum.

It plays through `AudioManager` (engine/audio/audio_manager.py), so it obeys
the master/SFX volume sliders and mute, plays on the SFX channels (never the
music decks), and can be *spatial*: with `spatial=True` its volume and stereo
pan follow the distance/offset between this object and the listener (the
active camera by default), updated every frame while it plays.

For background music use `AudioManager.play_music()` / `crossfade_to()` instead
- an AudioSource is for sounds that belong to an object in the world.
"""
from engine.audio.audio_manager import AudioManager
from engine.components.component import Component
from engine.core.debug_manager import DebugManager


class AudioSource(Component):
    def __init__(self, path=None, volume=1.0, loop=False, play_on_start=False,
                 spatial=False, min_distance=100.0, max_distance=800.0, rolloff="linear"):
        super().__init__()
        self.volume = volume
        self.loop = loop
        self.play_on_start = play_on_start
        self.spatial = spatial
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.rolloff = rolloff

        self._sound = None
        self._handle = None

        if path is not None:
            self.load(path)

    def load(self, path):
        """Load (or replace) the sound this source plays. Failures (a
        missing file, an unsupported format, no audio device available)
        are logged via DebugManager rather than raised - a missing sound
        file shouldn't crash the whole game."""
        sound = AudioManager.load_sound(path)
        if sound is None:
            owner = getattr(self.game_object, "name", "?")
            DebugManager.log_error(f"AudioSource on '{owner}' failed to load '{path}'.")
        self._sound = sound

    def start(self):
        if self.play_on_start:
            self.play()

    def _position(self):
        return self.game_object.transform.get_world_xy() if self.spatial else None

    def play(self):
        """Starts playback from the beginning. Safe to call with no sound
        loaded (logs a warning, does nothing) or while already playing
        (restarts it)."""
        if self._sound is None:
            owner = getattr(self.game_object, "name", "?")
            DebugManager.log_warning(f"AudioSource on '{owner}' has no sound loaded - call load(path) first.")
            return
        self.stop()
        self._handle = AudioManager.play_sfx(
            self._sound, volume=self.volume, loop=self.loop, position=self._position(),
            min_distance=self.min_distance, max_distance=self.max_distance, rolloff=self.rolloff)

    def stop(self):
        if self._handle is not None:
            self._handle.stop()
            self._handle = None

    def pause(self):
        if self._handle is not None:
            self._handle.pause()

    def resume(self):
        if self._handle is not None:
            self._handle.resume()

    def set_volume(self, volume):
        self.volume = volume
        if self._handle is not None:
            self._handle.set_volume(volume)

    def update(self, delta_time):
        # Keep a playing spatial sound glued to its object.
        if self.spatial and self._handle is not None:
            self._handle.set_position(self.game_object.transform.get_world_xy())

    def on_destroy(self):
        self.stop()

    @property
    def is_playing(self):
        return self._handle is not None and self._handle.is_playing
