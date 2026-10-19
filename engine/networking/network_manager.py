"""NetworkManager: host a game, join one, call remote procedures, and keep
networked objects, their positions and their state in sync across every
connected player. Static-style, like AudioManager and Input: reachable from
anywhere, no reference to Engine needed. Engine.run() calls `update()` every
frame and `shutdown()` on exit automatically - see engine/core/app.py.

Topology: a star. One process is the *host* (it also plays - there is no
separate, non-playing server); every other process is a *client*, connected
to the host only, never to each other. Every piece of state that must agree
across players - who exists, where they are, who owns what - flows through
the host: a client that wants to spawn or destroy a networked object asks the
host to do it, and what the host decides is what actually happens, replicated
back to every peer, the host included. This one rule is what keeps every
peer's world consistent without full lockstep simulation: a client never has
to "undo" something it did locally that the host disagreed with, because a
client never speculatively changes shared state in the first place.

What is NOT synced automatically: a Rigidbody2D's simulation. Physics runs
independently on every machine against its own Time.fixed_delta_time, and two
independent float simulations *will* drift apart over time even given
identical inputs. So exactly one machine may ever be the source of truth for
a given networked object's motion - that is what NetworkIdentity.owner_id and
NetworkTransform are for (engine/components/network_identity.py,
network_transform.py): the owner runs real physics and broadcasts its
position; every other peer's copy has its own Rigidbody2D disabled and just
eases toward whatever position it was last told. Values that aren't a
position (health, score, "door is open") travel through NetworkState the same
way, and one-off events ("player X fired", "load level 2") through RPCs.

A player who joins late is caught up automatically: the host sends the
newcomer a copy of every networked object that already exists (at its current
position, with its current NetworkState) right after the handshake. Game
state that lives *outside* networked objects (a round timer, which level is
loaded) is yours to send - the "network_player_joined" event fires on the host
the moment someone arrives, which is the place to send them an RPC.

Trust model: this is built for friends on a LAN, not for strangers on the
internet. Every connected client is trusted, with these guard rails: a client
can only drive the position and state of objects it owns, can only ask for
objects to be owned by itself or the host, can only despawn objects it owns,
and a malformed or hostile message is dropped (and logged) instead of
crashing the host. There is no encryption and no authentication.

Transport: plain TCP, one persistent socket per client-to-host link, framed
with a 4-byte length prefix (protocol.py). TCP's ordering and reliability are
exactly what shared game state needs, and are far simpler to reason about
than hand-rolled UDP reliability - the trade-off is a little more latency
under packet loss, which essentially never happens on a real LAN. Optional
UDP broadcast (discovery.py) exists only so players don't have to type an IP
address - no gameplay data ever travels over UDP.

Concurrency: none. Everything here is driven by one call per frame,
`update()`, which polls every socket without blocking and then processes
whatever arrived. There is no background thread anywhere in this module - the
one thread already running your game frame is the only thread that ever
touches game state, so nothing in the Scene/GameObject graph needs to be
thread-safe on networking's account, and nothing here can preempt your code
mid-frame.

    NetworkManager.host(port=7777, name="Alice's Game")
    NetworkManager.join("192.168.1.42")
    NetworkManager.register_prefab("player", make_player)
    NetworkManager.spawn("player", 100, 100)
    NetworkManager.send_rpc("say", "hi everyone!", target="all")
    EventBus.subscribe("network_player_joined", on_player_joined)
"""
import errno
import math
import os
import select
import socket
import time as _time

from engine.core.debug_manager import DebugManager
from engine.core.event_bus import EventBus
from engine.core.game_object import GameObject
from engine.core.scene_manager import SceneManager
from engine.networking import protocol
from engine.networking.connection import Connection
from engine.networking.discovery import LanAdvertiser, LanBrowser

DEFAULT_PORT = 7777
DEFAULT_DISCOVERY_PORT = 7778
HOST_PLAYER_ID = 0

MAX_PENDING_CONNECTIONS = 32   # sockets that connected but haven't said "hello" yet
_CONNECT_IN_PROGRESS = (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_id(value):
    return isinstance(value, int) and not isinstance(value, bool)


class PlayerInfo:
    """One entry in `NetworkManager.players()`. `ping_ms` is the last measured
    round-trip time between this machine and that player (None for yourself,
    and until the first measurement arrives)."""

    __slots__ = ("id", "name", "ping_ms")

    def __init__(self, id, name, ping_ms):
        self.id = id
        self.name = name
        self.ping_ms = ping_ms

    def __repr__(self):
        return f"PlayerInfo(id={self.id}, name={self.name!r}, ping_ms={self.ping_ms})"


class _PendingClient:
    """A host-side socket that has connected but not yet completed the hello/
    welcome handshake. Kept apart from `_connections` (which holds only
    fully-joined players) so a half-open socket can never be mistaken for a
    real player."""

    __slots__ = ("connection", "deadline")

    def __init__(self, connection, deadline):
        self.connection = connection
        self.deadline = deadline


class NetworkManager:
    # -- state -----------------------------------------------------------------
    # One global session, like SceneManager's single active scene: a running
    # copy of the game is host XOR client XOR neither, never more than one.
    is_host = False
    is_client = False
    is_connecting = False       # client only: mid-handshake, not yet confirmed either way
    is_connected = False        # True once host() succeeds, or a client's handshake completes
    local_player_id = None      # 0 on the host; assigned by the host for a client; None otherwise
    local_name = "Player"
    session_name = "Game"
    max_players = 8             # total, host included
    port = None                 # host only: the TCP port actually being listened on
    accepting_players = True    # host only: set False to refuse (and stop advertising to) newcomers

    # Tunables - plain class attributes, change them any time:
    ping_interval = 2.0         # seconds between latency probes to each peer
    peer_timeout = 8.0          # no traffic at all from a peer for this long -> treat it as dead
    handshake_timeout = 5.0     # host side: how long a fresh socket may stay silent before "hello"

    _listen_socket = None                # host: the non-blocking accepting socket
    _connections = {}                    # host: {player_id: Connection}   client: {HOST_PLAYER_ID: Connection}
    _pending = []                        # host: [_PendingClient, ...] awaiting "hello"
    _pending_connect_socket = None       # client: the raw socket while connect() is still in flight
    _handshake_deadline = None           # client: give up on the whole handshake at this monotonic time
    _join_name = None

    _advertiser = None                   # host: LanAdvertiser, if discoverable=True
    _browser = None                      # LanBrowser, only while start_discovery() is active

    _names = {}                          # {player_id: name}, for players()
    _last_seen = {}                      # host: {player_id: monotonic time of last traffic}
    _ping_sent_at = {}                   # {peer_id: {token: monotonic time sent}}
    _ping_ms = {}                        # {peer_id: last measured round-trip ms}
    _next_ping_token = 0
    _last_ping_round = 0.0
    _host_last_seen = 0.0                # client: monotonic time of last traffic from the host
    _last_update_time = None
    _resync_epoch = 0                    # bumped when someone joins; owners re-send their full transform/state

    _next_player_id = 1                  # host-only counter (0 is always the host itself)
    _next_network_id = 1                 # host-only counter for spawned-object ids
    _prefabs = {}                        # {name: factory(x, y, **kwargs) -> GameObject}
    _networked_objects = {}              # {network_id: GameObject}, kept on every peer
    _rpc_handlers = {}                   # {name: [handler, ...]}
    _applying_remote_despawn = False     # guards NetworkIdentity.on_destroy() against re-broadcasting

    # == lifecycle ================================================================

    @classmethod
    def host(cls, port=DEFAULT_PORT, name="Game", max_players=8, player_name="Host",
             discoverable=True, discovery_port=DEFAULT_DISCOVERY_PORT):
        """Start hosting: opens a listening socket and makes this process
        player 0. Returns True on success, False if the port could not be
        bound (already in use, no permission, ...), logging the reason
        either way. `port=0` lets the OS pick a free port (read it back from
        `NetworkManager.port`). `max_players` counts everyone, the host
        included. `discoverable=True` also broadcasts this game on the LAN
        (see discovery.py) so `start_discovery()` on another machine can
        find it without an IP address."""
        if cls.is_host or cls.is_client:
            DebugManager.log_warning("NetworkManager.host(): already hosting or connected; "
                                     "call disconnect() first.", source="Networking")
            return False
        try:
            max_players = max(1, int(max_players))
        except (TypeError, ValueError, OverflowError):
            DebugManager.log_error(f"NetworkManager.host(): max_players must be a number, got {max_players!r}",
                                   source="Networking")
            return False
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name != "nt":
                # Lets a restarted host reuse the port straight away. Deliberately NOT set on
                # Windows, where SO_REUSEADDR would let two hosts bind the very same port.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
            sock.listen(16)
            sock.setblocking(False)
        except (OSError, OverflowError, TypeError) as exc:
            if sock is not None:
                sock.close()
            DebugManager.log_error(f"NetworkManager.host(): couldn't listen on port {port}: {exc}",
                                   source="Networking")
            return False

        cls._reset_state()
        cls._listen_socket = sock
        cls.port = sock.getsockname()[1]
        cls.is_host = True
        cls.is_connected = True
        cls.local_player_id = HOST_PLAYER_ID
        cls.local_name = player_name
        cls.session_name = name
        cls.max_players = max_players
        cls.accepting_players = True
        cls._names[HOST_PLAYER_ID] = player_name

        if discoverable:
            cls._advertiser = LanAdvertiser(name=name, game_port=cls.port,
                                            discovery_port=discovery_port, max_players=max_players)
        DebugManager.log(f"Hosting '{name}' on port {cls.port} (local IP: {cls.local_ip()}).",
                         source="Networking")
        EventBus.emit("network_connected", as_host=True, player_id=HOST_PLAYER_ID)
        return True

    @classmethod
    def join(cls, address, port=DEFAULT_PORT, name="Player", timeout=5.0):
        """Start connecting to a host at `address:port`. Returns immediately;
        the outcome arrives later as an event - subscribe to
        "network_connected" and "network_connection_failed" on the EventBus
        before calling this (or watch `is_connected` / `is_connecting`).
        `timeout` is how long the *whole* handshake may take (TCP connect,
        then the host's welcome) before giving up with reason "timeout".
        Prefer a numeric IP address: a hostname is resolved synchronously and
        can briefly stall the frame."""
        if cls.is_host or cls.is_client:
            DebugManager.log_warning("NetworkManager.join(): already hosting or connected; "
                                     "call disconnect() first.", source="Networking")
            return
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            code = sock.connect_ex((address, port))
        except (OSError, OverflowError, TypeError, UnicodeError) as exc:
            if sock is not None:
                sock.close()
            DebugManager.log_error(f"NetworkManager.join(): couldn't start connecting to "
                                   f"{address}:{port}: {exc}", source="Networking")
            EventBus.emit("network_connection_failed", reason=str(exc))
            return
        if code != 0 and code not in _CONNECT_IN_PROGRESS:
            sock.close()
            reason = errno.errorcode.get(code, str(code))
            DebugManager.log_error(f"NetworkManager.join(): connecting to {address}:{port} failed "
                                   f"({reason}).", source="Networking")
            EventBus.emit("network_connection_failed", reason=reason)
            return

        cls._reset_state()
        cls.is_client = True
        cls.is_connecting = True
        cls.local_name = name
        cls._pending_connect_socket = sock
        cls._handshake_deadline = _time.monotonic() + max(float(timeout), 0.1)
        cls._join_name = name
        DebugManager.log(f"Connecting to {address}:{port}...", source="Networking")

    @classmethod
    def disconnect(cls):
        """Leave the current session (host or client), closing every socket
        and removing every networked object this peer knows about. Safe to
        call any time, including when not connected (then it does nothing)."""
        was_established = cls.is_host or cls.is_connected
        if cls.is_host:
            for connection in list(cls._connections.values()):
                connection.queue_send({"t": protocol.DISCONNECT, "reason": "host_closed"})
                connection.flush_and_close()
        elif cls.is_client:
            connection = cls._connections.get(HOST_PLAYER_ID)
            if connection is not None and connection.is_open:
                connection.queue_send({"t": protocol.DISCONNECT, "reason": "left"})
                connection.flush_and_close()
        cls._destroy_all_networked_objects()
        cls._reset_state()
        if was_established:
            EventBus.emit("network_disconnected", reason="left")

    @classmethod
    def shutdown(cls):
        """Called by Engine on exit: leave the session and stop browsing."""
        if cls.is_host or cls.is_client:
            cls.disconnect()
        cls.stop_discovery()

    @classmethod
    def kick(cls, player_id, reason="kicked"):
        """Host only: remove `player_id` from the session. The kicked player
        sees "network_disconnected" with `reason`. Returns True if someone
        was kicked."""
        if not cls.is_host:
            DebugManager.log_warning("NetworkManager.kick() is host-only; ignored.", source="Networking")
            return False
        connection = cls._connections.get(player_id)
        if connection is None:
            return False
        connection.queue_send({"t": protocol.DISCONNECT, "reason": str(reason)})
        connection.flush_and_close()
        cls._drop_player(player_id, reason=str(reason))
        return True

    @classmethod
    def _reset_state(cls):
        """Close every socket and forget the session. Prefabs, RPC handlers and
        the LAN browser (which has its own start/stop) deliberately survive."""
        for connection in list(cls._connections.values()):
            connection.close()
        for pending in cls._pending:
            pending.connection.close()
        for sock in (cls._listen_socket, cls._pending_connect_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        if cls._advertiser is not None:
            cls._advertiser.close()

        cls.is_host = False
        cls.is_client = False
        cls.is_connecting = False
        cls.is_connected = False
        cls.local_player_id = None
        cls.port = None
        cls._listen_socket = None
        cls._connections = {}
        cls._pending = []
        cls._pending_connect_socket = None
        cls._handshake_deadline = None
        cls._advertiser = None
        cls._names = {}
        cls._last_seen = {}
        cls._ping_sent_at = {}
        cls._ping_ms = {}
        cls._next_ping_token = 0
        cls._last_ping_round = 0.0
        cls._host_last_seen = 0.0
        cls._last_update_time = None
        cls._resync_epoch = 0
        cls._next_player_id = 1
        cls._next_network_id = 1
        cls._networked_objects = {}
        cls._applying_remote_despawn = False

    @classmethod
    def _destroy_all_networked_objects(cls):
        """Remove every networked object from this peer's scene - silently: the
        session is ending, so there is nobody left to tell. The registry is
        cleared first so that, if the destroy is deferred to the end of the
        frame, NetworkIdentity.on_destroy() finds nothing to report."""
        objects = list(cls._networked_objects.values())
        cls._networked_objects = {}
        cls._applying_remote_despawn = True
        try:
            for game_object in objects:
                try:
                    game_object.destroy()
                except Exception as exc:  # noqa: BLE001 - teardown must not raise
                    DebugManager.log_error(f"NetworkManager: cleanup raised {exc!r}", source="Networking")
        finally:
            cls._applying_remote_despawn = False

    # == per-frame ================================================================

    @classmethod
    def update(cls):
        """Poll every socket and process whatever arrived. Engine.run() calls
        this once per frame automatically - only call it yourself if you are
        driving the loop by hand (compare Scene.tick(), which does the same
        for physics)."""
        now = _time.monotonic()
        dt = 0.0 if cls._last_update_time is None else min(now - cls._last_update_time, 0.25)
        cls._last_update_time = now
        if cls.is_host:
            cls._update_host(now, dt)
        elif cls.is_client:
            # Sub-states of "is_client", told apart by what exists:
            #   a pending connect socket  -> the raw TCP connect() is still in flight
            #   a Connection to the host  -> handshaking or fully connected; _update_client()
            #                                covers both (WELCOME is what flips is_connected)
            if cls._pending_connect_socket is not None:
                cls._update_connecting(now)
            elif HOST_PLAYER_ID in cls._connections:
                cls._update_client(now)
        if cls._browser is not None:
            cls._browser.update(dt)

    @classmethod
    def _guarded(cls, handler, *args):
        """Run a message handler; a malformed message must never escape and
        crash the game loop - log it and carry on."""
        try:
            return handler(*args)
        except Exception as exc:  # noqa: BLE001
            message = args[-1] if args and isinstance(args[-1], dict) else {}
            DebugManager.log_error(f"NetworkManager: error handling a '{message.get('t')}' message: {exc!r}",
                                   source="Networking")
            return None

    # -- host side ---------------------------------------------------------------

    @classmethod
    def _update_host(cls, now, dt):
        if cls._advertiser is not None and cls.accepting_players:
            cls._advertiser.player_count = len(cls._connections) + 1
            cls._advertiser.update(dt)

        cls._accept_new_connections(now)

        for pending in list(cls._pending):
            promoted_id = None
            for message in pending.connection.pump_recv():
                if promoted_id is None:
                    promoted_id = cls._guarded(cls._handle_pending_message, pending, message)
                elif promoted_id in cls._connections:
                    # The client pipelined more messages right behind its "hello": treat them
                    # as coming from the now-joined player, in order.
                    cls._guarded(cls._handle_message_as_host, promoted_id, pending.connection, message)
            if pending in cls._pending:
                if not pending.connection.is_open:
                    cls._pending.remove(pending)
                elif now > pending.deadline:
                    DebugManager.log_warning("NetworkManager: a connection never sent 'hello' in time; "
                                             "dropping it.", source="Networking")
                    pending.connection.close()
                    cls._pending.remove(pending)

        for player_id, connection in list(cls._connections.items()):
            if player_id not in cls._connections:
                continue                      # dropped while handling an earlier player's messages
            messages = connection.pump_recv()
            if messages:
                cls._last_seen[player_id] = now
            for message in messages:
                if player_id not in cls._connections:
                    break
                cls._guarded(cls._handle_message_as_host, player_id, connection, message)
            if player_id in cls._connections and not connection.is_open:
                cls._drop_player(player_id, reason="disconnected")

        for player_id in list(cls._connections):
            if now - cls._last_seen.get(player_id, now) > cls.peer_timeout:
                DebugManager.log_warning(f"NetworkManager: player {player_id} timed out (no traffic for "
                                         f"{cls.peer_timeout:g}s); dropping.", source="Networking")
                cls._drop_player(player_id, reason="timeout")

        if now - cls._last_ping_round >= cls.ping_interval:
            cls._last_ping_round = now
            for player_id, connection in cls._connections.items():
                cls._send_ping(player_id, connection, now)

        for pending in cls._pending:
            pending.connection.pump_send()
        for connection in cls._connections.values():
            connection.pump_send()

    @classmethod
    def _accept_new_connections(cls, now):
        while True:
            try:
                sock, addr = cls._listen_socket.accept()
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            if len(cls._pending) >= MAX_PENDING_CONNECTIONS:
                sock.close()                 # a flood of half-open sockets: refuse the excess
                continue
            cls._pending.append(_PendingClient(Connection(sock, addr), now + cls.handshake_timeout))

    @classmethod
    def _reject(cls, pending, reason):
        pending.connection.queue_send({"t": protocol.REJECT, "reason": reason})
        pending.connection.flush_and_close()

    @classmethod
    def _handle_pending_message(cls, pending, message):
        """Returns the new player's id if this message completed the handshake."""
        if message.get("t") != protocol.HELLO:
            return None                      # anything before "hello" is ignored; the deadline cleans up
        if message.get("protocol") != protocol.PROTOCOL_VERSION:
            cls._reject(pending, "protocol_mismatch")
            return None
        if not cls.accepting_players:
            cls._reject(pending, "session_closed")
            return None
        if len(cls._connections) + 1 >= cls.max_players:
            cls._reject(pending, "server_full")
            return None

        connection = pending.connection
        player_id = cls._next_player_id
        cls._next_player_id += 1
        raw_name = message.get("name")
        name = raw_name.strip()[:64] if isinstance(raw_name, str) and raw_name.strip() else f"Player{player_id}"
        connection.player_id = player_id
        connection.name = name
        cls._connections[player_id] = connection
        cls._names[player_id] = name
        cls._last_seen[player_id] = _time.monotonic()
        cls._pending.remove(pending)

        roster = [{"id": HOST_PLAYER_ID, "name": cls.local_name}]
        roster += [{"id": pid, "name": cls._names.get(pid, "")} for pid in cls._connections if pid != player_id]
        connection.queue_send({"t": protocol.WELCOME, "your_id": player_id, "players": roster,
                               "max_players": cls.max_players, "session_name": cls.session_name})
        # Late join: everything that already exists, right behind the welcome (TCP keeps the order),
        # so the newcomer's world matches ours before it sees anything else.
        for network_id, game_object in sorted(cls._networked_objects.items()):
            cls._queue_spawn_snapshot(connection, network_id, game_object)
        cls._broadcast({"t": protocol.PLAYER_JOINED, "id": player_id, "name": name}, exclude=player_id)
        cls._resync_epoch += 1               # owners re-send their full transform/state to the newcomer
        DebugManager.log(f"Player {player_id} ('{name}') joined.", source="Networking")
        EventBus.emit("network_player_joined", player_id=player_id, name=name)
        return player_id

    @classmethod
    def _queue_spawn_snapshot(cls, connection, network_id, game_object):
        from engine.components.network_identity import NetworkIdentity
        from engine.components.network_state import NetworkState
        identity = game_object.get_component(NetworkIdentity)
        if identity is None:
            return
        x, y = game_object.transform.get_world_xy()
        message = {"t": protocol.SPAWN, "id": network_id, "prefab": identity.prefab_name,
                   "owner": identity.owner_id, "x": x, "y": y, "kwargs": identity.spawn_kwargs}
        state = game_object.get_component(NetworkState)
        if state is not None:
            values = state.snapshot()
            if values:
                message["state"] = values
        cls._queue(connection, message)

    @classmethod
    def _handle_message_as_host(cls, sender_id, connection, message):
        msg_type = message.get("t")
        if msg_type == protocol.RPC:
            name = message.get("name")
            args = message.get("args", [])
            kwargs = message.get("kwargs", {})
            if isinstance(name, str) and isinstance(args, list) and isinstance(kwargs, dict):
                cls._route_and_apply_rpc(name, args, kwargs, sender_id, message.get("target", "all"))
        elif msg_type == protocol.SPAWN_REQUEST:
            prefab = message.get("prefab")
            x, y = message.get("x"), message.get("y")
            owner = message.get("owner", sender_id)
            kwargs = message.get("kwargs", {})
            if not (isinstance(prefab, str) and _is_number(x) and _is_number(y) and isinstance(kwargs, dict)):
                return
            if not _is_id(owner) or owner not in (sender_id, HOST_PLAYER_ID):
                DebugManager.log_warning(f"NetworkManager: player {sender_id} asked to spawn an object owned by "
                                         f"player {owner}; refused (clients may only spawn objects owned by "
                                         f"themselves or the host).", source="Networking")
                return
            cls._perform_spawn(prefab, x, y, owner, kwargs)
        elif msg_type == protocol.DESPAWN_REQUEST:
            network_id = message.get("id")
            if _is_id(network_id):
                owner = cls._owner_of(network_id)
                if owner is not None and owner == sender_id:
                    cls._perform_despawn(network_id)
                elif owner is not None:
                    DebugManager.log_warning(f"NetworkManager: player {sender_id} asked to despawn object "
                                             f"{network_id}, owned by player {owner}; refused (only its owner "
                                             f"or the host may despawn an object - see NetworkManager.despawn()).",
                                             source="Networking")
        elif msg_type == protocol.TRANSFORM:
            network_id, x, y, rot = message.get("id"), message.get("x"), message.get("y"), message.get("rot", 0.0)
            if _is_id(network_id) and cls._owner_of(network_id) == sender_id \
                    and _is_number(x) and _is_number(y) and _is_number(rot):
                cls._apply_transform(network_id, x, y, rot)
                cls._broadcast({"t": protocol.TRANSFORM, "id": network_id, "x": x, "y": y, "rot": rot},
                               exclude=sender_id)
        elif msg_type == protocol.STATE:
            network_id, values = message.get("id"), message.get("vars")
            if _is_id(network_id) and isinstance(values, dict) and cls._owner_of(network_id) == sender_id:
                cls._apply_state(network_id, values)
                cls._broadcast({"t": protocol.STATE, "id": network_id, "vars": values}, exclude=sender_id)
        elif msg_type == protocol.PING:
            cls._queue(connection, {"t": protocol.PONG, "token": message.get("token")})
        elif msg_type == protocol.PONG:
            cls._record_pong(sender_id, message.get("token"))
        elif msg_type == protocol.DISCONNECT:
            # Drop the player right here, with the right reason - closing the connection alone would let
            # the generic "connection went away" check in _update_host() re-drop this same player as
            # "disconnected", overwriting the fact that this departure was deliberate. _drop_player()
            # is a no-op for a player who is already gone, so that later check then does nothing.
            connection.close()
            cls._drop_player(sender_id, reason="left")

    @classmethod
    def _drop_player(cls, player_id, reason):
        connection = cls._connections.pop(player_id, None)
        if connection is None:
            return
        connection.close()
        cls._names.pop(player_id, None)
        cls._last_seen.pop(player_id, None)
        cls._ping_sent_at.pop(player_id, None)
        cls._ping_ms.pop(player_id, None)
        # Whatever this player owned would otherwise sit frozen forever, with nobody left to drive it.
        for network_id in cls._object_ids_owned_by(player_id):
            cls._perform_despawn(network_id)
        cls._broadcast({"t": protocol.PLAYER_LEFT, "id": player_id, "reason": reason})
        DebugManager.log(f"Player {player_id} left ({reason}).", source="Networking")
        EventBus.emit("network_player_left", player_id=player_id, reason=reason)

    # -- pings (both roles) ------------------------------------------------------------

    @classmethod
    def _send_ping(cls, peer_id, connection, now):
        token = cls._next_ping_token
        cls._next_ping_token += 1
        sent = cls._ping_sent_at.setdefault(peer_id, {})
        sent[token] = now
        if len(sent) > 16:
            del sent[min(sent)]              # a pong that never came back must not pile up forever
        cls._queue(connection, {"t": protocol.PING, "token": token})

    @classmethod
    def _record_pong(cls, from_id, token):
        sent = cls._ping_sent_at.get(from_id)
        if not sent or not _is_id(token) or token not in sent:
            return
        cls._ping_ms[from_id] = (_time.monotonic() - sent.pop(token)) * 1000.0

    # -- client side: connecting phase --------------------------------------------

    @classmethod
    def _update_connecting(cls, now):
        sock = cls._pending_connect_socket
        try:
            _, writable, errored = select.select([], [sock], [sock], 0)
        except (OSError, ValueError):
            cls._fail_connect("socket_error")
            return

        if errored or sock in writable:
            code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if code != 0:
                cls._fail_connect(errno.errorcode.get(code, str(code)))
                return
            try:
                peer = sock.getpeername()
            except OSError:
                cls._fail_connect("socket_error")
                return
            connection = Connection(sock, peer)
            cls._pending_connect_socket = None
            cls._connections[HOST_PLAYER_ID] = connection
            connection.queue_send({"t": protocol.HELLO, "protocol": protocol.PROTOCOL_VERSION,
                                   "name": cls._join_name})
            connection.pump_send()
            cls._host_last_seen = now
            return

        if now > cls._handshake_deadline:
            cls._fail_connect("timeout")

    @classmethod
    def _fail_connect(cls, reason):
        DebugManager.log_error(f"NetworkManager: connection failed ({reason}).", source="Networking")
        was_client = cls.is_client
        cls._reset_state()
        if was_client:
            EventBus.emit("network_connection_failed", reason=reason)

    @classmethod
    def _connection_lost(cls, reason):
        """The link to the host is gone. Mid-handshake that's a failed
        connection; once established it's a disconnection."""
        if cls.is_connecting:
            cls._fail_connect(reason)
        else:
            cls._handle_host_gone(reason)

    # -- client side: handshaking or connected ------------------------------------------

    @classmethod
    def _update_client(cls, now):
        connection = cls._connections.get(HOST_PLAYER_ID)
        if connection is None or not connection.is_open:
            cls._connection_lost("disconnected")
            return

        messages = connection.pump_recv()
        if messages:
            cls._host_last_seen = now
        for message in messages:
            if not cls.is_client:
                break                        # an earlier message already ended the session
            cls._guarded(cls._handle_message_as_client, message)
        if not cls.is_client:
            return

        connection = cls._connections.get(HOST_PLAYER_ID)
        if connection is None or not connection.is_open:
            cls._connection_lost("disconnected")
            return
        if cls.is_connecting:
            if now > cls._handshake_deadline:
                cls._fail_connect("timeout")
                return
        elif now - cls._host_last_seen > cls.peer_timeout:
            cls._connection_lost("timeout")
            return
        if cls.is_connected and now - cls._last_ping_round >= cls.ping_interval:
            cls._last_ping_round = now
            cls._send_ping(HOST_PLAYER_ID, connection, now)
        connection.pump_send()

    @classmethod
    def _handle_message_as_client(cls, message):
        msg_type = message.get("t")
        if msg_type == protocol.WELCOME:
            if cls.is_connecting:
                cls._complete_handshake(message)
            return
        if msg_type == protocol.REJECT:
            # A rejection only means something during the handshake. Once we are connected a stray one must
            # not tear the session down (and, worse, do it without cleaning up the networked objects).
            if cls.is_connecting:
                reason = message.get("reason")
                cls._fail_connect(reason if isinstance(reason, str) else "rejected")
            return
        if msg_type == protocol.DISCONNECT:
            reason = message.get("reason")
            cls._connection_lost(reason if isinstance(reason, str) else "host_closed")
            return
        if not cls.is_connected:
            return                           # everything else only means something after the welcome

        if msg_type == protocol.PLAYER_JOINED:
            player_id, name = message.get("id"), message.get("name")
            if _is_id(player_id):
                name = name if isinstance(name, str) else ""
                cls._names[player_id] = name
                cls._resync_epoch += 1
                EventBus.emit("network_player_joined", player_id=player_id, name=name)
        elif msg_type == protocol.PLAYER_LEFT:
            player_id = message.get("id")
            if _is_id(player_id):
                cls._names.pop(player_id, None)
                reason = message.get("reason")
                EventBus.emit("network_player_left", player_id=player_id,
                              reason=reason if isinstance(reason, str) else "")
        elif msg_type == protocol.RPC:
            name = message.get("name")
            args = message.get("args", [])
            kwargs = message.get("kwargs", {})
            if isinstance(name, str) and isinstance(args, list) and isinstance(kwargs, dict):
                cls._invoke_rpc_handlers(name, args, kwargs, message.get("sender"))
        elif msg_type == protocol.SPAWN:
            network_id, prefab, owner = message.get("id"), message.get("prefab"), message.get("owner")
            x, y = message.get("x"), message.get("y")
            kwargs, state = message.get("kwargs", {}), message.get("state")
            if _is_id(network_id) and isinstance(prefab, str) and _is_id(owner) \
                    and _is_number(x) and _is_number(y) and isinstance(kwargs, dict) \
                    and (state is None or isinstance(state, dict)):
                cls._apply_spawn(network_id, prefab, owner, x, y, kwargs, state)
        elif msg_type == protocol.DESPAWN:
            network_id = message.get("id")
            if _is_id(network_id):
                cls._apply_despawn(network_id)
        elif msg_type == protocol.TRANSFORM:
            cls._apply_transform(message.get("id"), message.get("x"), message.get("y"), message.get("rot", 0.0))
        elif msg_type == protocol.STATE:
            cls._apply_state(message.get("id"), message.get("vars"))
        elif msg_type == protocol.PING:
            cls._queue(cls._connections[HOST_PLAYER_ID], {"t": protocol.PONG, "token": message.get("token")})
        elif msg_type == protocol.PONG:
            cls._record_pong(HOST_PLAYER_ID, message.get("token"))

    @classmethod
    def _complete_handshake(cls, message):
        your_id = message.get("your_id")
        if not _is_id(your_id):
            cls._fail_connect("bad_welcome")
            return
        cls.local_player_id = your_id
        session_name, max_players = message.get("session_name"), message.get("max_players")
        if isinstance(session_name, str):
            cls.session_name = session_name
        if _is_id(max_players):
            cls.max_players = max_players
        cls.is_connecting = False
        cls.is_connected = True
        cls._host_last_seen = _time.monotonic()
        cls._names[your_id] = cls.local_name

        roster = []
        entries = message.get("players", [])
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and _is_id(entry.get("id")):
                name = entry.get("name") if isinstance(entry.get("name"), str) else ""
                cls._names[entry["id"]] = name
                roster.append((entry["id"], name))
        DebugManager.log(f"Connected as player {your_id}.", source="Networking")
        EventBus.emit("network_connected", as_host=False, player_id=your_id)
        for player_id, name in roster:
            EventBus.emit("network_player_joined", player_id=player_id, name=name)

    @classmethod
    def _handle_host_gone(cls, reason):
        was_established = cls.is_connected
        cls._destroy_all_networked_objects()
        cls._reset_state()
        if was_established:
            DebugManager.log_warning(f"Disconnected from host ({reason}).", source="Networking")
            EventBus.emit("network_disconnected", reason=reason)

    # == info ================================================================

    @classmethod
    def players(cls):
        """A fresh list of PlayerInfo for everyone in the session, yourself
        and the host included. Empty if not connected."""
        if not (cls.is_host or cls.is_connected):
            return []
        return [PlayerInfo(pid, cls._names.get(pid, "?"), cls._ping_ms.get(pid)) for pid in sorted(cls._names)]

    @classmethod
    def get_ping(cls, player_id):
        """Last measured round-trip time between this machine and `player_id`,
        in milliseconds - or None if not known yet. (The host measures every
        client; a client measures the host.)"""
        return cls._ping_ms.get(player_id)

    @classmethod
    def local_ip(cls):
        """Best-effort local network address to show players so they can type
        it into join() - not guaranteed reachable from outside this machine's
        network, and falls back to "127.0.0.1" if it can't be worked out."""
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("198.51.100.1", 80))   # TEST-NET-2 (RFC 5737): nothing is ever actually sent
            return probe.getsockname()[0]
        except OSError:
            try:
                return socket.gethostbyname(socket.gethostname())
            except OSError:
                return "127.0.0.1"
        finally:
            probe.close()

    # == LAN discovery (browsing) ==============================================================

    @classmethod
    def start_discovery(cls, discovery_port=DEFAULT_DISCOVERY_PORT):
        """Start listening for hosts' LAN broadcasts. Independent of join():
        browse first and join what you find, or skip straight to join() with
        a known address - either works. Call stop_discovery() when done."""
        if cls._browser is not None:
            return
        cls._browser = LanBrowser(discovery_port)

    @classmethod
    def stop_discovery(cls):
        if cls._browser is not None:
            cls._browser.close()
            cls._browser = None

    @classmethod
    def discovered_servers(cls):
        """A fresh list of ServerInfo currently visible on the LAN (empty if
        start_discovery() hasn't been called, or nothing has answered yet)."""
        return cls._browser.servers if cls._browser is not None else []

    # == low-level sending ================================================================

    @classmethod
    def _queue(cls, connection, message):
        try:
            connection.queue_send(message)
        except protocol.ProtocolError as exc:
            DebugManager.log_error(f"NetworkManager: couldn't send a '{message.get('t')}' message: {exc}",
                                   source="Networking")

    @classmethod
    def _broadcast(cls, message, exclude=None):
        for player_id, connection in list(cls._connections.items()):
            if player_id != exclude:
                cls._queue(connection, message)

    @classmethod
    def _send_to_host(cls, message):
        connection = cls._connections.get(HOST_PLAYER_ID)
        if connection is not None and connection.is_open:
            cls._queue(connection, message)

    # == RPCs ================================================================

    @classmethod
    def register_rpc(cls, name, handler):
        """Register `handler(sender_id, *args, **kwargs)` to run whenever an
        RPC named `name` is received (see send_rpc). Several handlers for the
        same name are all called, in registration order."""
        cls._rpc_handlers.setdefault(name, []).append(handler)

    @classmethod
    def unregister_rpc(cls, name, handler=None):
        """Remove `handler` from `name` (or every handler for `name` if
        `handler` is omitted)."""
        if handler is None:
            cls._rpc_handlers.pop(name, None)
            return
        handlers = cls._rpc_handlers.get(name)
        if handlers and handler in handlers:
            handlers.remove(handler)

    @classmethod
    def send_rpc(cls, name, *args, target="all", **kwargs):
        """Call `name` on other peers. `target` is `"all"` (everyone,
        including yourself - the call always goes through the host even for
        your own copy, so on a LAN expect a few milliseconds before it takes
        effect anywhere, your own machine included), `"host"` (only the
        host), or a specific player id (only that player). Every registered
        handler for `name` receives `(sender_id, *args, **kwargs)`. Arguments
        must be plain JSON data (numbers, strings, booleans, None, lists,
        dicts with string keys) - anything else raises TypeError right here.
        Does nothing (logged) if not connected."""
        args = protocol.normalize_json(list(args), f"send_rpc({name!r}) arguments")
        kwargs = protocol.normalize_json(kwargs, f"send_rpc({name!r}) keyword arguments")
        if not (cls.is_host or cls.is_connected):
            DebugManager.log_warning(f"send_rpc({name!r}) called while not connected; ignored.",
                                     source="Networking")
            return
        if cls.is_host:
            cls._route_and_apply_rpc(name, args, kwargs, HOST_PLAYER_ID, target)
        else:
            cls._send_to_host({"t": protocol.RPC, "name": name, "args": args, "kwargs": kwargs,
                               "sender": cls.local_player_id, "target": target})

    @classmethod
    def _route_and_apply_rpc(cls, name, args, kwargs, sender_id, target):
        """Host-only: decide who receives this RPC over the wire and whether
        the host itself should run it, then do both. The one place this logic
        lives, whether the call started on the host or arrived from a client."""
        if target == "all":
            cls._broadcast({"t": protocol.RPC, "name": name, "args": args, "kwargs": kwargs,
                            "sender": sender_id, "target": "all"})
            cls._invoke_rpc_handlers(name, args, kwargs, sender_id)
        elif target == "host":
            cls._invoke_rpc_handlers(name, args, kwargs, sender_id)
        elif _is_id(target):
            if target == HOST_PLAYER_ID:
                cls._invoke_rpc_handlers(name, args, kwargs, sender_id)
            else:
                connection = cls._connections.get(target)
                if connection is not None:
                    cls._queue(connection, {"t": protocol.RPC, "name": name, "args": args, "kwargs": kwargs,
                                            "sender": sender_id, "target": target})
        else:
            DebugManager.log_warning(f"send_rpc: unrecognized target {target!r}; ignoring.", source="Networking")

    @classmethod
    def _invoke_rpc_handlers(cls, name, args, kwargs, sender_id):
        handlers = cls._rpc_handlers.get(name)
        if not handlers:
            return
        for handler in list(handlers):   # a copy: a handler may register/unregister others
            try:
                handler(sender_id, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - one bad RPC handler must not break networking
                DebugManager.log_error(f"RPC handler for '{name}' raised {exc!r}", source="Networking")

    # == networked objects ===========================================================

    @classmethod
    def register_prefab(cls, name, factory):
        """`factory(x, y, **kwargs) -> GameObject`, not yet added to any
        scene - NetworkManager adds it to the active scene itself, attaching
        NetworkIdentity (and a default NetworkTransform if the factory didn't
        add its own). Register every prefab on *every* peer (host and clients
        alike) before hosting/joining: a peer that doesn't recognize a prefab
        name logs an error and skips that object rather than crashing.
        The factory receives exactly the same arguments on every peer, so it
        should build the same thing everywhere."""
        cls._prefabs[name] = factory

    @classmethod
    def spawn(cls, prefab_name, x, y, owner_id=None, **kwargs):
        """Create a networked instance of `prefab_name` at `(x, y)`, visible
        to every connected peer. `kwargs` are passed to the prefab factory on
        every peer, so they must be plain JSON data (TypeError otherwise).
        `owner_id` defaults to whoever calls this; pass HOST_PLAYER_ID (0) or
        another player's id to give ownership to someone else (a client may
        only ask for itself or the host).

        On the host this returns the real GameObject immediately. On a client
        it always returns None - the request goes to the host, and the object
        appears (on every peer, this one included) once the host's reply
        comes back; subscribe to the "network_object_spawned" event if you
        need a reference to it."""
        if not (cls.is_host or cls.is_connected):
            DebugManager.log_warning("NetworkManager.spawn() called while not connected; ignored.",
                                     source="Networking")
            return None
        if not (_is_number(x) and _is_number(y)):
            raise ValueError(f"NetworkManager.spawn(): x and y must be finite numbers, got ({x!r}, {y!r})")
        kwargs = protocol.normalize_json(kwargs, f"spawn({prefab_name!r}) keyword arguments")
        if prefab_name not in cls._prefabs:
            DebugManager.log_error(f"NetworkManager.spawn(): no prefab registered as '{prefab_name}' - call "
                                   f"register_prefab() on every peer first.", source="Networking")
            return None
        if owner_id is None:
            owner_id = cls.local_player_id
        if cls.is_host:
            return cls._perform_spawn(prefab_name, x, y, owner_id, kwargs)
        cls._send_to_host({"t": protocol.SPAWN_REQUEST, "prefab": prefab_name, "x": x, "y": y,
                           "owner": owner_id, "kwargs": kwargs})
        return None

    @classmethod
    def _perform_spawn(cls, prefab_name, x, y, owner_id, kwargs):
        """Host-only: create the object here, then tell every client to."""
        network_id = cls._next_network_id
        cls._next_network_id += 1
        game_object = cls._apply_spawn(network_id, prefab_name, owner_id, x, y, kwargs, None)
        if game_object is not None:
            cls._broadcast({"t": protocol.SPAWN, "id": network_id, "prefab": prefab_name,
                            "owner": owner_id, "x": x, "y": y, "kwargs": kwargs})
        return game_object

    @classmethod
    def _apply_spawn(cls, network_id, prefab_name, owner_id, x, y, kwargs, state):
        """Shared by the host (spawning locally) and every client (receiving a
        SPAWN): build the object from its prefab factory, attach identity and
        transform, add it to the active scene, register it."""
        from engine.components.network_identity import NetworkIdentity
        from engine.components.network_state import NetworkState
        from engine.components.network_transform import NetworkTransform

        if network_id in cls._networked_objects:
            DebugManager.log_warning(f"NetworkManager: object id {network_id} already exists; duplicate "
                                     f"spawn ignored.", source="Networking")
            return None
        factory = cls._prefabs.get(prefab_name)
        if factory is None:
            DebugManager.log_error(f"NetworkManager: no prefab registered as '{prefab_name}' - call "
                                   f"register_prefab() for it on every peer before hosting/joining.",
                                   source="Networking")
            return None
        scene = SceneManager.active_scene
        if scene is None:
            DebugManager.log_error("NetworkManager: a spawn arrived but there is no active scene.",
                                   source="Networking")
            return None
        try:
            game_object = factory(x, y, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a broken factory must not take down networking
            DebugManager.log_error(f"NetworkManager: prefab '{prefab_name}' factory raised {exc!r}",
                                   source="Networking")
            return None
        if not isinstance(game_object, GameObject):
            DebugManager.log_error(f"NetworkManager: prefab '{prefab_name}' factory did not return a "
                                   f"GameObject; skipped.", source="Networking")
            return None

        game_object.add_component(NetworkIdentity(network_id, owner_id, prefab_name, kwargs))
        if game_object.get_component(NetworkTransform) is None:
            game_object.add_component(NetworkTransform())
        scene.add_game_object(game_object)
        cls._networked_objects[network_id] = game_object
        if state:
            network_state = game_object.get_component(NetworkState)
            if network_state is not None:
                network_state.apply_remote(state)
        EventBus.emit("network_object_spawned", game_object=game_object, network_id=network_id,
                      owner_id=owner_id)
        return game_object

    @classmethod
    def despawn(cls, target):
        """Destroy a networked object everywhere. `target` is the GameObject,
        its NetworkIdentity, or a bare network_id. On the host this happens
        at once and is then broadcast; on a client it sends a request to the
        host, and the object disappears (on every peer, this one included)
        when the host's reply arrives. Use this instead of `.destroy()` on
        networked objects (on the host `.destroy()` is noticed and broadcast
        for you, but a client has no way to tell anyone)."""
        from engine.components.network_identity import NetworkIdentity

        if _is_id(target):
            network_id = target
        elif isinstance(target, NetworkIdentity):
            network_id = target.network_id
        elif isinstance(target, GameObject):
            identity = target.get_component(NetworkIdentity)
            if identity is None:
                DebugManager.log_warning(f"NetworkManager.despawn(): '{target.name}' has no "
                                         f"NetworkIdentity; ignored.", source="Networking")
                return
            network_id = identity.network_id
        else:
            raise TypeError("NetworkManager.despawn() expects a GameObject, NetworkIdentity, or "
                            f"network_id int, got {type(target).__name__}")

        if not (cls.is_host or cls.is_connected):
            return
        if cls.is_host:
            cls._perform_despawn(network_id)
        else:
            cls._send_to_host({"t": protocol.DESPAWN_REQUEST, "id": network_id})

    @classmethod
    def _perform_despawn(cls, network_id):
        if network_id not in cls._networked_objects:
            return
        cls._apply_despawn(network_id)
        cls._broadcast({"t": protocol.DESPAWN, "id": network_id})

    @classmethod
    def _apply_despawn(cls, network_id):
        game_object = cls._networked_objects.pop(network_id, None)
        if game_object is None:
            return
        cls._applying_remote_despawn = True
        try:
            game_object.destroy()
        finally:
            cls._applying_remote_despawn = False
        EventBus.emit("network_object_despawned", network_id=network_id)

    @classmethod
    def _on_networked_object_destroyed(cls, identity):
        """Called by NetworkIdentity.on_destroy(), however the object died: a
        direct .destroy() call, a parent's destruction cascading to it, a
        whole scene being torn down, or this class's own _apply_despawn().
        The registry must never keep a stale entry whatever the cause; and
        when something outside the normal despawn path destroyed it, the
        peers have to be told - only the host can do that, and a client can
        only ask."""
        still_registered = cls._networked_objects.get(identity.network_id) is identity.game_object
        if still_registered:
            del cls._networked_objects[identity.network_id]
        if not still_registered or cls._applying_remote_despawn:
            return
        # _apply_despawn() emits this event itself for the normal path; reaching here means the object
        # went away some other way, and game code listening for despawns should hear about that too.
        EventBus.emit("network_object_despawned", network_id=identity.network_id)
        active_scene = SceneManager.active_scene
        scene_teardown = identity._scene_teardown or (active_scene is not None and active_scene.is_destroyed)
        if cls.is_host:
            cls._broadcast({"t": protocol.DESPAWN, "id": identity.network_id})
        elif cls.is_client:
            if scene_teardown:
                # A level change on this client. What it owned would otherwise live on
                # everywhere else with nobody driving it - ask the host to remove it.
                if identity.owner_id == cls.local_player_id:
                    cls._send_to_host({"t": protocol.DESPAWN_REQUEST, "id": identity.network_id})
            else:
                DebugManager.log_error(
                    f"A networked object (id={identity.network_id}) was destroyed directly on a client "
                    f"without NetworkManager.despawn() - it is now out of sync with other players. Use "
                    f"NetworkManager.despawn(...) instead of .destroy() on networked objects.",
                    source="Networking")

    @classmethod
    def get_networked_object(cls, network_id):
        """The GameObject for `network_id` on this peer, or None if it doesn't
        exist here (never spawned, already despawned, or not replicated yet)."""
        return cls._networked_objects.get(network_id) if _is_id(network_id) else None

    @classmethod
    def networked_objects(cls):
        """A fresh list of every networked GameObject on this peer."""
        return list(cls._networked_objects.values())

    @classmethod
    def objects_owned_by(cls, player_id=None):
        """A fresh list of the networked GameObjects owned by `player_id`
        (default: the local player) - e.g. "find my own avatar"."""
        if player_id is None:
            player_id = cls.local_player_id
        return [cls._networked_objects[nid] for nid in cls._object_ids_owned_by(player_id)]

    @classmethod
    def _object_ids_owned_by(cls, player_id):
        from engine.components.network_identity import NetworkIdentity
        result = []
        for network_id, game_object in cls._networked_objects.items():
            identity = game_object.get_component(NetworkIdentity)
            if identity is not None and identity.owner_id == player_id:
                result.append(network_id)
        return result

    @classmethod
    def _owner_of(cls, network_id):
        from engine.components.network_identity import NetworkIdentity
        game_object = cls._networked_objects.get(network_id)
        if game_object is None:
            return None
        identity = game_object.get_component(NetworkIdentity)
        return identity.owner_id if identity is not None else None

    # == position and state sync (called by the components; not public API) ==================

    @classmethod
    def _send_transform_update(cls, network_id, x, y, rotation):
        message = {"t": protocol.TRANSFORM, "id": network_id, "x": x, "y": y, "rot": rotation}
        if cls.is_host:
            cls._broadcast(message)
        elif cls.is_connected:
            cls._send_to_host(message)

    @classmethod
    def _apply_transform(cls, network_id, x, y, rotation):
        from engine.components.network_identity import NetworkIdentity
        from engine.components.network_transform import NetworkTransform
        if not (_is_id(network_id) and _is_number(x) and _is_number(y) and _is_number(rotation)):
            return
        game_object = cls._networked_objects.get(network_id)
        if game_object is None:
            return                           # normal: an update can arrive just after the despawn
        identity = game_object.get_component(NetworkIdentity)
        if identity is not None and identity.is_owner:
            return                           # a stale update must never move an object we drive ourselves
        component = game_object.get_component(NetworkTransform)
        if component is not None:
            component.receive_update(x, y, rotation)

    @classmethod
    def _send_state_update(cls, network_id, values):
        message = {"t": protocol.STATE, "id": network_id, "vars": values}
        if cls.is_host:
            cls._broadcast(message)
        elif cls.is_connected:
            cls._send_to_host(message)

    @classmethod
    def _apply_state(cls, network_id, values):
        from engine.components.network_identity import NetworkIdentity
        from engine.components.network_state import NetworkState
        if not (_is_id(network_id) and isinstance(values, dict)):
            return
        game_object = cls._networked_objects.get(network_id)
        if game_object is None:
            return
        identity = game_object.get_component(NetworkIdentity)
        if identity is not None and identity.is_owner:
            return
        component = game_object.get_component(NetworkState)
        if component is not None:
            component.apply_remote(values)
