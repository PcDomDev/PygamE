"""Unity-style persistent settings: `PlayerPrefs.set_int("high_score", 10)`.

Backed by one JSON file (default `playerprefs.json` in the working directory;
change it with `PlayerPrefs.set_path(...)` before first use). Values are typed:
`get_int` on a key that holds a string returns the default, like Unity.

    PlayerPrefs.set_int("high_score", 4200)
    PlayerPrefs.set_float("music_volume", 0.6)
    PlayerPrefs.set_string("player_name", "Georgii")
    PlayerPrefs.save()                       # nothing hits the disk until this

Reliability: `save()` writes a temp file then atomically replaces the real one,
so a crash mid-save can't leave a half-written file; a file that fails to
parse on load is moved aside to `<file>.corrupt` (and logged) rather than
crashing the game or being silently overwritten.
"""
import json
import math
import os

from engine.core.debug_manager import DebugManager


class PlayerPrefs:
    DEFAULT_PATH = "playerprefs.json"

    _path = DEFAULT_PATH
    _data = None          # loaded lazily
    _dirty = False

    # -- configuration -----------------------------------------------------------

    @classmethod
    def set_path(cls, path):
        """Use a different file. Drops the in-memory copy (unsaved changes are
        discarded) so the next access loads from the new location."""
        cls._path = str(path)
        cls._data = None
        cls._dirty = False

    @classmethod
    def get_path(cls):
        return cls._path

    # -- loading / saving -----------------------------------------------------------

    @classmethod
    def _load(cls):
        if cls._data is not None:
            return cls._data
        cls._data = {}
        if not os.path.exists(cls._path):
            return cls._data
        try:
            with open(cls._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("top-level JSON value is not an object")
            cls._data = {k: v for k, v in raw.items()
                         if isinstance(k, str) and isinstance(v, (int, float, str)) and not isinstance(v, bool)}
        except (OSError, ValueError) as exc:   # JSONDecodeError is a ValueError
            DebugManager.log_error(f"PlayerPrefs: couldn't read '{cls._path}' ({exc!r}); starting empty.")
            try:
                os.replace(cls._path, cls._path + ".corrupt")
            except OSError:
                pass
            cls._data = {}
        return cls._data

    @classmethod
    def reload(cls):
        """Discard unsaved changes and re-read the file."""
        cls._data = None
        cls._dirty = False
        cls._load()

    @classmethod
    def save(cls):
        """Write to disk (atomically). Returns True on success."""
        data = cls._load()
        tmp = cls._path + ".tmp"
        try:
            parent = os.path.dirname(os.path.abspath(cls._path))
            os.makedirs(parent, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, cls._path)
        except OSError as exc:
            DebugManager.log_error(f"PlayerPrefs: couldn't save '{cls._path}': {exc!r}")
            return False
        cls._dirty = False
        return True

    @classmethod
    def is_dirty(cls):
        """True if there are changes not yet written by save()."""
        return cls._dirty

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _check_key(key):
        if not isinstance(key, str) or not key:
            raise TypeError("PlayerPrefs keys must be non-empty strings")

    @classmethod
    def _set(cls, key, value):
        cls._check_key(key)
        data = cls._load()
        if data.get(key) != value or type(data.get(key)) is not type(value):
            data[key] = value
            cls._dirty = True

    # -- typed access -----------------------------------------------------------

    @classmethod
    def set_int(cls, key, value):
        if isinstance(value, float) or not isinstance(value, (int, bool)):
            raise TypeError(f"PlayerPrefs.set_int expects an int, got {type(value).__name__}")
        cls._set(key, int(value))

    @classmethod
    def get_int(cls, key, default=0):
        value = cls._load().get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return default

    @classmethod
    def set_float(cls, key, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"PlayerPrefs.set_float expects a number, got {type(value).__name__}")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("PlayerPrefs.set_float: value must be finite (JSON can't store NaN/inf)")
        cls._set(key, value)

    @classmethod
    def get_float(cls, key, default=0.0):
        value = cls._load().get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return default

    @classmethod
    def set_string(cls, key, value):
        if not isinstance(value, str):
            raise TypeError(f"PlayerPrefs.set_string expects a str, got {type(value).__name__}")
        cls._set(key, value)

    @classmethod
    def get_string(cls, key, default=""):
        value = cls._load().get(key)
        return value if isinstance(value, str) else default

    # -- housekeeping --------------------------------------------------------------

    @classmethod
    def has_key(cls, key):
        return key in cls._load()

    @classmethod
    def delete_key(cls, key):
        data = cls._load()
        if key in data:
            del data[key]
            cls._dirty = True

    @classmethod
    def delete_all(cls):
        data = cls._load()
        if data:
            data.clear()
            cls._dirty = True
