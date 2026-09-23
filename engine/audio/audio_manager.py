"""AudioManager: music, sound effects, volume sliders and 2D positional audio.

    AudioManager.play_music("theme.ogg", fade_in=1.5)
    AudioManager.crossfade_to("battle.ogg", duration=2.0)
    AudioManager.play_sfx("jump.wav")
    AudioManager.play_sfx("explosion.wav", position=(x, y))   # louder/panned by distance
    AudioManager.set_music_volume(0.4)                       # sliders: master / sfx / music

Structure:
  - Channels 0 and 1 are *reserved* for music (two "decks"); everything else is
    sound-effect channels. SFX can never steal a music channel, and a crowd of
    explosions can never cut the music.
  - Music is played as a `Sound` on a deck rather than through
    `pygame.mixer.music`, because that is the only way to have two tracks
    audible at once (crossfade), and because `mixer.music.fadeout()` blocks the
    whole game until it finishes. Fades here are ramped in `update(dt)` and
    never block. The trade-off: a music file is decoded into memory when it
    starts (a few MB for a compressed 3-minute track, ~30 MB as raw PCM), so
    prefer compressed OGG, and expect a short load hitch when a track starts.
  - The effective volume of anything is master * (sfx | music) * its own volume
    * attenuation, recomputed every frame, so moving a slider affects sounds
    that are already playing.
  - Positional audio: pass `position=` (world coordinates) to `play_sfx`. Volume
    falls off between `min_distance` (full volume) and `max_distance` (silent)
    around the *listener* - the active camera by default, or whatever you set
    with `AudioManager.listener` (a GameObject, an (x, y) tuple, or a callable
    returning one) - and the sound is panned left/right by its horizontal offset.
  - No audio device (or a headless machine): everything degrades to a logged
    warning and no-ops instead of raising.

Engine calls `AudioManager.update(dt)` once per frame.
"""
import math
import os

import pygame

from engine.core.debug_manager import DebugManager


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


class SoundHandle:
    """A playing sound effect. Stop it, move it, change its volume."""

    __slots__ = ("sound", "channel", "volume", "position", "min_distance", "max_distance", "rolloff", "loop")

    def __init__(self, sound, volume, position, min_distance, max_distance, rolloff, loop):
        self.sound = sound
        self.channel = None
        self.volume = volume
        self.position = position
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.rolloff = rolloff
        self.loop = loop

    @property
    def is_playing(self):
        channel = self.channel
        return channel is not None and channel.get_busy() and channel.get_sound() is self.sound

    def stop(self):
        if self.is_playing:
            self.channel.stop()
        self.channel = None

    def pause(self):
        if self.is_playing:
            self.channel.pause()

    def resume(self):
        if self.channel is not None:
            self.channel.unpause()

    def set_volume(self, volume):
        self.volume = volume

    def set_position(self, position):
        self.position = position


class _Deck:
    """One music channel plus its fade state."""

    __slots__ = ("channel", "sound", "path", "volume", "target", "rate", "track_volume", "loop", "paused")

    def __init__(self, channel):
        self.channel = channel
        self.sound = None
        self.path = None
        self.volume = 0.0        # current fade level 0..1
        self.target = 0.0        # fade level being ramped toward
        self.rate = 0.0          # fade speed, level per second
        self.track_volume = 1.0
        self.loop = True
        self.paused = False


class AudioManager:
    NUM_CHANNELS = 32
    RESERVED_CHANNELS = 2        # music decks

    listener = None              # GameObject | (x, y) | callable -> (x, y) | None (= active camera)

    _initialized = False
    _available = False
    _master = 1.0
    _sfx = 1.0
    _music = 1.0
    _muted = False
    _sounds = {}
    _handles = []
    _decks = []
    _current = None

    # -- setup -----------------------------------------------------------------

    @classmethod
    def init(cls):
        """Ensure the mixer is ready. Returns False (once, with a log line) if
        there is no usable audio device."""
        if cls._initialized:
            return cls._available
        cls._initialized = True
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.set_num_channels(cls.NUM_CHANNELS)
            pygame.mixer.set_reserved(cls.RESERVED_CHANNELS)
            cls._decks = [_Deck(pygame.mixer.Channel(i)) for i in range(cls.RESERVED_CHANNELS)]
            cls._available = True
        except pygame.error as exc:
            DebugManager.log_warning(f"AudioManager: no audio available ({exc}); sound is disabled.", source="Audio")
            cls._available = False
        return cls._available

    @classmethod
    def shutdown(cls):
        if cls._initialized and cls._available:
            cls.stop_all_sfx()
            cls.stop_music()
        cls._sounds.clear()
        cls._handles = []
        cls._decks = []
        cls._current = None
        cls._initialized = False
        cls._available = False

    # -- volume sliders ----------------------------------------------------------

    @classmethod
    def set_master_volume(cls, volume):
        cls._master = _clamp01(volume)

    @classmethod
    def set_sfx_volume(cls, volume):
        cls._sfx = _clamp01(volume)

    @classmethod
    def set_music_volume(cls, volume):
        cls._music = _clamp01(volume)

    @classmethod
    def get_master_volume(cls):
        return cls._master

    @classmethod
    def get_sfx_volume(cls):
        return cls._sfx

    @classmethod
    def get_music_volume(cls):
        return cls._music

    @classmethod
    def mute(cls):
        cls._muted = True

    @classmethod
    def unmute(cls):
        cls._muted = False

    @classmethod
    def toggle_mute(cls):
        cls._muted = not cls._muted

    @classmethod
    def is_muted(cls):
        return cls._muted

    @classmethod
    def _sfx_gain(cls):
        return 0.0 if cls._muted else cls._master * cls._sfx

    @classmethod
    def _music_gain(cls):
        return 0.0 if cls._muted else cls._master * cls._music

    @classmethod
    def save_settings(cls, prefix="audio."):
        """Persist the three sliders through PlayerPrefs (call PlayerPrefs.save() after)."""
        from engine.core.player_prefs import PlayerPrefs
        PlayerPrefs.set_float(prefix + "master_volume", cls._master)
        PlayerPrefs.set_float(prefix + "sfx_volume", cls._sfx)
        PlayerPrefs.set_float(prefix + "music_volume", cls._music)

    @classmethod
    def load_settings(cls, prefix="audio."):
        from engine.core.player_prefs import PlayerPrefs
        cls.set_master_volume(PlayerPrefs.get_float(prefix + "master_volume", cls._master))
        cls.set_sfx_volume(PlayerPrefs.get_float(prefix + "sfx_volume", cls._sfx))
        cls.set_music_volume(PlayerPrefs.get_float(prefix + "music_volume", cls._music))

    # -- loading ---------------------------------------------------------------

    @classmethod
    def load_sound(cls, path, cache=True):
        """A `pygame.mixer.Sound` for `path` (cached), or None - a missing or
        unsupported file is logged, never raised."""
        if not cls.init():
            return None
        key = os.fspath(path)
        if cache and key in cls._sounds:
            return cls._sounds[key]
        try:
            sound = pygame.mixer.Sound(key)
        except (pygame.error, FileNotFoundError, OSError) as exc:
            DebugManager.log_error(f"AudioManager: couldn't load '{key}': {exc!r}", source="Audio")
            return None
        if cache:
            cls._sounds[key] = sound
        return sound

    preload = load_sound

    @classmethod
    def _resolve(cls, sound, cache=True):
        if isinstance(sound, (str, os.PathLike)):
            return cls.load_sound(sound, cache=cache)
        return sound

    # -- math (pure functions; unit-testable without a mixer) ---------------------------

    @staticmethod
    def compute_attenuation(distance, min_distance, max_distance, rolloff="linear"):
        """Gain 0..1 for a source `distance` away. Full volume inside
        `min_distance`, silent at `max_distance`."""
        if distance <= min_distance:
            return 1.0
        if distance >= max_distance or max_distance <= min_distance:
            return 0.0
        fraction = (distance - min_distance) / (max_distance - min_distance)
        if rolloff == "inverse":
            return max(0.0, (min_distance / distance) * (1.0 - fraction))
        return 1.0 - fraction

    @staticmethod
    def compute_pan(dx, max_distance):
        """-1 (hard left) .. +1 (hard right) from the horizontal offset; fully
        panned at half the audible range."""
        if max_distance <= 0:
            return 0.0
        return max(-1.0, min(1.0, dx / (max_distance * 0.5)))

    @staticmethod
    def stereo_volumes(volume, pan):
        """(left, right) channel volumes for a mono `volume` at `pan`."""
        return volume * (1.0 - max(0.0, pan)), volume * (1.0 + min(0.0, pan))

    @classmethod
    def _listener_position(cls):
        source = cls.listener
        if source is None:
            from engine.core.scene_manager import SceneManager
            scene = SceneManager.active_scene
            camera = scene.active_camera if scene is not None else None
            return (camera.position.x, camera.position.y) if camera is not None else None
        if callable(source):
            source = source()
        if hasattr(source, "transform"):
            return source.transform.get_world_xy()
        if hasattr(source, "x") and hasattr(source, "y"):
            return source.x, source.y
        return source[0], source[1]

    @classmethod
    def _handle_volumes(cls, handle):
        gain = cls._sfx_gain() * handle.volume
        if handle.position is None:
            return gain, gain
        listener = cls._listener_position()
        if listener is None:
            return gain, gain
        px, py = handle.position
        dx, dy = px - listener[0], py - listener[1]
        attenuation = cls.compute_attenuation(math.hypot(dx, dy), handle.min_distance,
                                              handle.max_distance, handle.rolloff)
        return cls.stereo_volumes(gain * attenuation, cls.compute_pan(dx, handle.max_distance))

    # -- sound effects ------------------------------------------------------------

    @classmethod
    def play_sfx(cls, sound, volume=1.0, loop=False, position=None,
                 min_distance=100.0, max_distance=800.0, rolloff="linear"):
        """Play a sound effect (a path or a `pygame.mixer.Sound`). Returns a
        `SoundHandle`, or None if nothing played (no audio, load failure, all
        channels busy, or a positional sound that is out of earshot)."""
        if not cls.init():
            return None
        resolved = cls._resolve(sound)
        if resolved is None:
            return None
        handle = SoundHandle(resolved, volume, position, min_distance, max_distance, rolloff, loop)
        left, right = cls._handle_volumes(handle)
        if position is not None and left <= 0.0 and right <= 0.0 and not loop:
            return None                      # inaudible: don't waste a channel
        channel = resolved.play(loops=-1 if loop else 0)
        if channel is None:
            return None                      # every SFX channel is busy
        channel.set_volume(left, right)
        handle.channel = channel
        cls._handles.append(handle)
        return handle

    @classmethod
    def stop_all_sfx(cls):
        for handle in list(cls._handles):
            handle.stop()
        cls._handles = []

    @classmethod
    def active_sfx_count(cls):
        return sum(1 for h in cls._handles if h.is_playing)

    # -- music ---------------------------------------------------------------------

    @classmethod
    def _deck_gain(cls, deck):
        return cls._music_gain() * deck.volume * deck.track_volume

    @classmethod
    def _start_deck(cls, deck, sound, path, loop, track_volume, fade_in):
        deck.sound = sound
        deck.path = path
        deck.loop = loop
        deck.track_volume = track_volume
        deck.paused = False
        if fade_in > 0:
            deck.volume, deck.target, deck.rate = 0.0, 1.0, 1.0 / fade_in
        else:
            deck.volume, deck.target, deck.rate = 1.0, 1.0, 0.0
        deck.channel.play(sound, loops=-1 if loop else 0)
        deck.channel.set_volume(cls._deck_gain(deck))

    @classmethod
    def _release_deck(cls, deck):
        if deck.channel is not None:
            deck.channel.stop()
        deck.sound = None
        deck.path = None
        deck.volume = deck.target = deck.rate = 0.0
        deck.paused = False
        if cls._current is deck:
            cls._current = None

    @classmethod
    def play_music(cls, path, loop=True, fade_in=0.0, volume=1.0):
        """Start a track, cutting whatever music was playing. `fade_in` (seconds)
        ramps it up from silence. Returns False if it couldn't be started."""
        if not cls.init():
            return False
        sound = cls._resolve(path, cache=False)
        if sound is None:
            return False
        for deck in cls._decks:
            cls._release_deck(deck)
        deck = cls._decks[0]
        cls._start_deck(deck, sound, os.fspath(path) if isinstance(path, (str, os.PathLike)) else None,
                        loop, volume, fade_in)
        cls._current = deck
        return True

    @classmethod
    def crossfade_to(cls, path, duration=2.0, loop=True, volume=1.0):
        """Fade the current track out while fading `path` in, overlapping.
        Equivalent to play_music(fade_in=duration) if nothing is playing."""
        if not cls.init():
            return False
        current = cls._current
        if current is None or current.sound is None or duration <= 0:
            return cls.play_music(path, loop=loop, fade_in=max(duration, 0.0), volume=volume)
        sound = cls._resolve(path, cache=False)
        if sound is None:
            return False
        other = cls._decks[1] if current is cls._decks[0] else cls._decks[0]
        if other.sound is not None:
            cls._release_deck(other)         # a previous crossfade's leftover: cut it
        current.target = 0.0
        current.rate = 1.0 / duration
        cls._start_deck(other, sound, os.fspath(path) if isinstance(path, (str, os.PathLike)) else None,
                        loop, volume, duration)
        cls._current = other
        return True

    @classmethod
    def stop_music(cls, fade_out=0.0):
        """Stop the music, immediately or fading out over `fade_out` seconds."""
        for deck in cls._decks:
            if deck.sound is None:
                continue
            if fade_out > 0:
                deck.target = 0.0
                deck.rate = 1.0 / fade_out
            else:
                cls._release_deck(deck)
        if fade_out > 0:
            cls._current = None

    @classmethod
    def pause_music(cls):
        for deck in cls._decks:
            if deck.sound is not None and not deck.paused:
                deck.channel.pause()
                deck.paused = True

    @classmethod
    def resume_music(cls):
        for deck in cls._decks:
            if deck.sound is not None and deck.paused:
                deck.channel.unpause()
                deck.paused = False

    @classmethod
    def current_music(cls):
        """Path of the track that is (fading) in, or None."""
        return cls._current.path if cls._current is not None else None

    @classmethod
    def is_music_playing(cls):
        return any(d.sound is not None and d.channel.get_busy() for d in cls._decks)

    @classmethod
    def music_level(cls, deck_index=None):
        """Current fade level(s), for debugging/tests: the current deck's, or a given deck's."""
        if deck_index is not None:
            return cls._decks[deck_index].volume
        return cls._current.volume if cls._current is not None else 0.0

    # -- per-frame ------------------------------------------------------------------

    @classmethod
    def update(cls, delta_time):
        """Advance fades and refresh volumes (sliders, listener movement)."""
        if not cls._available:
            return

        if cls._handles:
            alive = []
            for handle in cls._handles:
                if handle.is_playing:
                    left, right = cls._handle_volumes(handle)
                    handle.channel.set_volume(left, right)
                    alive.append(handle)
            cls._handles = alive

        for deck in cls._decks:
            if deck.sound is None:
                continue
            if deck.volume != deck.target:
                step = deck.rate * delta_time
                if deck.volume < deck.target:
                    deck.volume = min(deck.target, deck.volume + step)
                else:
                    deck.volume = max(deck.target, deck.volume - step)
            if deck.target <= 0.0 and deck.volume <= 0.0:
                cls._release_deck(deck)          # faded out
            elif not deck.paused and not deck.channel.get_busy():
                cls._release_deck(deck)          # a non-looping track ended
            else:
                deck.channel.set_volume(cls._deck_gain(deck))
