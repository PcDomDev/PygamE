"""NetworkState: a small set of named values - health, a score, a facing
direction, "is the door open" - that every peer sees for one networked
object. Attach it to a prefab next to (or instead of) NetworkTransform:

    def make_player(x, y, **kwargs):
        go = GameObject(x, y, name="Player")
        go.add_component(NetworkState({"hp": 100}))
        return go

    state = player.get_component(NetworkState)
    state.set("hp", 80)                       # on the OWNER: every peer sees it
    state.get("hp")                           # anywhere
    state.on_changed.append(lambda key, value, is_local: ...)

The same ownership rule as NetworkTransform applies: only the owner of the
object may change its state; `set()` on any other peer logs a warning and does
nothing (to ask the owner to change something, send it an RPC). Changes are
sent as small deltas, at most `send_rate` times a second - a value that keeps
changing every frame costs one message per interval, not one per frame - and a
player who joins later receives the current values along with the object.

Values must be plain JSON data (numbers, strings, booleans, None, lists, dicts
with string keys). Treat what `get()` returns as read-only: changing a list you
got from `get()` in place bypasses set() and is never sent - call `set()` with
a new value instead.
"""
import copy

from engine.components.component import Component
from engine.components.network_identity import NetworkIdentity
from engine.core.debug_manager import DebugManager
from engine.networking import protocol


def _same(a, b):
    # 1 == True in Python; a state that flips between them is a real change.
    return type(a) is type(b) and a == b


class NetworkState(Component):
    def __init__(self, initial=None, send_rate=10):
        super().__init__()
        self.send_rate = send_rate
        # Callbacks: fn(key, value, is_local). Fired on every peer when a value
        # actually changes; is_local is True on the peer that called set().
        self.on_changed = []
        self.identity = None

        self._values = protocol.normalize_json(dict(initial), "NetworkState initial values") if initial else {}
        self._interval = (1.0 / send_rate) if send_rate > 0 else 0.0
        self._timer = 0.0
        self._dirty = set()
        self._epoch = None
        self._warned_not_owner = False

    def start(self):
        self.identity = self.game_object.get_component(NetworkIdentity)
        if self.identity is None:
            DebugManager.log_error(
                f"NetworkState on '{self.game_object.name}' has no NetworkIdentity - it will not sync. "
                f"Create networked objects through NetworkManager.spawn().", source="Networking")

    # -- reading -----------------------------------------------------------------

    def get(self, key, default=None):
        return self._values.get(key, default)

    def items(self):
        """A fresh list of (key, value) pairs."""
        return list(self._values.items())

    def snapshot(self):
        """A deep copy of every current value."""
        return copy.deepcopy(self._values)

    # -- writing (owner only) -----------------------------------------------------

    def set(self, key, value):
        """Set `key` to `value` and replicate it. Returns True if applied (or
        already had that value), False if this peer isn't the owner."""
        if not isinstance(key, str):
            raise TypeError(f"NetworkState keys must be strings, got {type(key).__name__}")
        if self.identity is None:
            DebugManager.log_warning("NetworkState.set() on an object with no NetworkIdentity; ignored.",
                                     source="Networking")
            return False
        if not self.identity.is_owner:
            if not self._warned_not_owner:
                self._warned_not_owner = True
                DebugManager.log_warning(
                    f"NetworkState.set({key!r}) ignored on '{self.game_object.name}': only the owner "
                    f"(player {self.identity.owner_id}) can change its state. Send the owner an RPC to "
                    f"ask for the change.", source="Networking")
            return False
        value = protocol.normalize_json(value, f"NetworkState value for {key!r}")
        if key in self._values and _same(self._values[key], value):
            return True
        self._values[key] = value
        self._dirty.add(key)
        self._fire(key, value, True)
        return True

    # -- networking (called by the engine) ----------------------------------------

    def update(self, delta_time):
        if self.identity is None or not self.identity.is_owner:
            return
        from engine.networking.network_manager import NetworkManager
        if self._epoch != NetworkManager._resync_epoch:
            # Someone joined since we last looked: send everything again.
            self._epoch = NetworkManager._resync_epoch
            self._dirty.update(self._values)
        self._timer += delta_time
        if not self._dirty or self._interval <= 0 or self._timer < self._interval:
            return
        self._timer = 0.0
        keys = sorted(self._dirty)
        self._dirty.clear()
        NetworkManager._send_state_update(self.identity.network_id,
                                          {key: self._values[key] for key in keys if key in self._values})

    def apply_remote(self, values):
        """Called by NetworkManager when state for this object arrives. Not
        meant to be called from game code."""
        for key, value in values.items():
            if not isinstance(key, str):
                continue
            if key in self._values and _same(self._values[key], value):
                continue
            self._values[key] = value
            self._fire(key, value, False)

    def _fire(self, key, value, is_local):
        for callback in list(self.on_changed):   # a copy: a callback may unsubscribe itself
            try:
                callback(key, value, is_local)
            except Exception as exc:  # noqa: BLE001 - a game callback must not break networking
                DebugManager.log_error(f"NetworkState on_changed callback raised {exc!r}", source="Networking")
