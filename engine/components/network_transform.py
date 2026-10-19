"""NetworkTransform: keeps this object's position (and optionally rotation)
in sync across every connected peer. Must sit on a GameObject that also has
a NetworkIdentity - NetworkManager.spawn() adds both together automatically;
add this one by hand only if you're building a networked object outside of
spawn() (rare - prefer register_prefab() + spawn() instead, which does this
for you).

On the owner (`NetworkIdentity.is_owner` is True): sends this object's
position up to `send_rate` times a second, and skips sending anything for a
frame where nothing actually moved (a player who joins later is caught up
automatically - see NetworkManager's "late join" note). `send_rate=0` turns
sending off entirely.

On every other peer: any Rigidbody2D on the same object is disabled the
moment this component starts, so it can never fight the incoming network
position with its own local gravity or collision response (see
network_manager.py's module docstring for why two machines can never safely
run physics on the same object). Instead, the position eases toward the
latest update received - the same exponential-smoothing technique Camera
uses (frame-rate independent, never overshoots) - so an update arriving only
`send_rate` times a second still reads as smooth motion at 60+ fps. The
trade-off, worth knowing: a remote copy's position always lags a little
behind the true, owning copy - bounded by network latency plus the
smoothing time constant, imperceptible on a LAN, but a real and permanent
lag, not a prediction of where the object "really" is right now.
"""
import math

from engine.components.component import Component
from engine.components.network_identity import NetworkIdentity
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.debug_manager import DebugManager


class NetworkTransform(Component):
    updates_when_static = False
    # After gameplay code (0) has moved the object this frame, before Camera (100)
    # reads it: the position that gets sent is the frame's final one.
    update_order = 50

    def __init__(self, send_rate=20, sync_rotation=False, smoothing_speed=15.0, snap_distance=600.0):
        super().__init__()
        self.send_rate = send_rate
        self.sync_rotation = sync_rotation
        self.smoothing_speed = smoothing_speed
        # A remote copy that is told to be further than this (px) from where it is jumps there
        # at once instead of gliding across the map - that is what a portal/teleport looks like
        # to other players. Normal motion moves far less than this per update. None = always glide.
        self.snap_distance = snap_distance
        self.identity = None

        self._interval = (1.0 / send_rate) if send_rate > 0 else 0.0
        self._timer = 0.0
        self._last_sent = None
        self._epoch = None
        self._warned_non_finite = False

        self._target_x = 0.0
        self._target_y = 0.0
        self._target_rotation = 0.0
        self._has_target = False

    def start(self):
        self.identity = self.game_object.get_component(NetworkIdentity)
        if self.identity is None:
            DebugManager.log_error(
                f"NetworkTransform on '{self.game_object.name}' has no NetworkIdentity - it will "
                f"not sync. Create networked objects through NetworkManager.spawn(), not by adding "
                f"NetworkTransform directly.", source="Networking")
            self.enabled = False
            return
        if not self.identity.is_owner:
            body = self.game_object.get_component(Rigidbody2D)
            if body is not None:
                body.enabled = False   # a passenger, not a driver - see the module docstring
            x, y = self.game_object.transform.get_world_xy()
            self._target_x, self._target_y = x, y
            self._target_rotation = self.game_object.transform.world_rotation
            self._has_target = True

    def update(self, delta_time):
        if self.identity is None:
            return
        if self.identity.is_owner:
            self._maybe_send(delta_time)
        else:
            self._ease_toward_target(delta_time)

    def _maybe_send(self, delta_time):
        if self._interval <= 0:
            return
        from engine.networking.network_manager import NetworkManager
        if self._epoch != NetworkManager._resync_epoch:
            # Someone joined since we last looked: forget what we last sent so the
            # current position goes out again even if the object hasn't moved.
            self._epoch = NetworkManager._resync_epoch
            self._last_sent = None
        self._timer += delta_time
        if self._timer < self._interval:
            return
        self._timer %= self._interval
        transform = self.game_object.transform
        x, y = transform.get_world_xy()
        rotation = transform.world_rotation if self.sync_rotation else 0.0
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(rotation)):
            if not self._warned_non_finite:
                self._warned_non_finite = True
                DebugManager.log_error(f"NetworkTransform on '{self.game_object.name}': position is not a "
                                       f"finite number ({x}, {y}); not sending it.", source="Networking")
            return
        snapshot = (round(x, 2), round(y, 2), round(rotation, 1))
        if snapshot == self._last_sent:
            return   # unchanged since the last send - a stationary object stops spending any bandwidth
        self._last_sent = snapshot
        NetworkManager._send_transform_update(self.identity.network_id, x, y, rotation)

    def _ease_toward_target(self, delta_time):
        if not self._has_target:
            return
        transform = self.game_object.transform
        x, y = transform.get_world_xy()
        snap = self.snap_distance
        if snap is not None:
            off_x, off_y = self._target_x - x, self._target_y - y
            if off_x * off_x + off_y * off_y > snap * snap:
                transform.set_world_position(self._target_x, self._target_y)
                if self.sync_rotation:
                    transform.rotation = self._target_rotation
                return
        t = 1.0 - math.exp(-self.smoothing_speed * delta_time)
        transform.set_world_position(x + (self._target_x - x) * t, y + (self._target_y - y) * t)
        if self.sync_rotation:
            transform.rotation += (self._target_rotation - transform.rotation) * t

    def receive_update(self, x, y, rotation):
        """Called by NetworkManager when a position update for this object
        arrives from the network. Not meant to be called from game code."""
        self._target_x = x
        self._target_y = y
        self._target_rotation = rotation
        self._has_target = True
