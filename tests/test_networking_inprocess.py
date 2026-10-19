"""In-process tests of NetworkManager, in both roles, against peers this file
controls byte for byte:

  - HOST role: NetworkManager.host() runs in the test process, and "raw peers"
    - plain TCP sockets speaking the wire protocol by hand - connect to it.
    That makes it easy to check exact replies (reject reasons, who receives
    what), and to send what no well-behaved client ever would.

  - CLIENT role: NetworkManager.join() runs in the test process, against a
    "fake host" - a plain listening socket this file drives - which can
    refuse, stay silent, hang up mid-session, or send nonsense.

(A real game is host XOR client per process, so these tests never need both
roles at once; tests/test_networking.py covers the real multi-process case.)
Everything runs over real loopback TCP, but without subprocesses - fast and
deterministic. Timeouts are shrunk through NetworkManager's tunable class
attributes (ping_interval, peer_timeout, handshake_timeout).

Run with: python -m unittest tests.test_networking_inprocess -v
"""
import json
import os
import socket
import struct
import sys
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

pygame.init()
# Same size as tests/test_engine.py: pygame's display mode is process-global.
DISPLAY = pygame.display.set_mode((640, 480))

from engine.components.network_identity import NetworkIdentity  # noqa: E402
from engine.components.network_state import NetworkState  # noqa: E402
from engine.components.network_transform import NetworkTransform  # noqa: E402
from engine.components.rigidbody2d import Rigidbody2D  # noqa: E402
from engine.core.debug_manager import DebugManager  # noqa: E402
from engine.core.event_bus import EventBus  # noqa: E402
from engine.core.game_object import GameObject  # noqa: E402
from engine.core.scene import Scene  # noqa: E402
from engine.core.scene_manager import SceneManager  # noqa: E402
from engine.networking import protocol  # noqa: E402
from engine.networking.network_manager import NetworkManager  # noqa: E402

EVENT_NAMES = ("network_connected", "network_connection_failed", "network_disconnected",
               "network_player_joined", "network_player_left",
               "network_object_spawned", "network_object_despawned")


def frame(payload):
    """Length-prefix `payload` bytes the way the wire protocol does."""
    return struct.pack(">I", len(payload)) + payload


def free_udp_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


# ==========================================================================================
# Peers this file controls
# ==========================================================================================

class _Wire:
    """Shared plumbing: a non-blocking socket with a *persistent* receive
    buffer (several protocol messages often arrive in one recv())."""

    def __init__(self):
        self.sock = None
        self.buf = bytearray()
        self.inbox = []
        self.closed = False

    def send(self, message):
        self.send_raw(json.dumps(message).encode("utf-8"))

    def send_raw(self, payload):
        self.send_bytes(frame(payload))

    def send_bytes(self, data):
        try:
            self.sock.sendall(data)
        except OSError:
            self.closed = True

    def poll(self):
        if self.sock is None:
            return
        try:
            chunk = self.sock.recv(65536)
            if chunk:
                self.buf += chunk
            else:
                self.closed = True
        except BlockingIOError:
            pass
        except OSError:
            self.closed = True
        while len(self.buf) >= 4:
            (n,) = struct.unpack(">I", self.buf[:4])
            if len(self.buf) < 4 + n:
                break
            self.inbox.append(json.loads(bytes(self.buf[4:4 + n]).decode("utf-8")))
            del self.buf[:4 + n]

    def messages(self, msg_type=None):
        return [m for m in self.inbox if msg_type is None or m.get("t") == msg_type]

    def types(self):
        return [m.get("t") for m in self.inbox]

    def clear(self):
        self.inbox.clear()

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self.closed = True


class RawPeer(_Wire):
    """A protocol client connected to the NetworkManager host under test."""

    def __init__(self, port):
        super().__init__()
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.sock.setblocking(False)
        self.player_id = None


class FakeHost(_Wire):
    """A listening socket standing in for a host, for NetworkManager.join()
    to connect to. Accepts one connection."""

    def __init__(self):
        super().__init__()
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.server.setblocking(False)
        self.port = self.server.getsockname()[1]

    def poll(self):
        if self.sock is None and self.server is not None:
            try:
                self.sock, _ = self.server.accept()
                self.sock.setblocking(False)
            except (BlockingIOError, OSError):
                pass
        super().poll()

    def close(self):
        super().close()
        if self.server is not None:
            try:
                self.server.close()
            except OSError:
                pass
            self.server = None


# ==========================================================================================
# Base class: a clean global NetworkManager/Scene/EventBus for every test
# ==========================================================================================

class NetTestCase(unittest.TestCase):
    def setUp(self):
        NetworkManager.disconnect()
        NetworkManager.stop_discovery()
        NetworkManager._prefabs = {}
        NetworkManager._rpc_handlers = {}
        NetworkManager.ping_interval = 2.0
        NetworkManager.peer_timeout = 8.0
        NetworkManager.handshake_timeout = 5.0
        NetworkManager.accepting_players = True
        EventBus.clear()
        SceneManager.reset()
        self.debug = DebugManager(print_to_console=False)
        self.scene = Scene("net-test")
        SceneManager.change_scene(self.scene)

        self.events = []
        for name in EVENT_NAMES:
            EventBus.subscribe(name, (lambda n: lambda **kw: self.events.append((n, kw)))(name))
        self.peers = []          # everything to poll during pump() and close in tearDown()

    def tearDown(self):
        for peer in self.peers:
            peer.close()
        NetworkManager.disconnect()
        NetworkManager.stop_discovery()
        SceneManager.reset()
        EventBus.clear()
        NetworkManager.ping_interval = 2.0
        NetworkManager.peer_timeout = 8.0
        NetworkManager.handshake_timeout = 5.0
        NetworkManager.accepting_players = True

    # -- helpers ---------------------------------------------------------------------

    def add_peer(self, peer):
        self.peers.append(peer)
        return peer

    def pump(self, seconds=0.3, until=None):
        """Drive the game loop (and poll every peer) for up to `seconds` of
        real time, or until `until()` becomes true. Returns until()'s value."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            NetworkManager.update()
            active = SceneManager.active_scene
            if active is not None:
                active.tick(1 / 60)
            for peer in self.peers:
                peer.poll()
            if until is not None and until():
                return True
            time.sleep(0.004)
        return until() if until is not None else None

    def step(self, frames=1, dt=1 / 60):
        """Run exactly `frames` game frames with no sleeping, so *game time* is exact
        (pump() sleeps in real time and so runs a variable number of frames)."""
        for _ in range(frames):
            NetworkManager.update()
            active = SceneManager.active_scene
            if active is not None:
                active.tick(dt)

    def deliver(self, seconds=0.25):
        """Move bytes between the peers and NetworkManager for a while WITHOUT ticking the scene."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            NetworkManager.update()
            for peer in self.peers:
                peer.poll()
            time.sleep(0.004)

    def event_names(self):
        return [name for name, _ in self.events]

    def events_named(self, name):
        return [kw for n, kw in self.events if n == name]

    def logs(self, level):
        return [entry.message for entry in self.debug.logs if entry.level == level]

    def state_box_factory(self):
        def make(x, y, **kwargs):
            go = GameObject(x, y, name="StateBox")
            go.add_component(NetworkState({"hp": 10}))
            return go
        return make

    def box_factory(self, calls=None):
        def make_box(x, y, **kwargs):
            if calls is not None:
                calls.append((x, y, kwargs))
            return GameObject(x, y, name="Box")
        return make_box


# ==========================================================================================
# HOST role
# ==========================================================================================

class HostTestCase(NetTestCase):
    """Base for tests of the host role: starts a host, and joins raw peers to it."""

    def start_host(self, **kwargs):
        options = dict(port=0, name="T", max_players=4, player_name="Hosty", discoverable=False)
        options.update(kwargs)
        self.assertTrue(NetworkManager.host(**options))
        self.port = NetworkManager.port
        return self.port

    def join(self, name="Alice"):
        """A raw peer that completes the handshake."""
        peer = self.add_peer(RawPeer(self.port))
        peer.send({"t": "hello", "protocol": protocol.PROTOCOL_VERSION, "name": name})
        self.assertTrue(self.pump(3, until=lambda: peer.messages("welcome")), "no welcome arrived")
        peer.player_id = peer.messages("welcome")[0]["your_id"]
        return peer


class TestHostRole(HostTestCase):
    # -- the handshake -------------------------------------------------------------------

    def test_welcome_describes_the_session(self):
        self.start_host()
        alice = self.join("Alice")
        welcome = alice.messages("welcome")[0]
        self.assertEqual(welcome["your_id"], 1)
        self.assertEqual(welcome["players"], [{"id": 0, "name": "Hosty"}])
        self.assertEqual(welcome["max_players"], 4)
        self.assertEqual(welcome["session_name"], "T")
        self.assertIn(("network_player_joined", {"player_id": 1, "name": "Alice"}), self.events)
        self.assertEqual([(p.id, p.name) for p in NetworkManager.players()], [(0, "Hosty"), (1, "Alice")])

    def test_the_second_player_sees_the_first_and_the_first_is_told_about_the_second(self):
        self.start_host()
        alice = self.join("Alice")
        bob = self.join("Bob")
        self.assertEqual(bob.messages("welcome")[0]["players"],
                         [{"id": 0, "name": "Hosty"}, {"id": 1, "name": "Alice"}])
        self.assertTrue(self.pump(2, until=lambda: alice.messages("player_joined")))
        self.assertEqual(alice.messages("player_joined")[0], {"t": "player_joined", "id": 2, "name": "Bob"})

    def test_player_ids_are_never_reused(self):
        self.start_host()
        alice = self.join("Alice")
        alice.close()
        self.assertTrue(self.pump(3, until=lambda: self.events_named("network_player_left")))
        bob = self.join("Bob")
        self.assertEqual(bob.player_id, 2, "a departed player's id must not be handed out again")

    def test_a_full_session_rejects_with_server_full(self):
        self.start_host(max_players=2)            # the host counts: room for exactly one client
        self.join("Alice")
        bob = self.add_peer(RawPeer(self.port))
        bob.send({"t": "hello", "protocol": protocol.PROTOCOL_VERSION, "name": "Bob"})
        self.assertTrue(self.pump(3, until=lambda: bob.messages("reject")))
        self.assertEqual(bob.messages("reject")[0]["reason"], "server_full")
        self.assertTrue(self.pump(2, until=lambda: bob.closed), "the host must hang up after rejecting")
        self.assertEqual(len(NetworkManager.players()), 2)

    def test_a_protocol_version_mismatch_is_rejected(self):
        self.start_host()
        peer = self.add_peer(RawPeer(self.port))
        peer.send({"t": "hello", "protocol": 999, "name": "Old"})
        self.assertTrue(self.pump(3, until=lambda: peer.messages("reject")))
        self.assertEqual(peer.messages("reject")[0]["reason"], "protocol_mismatch")

    def test_a_closed_session_refuses_newcomers_until_it_is_reopened(self):
        self.start_host()
        NetworkManager.accepting_players = False
        peer = self.add_peer(RawPeer(self.port))
        peer.send({"t": "hello", "protocol": protocol.PROTOCOL_VERSION, "name": "Late"})
        self.assertTrue(self.pump(3, until=lambda: peer.messages("reject")))
        self.assertEqual(peer.messages("reject")[0]["reason"], "session_closed")
        NetworkManager.accepting_players = True
        self.join("Ok")                            # and works again once reopened

    def test_player_names_are_sanitized(self):
        self.start_host(max_players=10)
        long_name = self.join("x" * 200)
        self.assertEqual(len(NetworkManager._names[long_name.player_id]), 64)
        for bad in (None, 123, "", "   ", ["a"]):
            peer = self.add_peer(RawPeer(self.port))
            peer.send({"t": "hello", "protocol": protocol.PROTOCOL_VERSION, "name": bad})
            self.assertTrue(self.pump(3, until=lambda: peer.messages("welcome")))
            player_id = peer.messages("welcome")[0]["your_id"]
            self.assertEqual(NetworkManager._names[player_id], f"Player{player_id}", f"name={bad!r}")

    def test_messages_before_hello_are_ignored_and_the_handshake_still_times_out(self):
        NetworkManager.handshake_timeout = 0.3
        self.start_host()
        peer = self.add_peer(RawPeer(self.port))
        peer.send({"t": "rpc", "name": "x", "args": [], "kwargs": {}, "target": "all"})
        peer.send({"t": "spawn_request", "prefab": "box", "x": 1, "y": 1})
        self.assertTrue(self.pump(2, until=lambda: peer.closed), "a socket that never says hello must be dropped")
        self.assertEqual(len(NetworkManager.players()), 1)

    def test_a_flood_of_half_open_connections_is_capped(self):
        NetworkManager.handshake_timeout = 0.6
        self.start_host()
        sockets = []
        try:
            for _ in range(8):       # in batches, pumping between: the host can only accept while it is updated
                for _ in range(8):
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.setblocking(False)
                    sock.connect_ex(("127.0.0.1", self.port))
                    sockets.append(sock)
                self.pump(0.05)
            self.assertGreater(len(NetworkManager._pending), 0)
            self.assertLessEqual(len(NetworkManager._pending), 32)
            self.assertTrue(self.pump(3, until=lambda: not NetworkManager._pending),
                            "silent connections must all be dropped after the handshake timeout")
        finally:
            for sock in sockets:
                sock.close()

    def test_pipelined_messages_right_behind_hello_are_not_lost(self):
        NetworkManager.register_prefab("box", self.box_factory())
        self.start_host()
        peer = self.add_peer(RawPeer(self.port))
        # hello and a spawn request in ONE write: the request arrives before the host has promoted us
        data = b""
        for message in ({"t": "hello", "protocol": protocol.PROTOCOL_VERSION, "name": "Fast"},
                        {"t": "spawn_request", "prefab": "box", "x": 3, "y": 4, "owner": 1, "kwargs": {}}):
            data += frame(json.dumps(message).encode())
        peer.send_bytes(data)
        self.assertTrue(self.pump(3, until=lambda: peer.messages("spawn")))
        self.assertEqual(peer.messages("spawn")[0]["owner"], 1)

    # -- leaving -----------------------------------------------------------------------------

    def test_kick_removes_the_player_and_tells_them_why(self):
        self.start_host()
        alice = self.join("Alice")
        self.assertTrue(NetworkManager.kick(alice.player_id, "spamming"))
        self.assertTrue(self.pump(3, until=lambda: alice.messages("disconnect")))
        self.assertEqual(alice.messages("disconnect")[0]["reason"], "spamming")
        self.assertEqual(self.events_named("network_player_left")[-1],
                         {"player_id": alice.player_id, "reason": "spamming"})
        self.assertEqual([p.id for p in NetworkManager.players()], [0])
        self.assertFalse(NetworkManager.kick(alice.player_id), "kicking someone who's gone does nothing")
        self.assertFalse(NetworkManager.kick(99))

    def test_a_graceful_disconnect_and_an_abrupt_one_have_different_reasons(self):
        self.start_host()
        alice, bob = self.join("Alice"), self.join("Bob")
        alice.send({"t": "disconnect", "reason": "left"})
        bob.close()
        self.assertTrue(self.pump(3, until=lambda: len(self.events_named("network_player_left")) == 2))
        reasons = {kw["player_id"]: kw["reason"] for kw in self.events_named("network_player_left")}
        self.assertEqual(reasons, {alice.player_id: "left", bob.player_id: "disconnected"})

    def test_a_silent_peer_is_dropped_after_the_timeout(self):
        NetworkManager.peer_timeout = 0.3
        self.start_host()
        alice = self.join("Alice")
        self.assertTrue(self.pump(2, until=lambda: self.events_named("network_player_left")))
        self.assertEqual(self.events_named("network_player_left")[0]["reason"], "timeout")
        self.assertTrue(self.pump(1, until=lambda: alice.closed))

    def test_pings_measure_latency_and_bogus_pongs_are_ignored(self):
        NetworkManager.ping_interval = 0.05
        self.start_host()
        alice = self.join("Alice")
        self.assertIsNone(NetworkManager.get_ping(alice.player_id))
        self.assertTrue(self.pump(2, until=lambda: alice.messages("ping")))
        alice.send({"t": "pong", "token": 987654})                       # a token we never sent
        alice.send({"t": "pong", "token": "x"})
        alice.send({"t": "pong"})
        self.pump(0.1)
        self.assertIsNone(NetworkManager.get_ping(alice.player_id))
        alice.send({"t": "pong", "token": alice.messages("ping")[0]["token"]})
        self.assertTrue(self.pump(2, until=lambda: NetworkManager.get_ping(alice.player_id) is not None))
        self.assertGreaterEqual(NetworkManager.get_ping(alice.player_id), 0.0)

    def test_the_host_answers_pings_too(self):
        self.start_host()
        alice = self.join("Alice")
        alice.send({"t": "ping", "token": 41})
        self.assertTrue(self.pump(2, until=lambda: alice.messages("pong")))
        self.assertEqual(alice.messages("pong")[0]["token"], 41)

    # -- RPCs -------------------------------------------------------------------------------

    def test_rpc_routing(self):
        self.start_host()
        alice, bob = self.join("Alice"), self.join("Bob")
        received = []
        NetworkManager.register_rpc("chat", lambda sender, *args, **kwargs: received.append((sender, args, kwargs)))

        def send(peer, target, sender_claim=None, **extra):
            peer.send({"t": "rpc", "name": "chat", "args": ["hi"], "kwargs": extra,
                       "sender": sender_claim if sender_claim is not None else peer.player_id, "target": target})

        def chat_count(peer):
            return len(peer.messages("rpc"))

        # target "all": everybody - the sender included - and the host's own handler
        send(alice, "all", k=1)
        self.assertTrue(self.pump(2, until=lambda: chat_count(alice) and chat_count(bob)))
        self.assertEqual(received, [(alice.player_id, ("hi",), {"k": 1})])

        # a specific player: only them
        alice.clear(); bob.clear(); received.clear()
        send(alice, bob.player_id)
        self.assertTrue(self.pump(2, until=lambda: chat_count(bob)))
        self.pump(0.2)
        self.assertEqual((chat_count(alice), chat_count(bob), received), (0, 1, []))

        # "host", and the host's own id: only the host's handler
        bob.clear(); received.clear()
        send(alice, "host")
        send(alice, 0)
        self.pump(0.3)
        self.assertEqual(len(received), 2)
        self.assertEqual((chat_count(alice), chat_count(bob)), (0, 0))

        # a player who doesn't exist, and a nonsense target: nothing delivered, nothing raised
        received.clear()
        send(alice, 99)
        send(alice, "bogus")
        self.pump(0.3)
        self.assertEqual((received, chat_count(alice), chat_count(bob)), ([], 0, 0))
        self.assertTrue(any("unrecognized target" in m for m in self.logs("WARNING")))
        self.assertEqual(self.logs("ERROR"), [])

    def test_a_client_cannot_forge_the_sender_of_an_rpc(self):
        self.start_host()
        alice, bob = self.join("Alice"), self.join("Bob")
        received = []
        NetworkManager.register_rpc("chat", lambda sender, *a, **k: received.append(sender))
        alice.send({"t": "rpc", "name": "chat", "args": [], "kwargs": {}, "sender": bob.player_id, "target": "all"})
        self.assertTrue(self.pump(2, until=lambda: bob.messages("rpc")))
        self.assertEqual(received, [alice.player_id], "the host's handler must see the real sender")
        self.assertEqual(bob.messages("rpc")[0]["sender"], alice.player_id, "...and so must every other player")

    def test_the_hosts_own_rpcs(self):
        self.start_host()
        alice, bob = self.join("Alice"), self.join("Bob")
        received = []
        NetworkManager.register_rpc("ping_all", lambda sender, *a, **k: received.append((sender, a, k)))
        NetworkManager.send_rpc("ping_all", 1, 2, target="all", flag=True)
        self.assertTrue(self.pump(2, until=lambda: alice.messages("rpc") and bob.messages("rpc")))
        self.assertEqual(received, [(0, (1, 2), {"flag": True})])
        self.assertEqual(alice.messages("rpc")[0]["sender"], 0)
        alice.clear(); bob.clear()
        NetworkManager.send_rpc("ping_all", target=alice.player_id)
        self.assertTrue(self.pump(2, until=lambda: alice.messages("rpc")))
        self.pump(0.2)
        self.assertEqual(len(bob.messages("rpc")), 0)

    def test_rpc_arguments_must_be_plain_json_data(self):
        self.start_host()
        for bad in (object(), {1, 2}, float("nan"), float("inf"), lambda: 0, pygame.Surface((1, 1)), {1: "x"}):
            with self.assertRaises(TypeError, msg=repr(bad)):
                NetworkManager.send_rpc("x", bad)
        with self.assertRaises(TypeError):
            NetworkManager.send_rpc("x", fine=object())
        NetworkManager.send_rpc("x", (1, 2), {"a": [1, None, True, "s", 1.5]})   # all fine

    def test_a_failing_rpc_handler_does_not_stop_the_others_or_the_host(self):
        self.start_host()
        calls = []
        NetworkManager.register_rpc("boom", lambda sender, *a, **k: 1 / 0)
        NetworkManager.register_rpc("boom", lambda sender, *a, **k: calls.append("second"))
        NetworkManager.send_rpc("boom", target="all")
        self.assertEqual(calls, ["second"])
        self.assertTrue(any("ZeroDivisionError" in m for m in self.logs("ERROR")))
        handler = lambda sender, *a, **k: calls.append("third")      # noqa: E731
        NetworkManager.register_rpc("boom", handler)
        NetworkManager.unregister_rpc("boom", handler)
        calls.clear()
        NetworkManager.send_rpc("boom", target="all")
        self.assertEqual(calls, ["second"])
        NetworkManager.unregister_rpc("boom")
        calls.clear()
        NetworkManager.send_rpc("boom", target="all")
        self.assertEqual(calls, [])

    def test_send_rpc_while_not_connected_is_a_logged_no_op(self):
        NetworkManager.send_rpc("x", 1)
        self.assertTrue(any("not connected" in m for m in self.logs("WARNING")))



class TestHostObjects(HostTestCase):
    """Networked objects, replication, and hostile input - seen from the host."""

    def spawned_id(self, peer):
        return peer.messages("spawn")[-1]["id"]

    def test_a_spawn_request_creates_the_object_and_replicates_it_to_everyone(self):
        calls = []
        NetworkManager.register_prefab("box", self.box_factory(calls))
        self.start_host()
        alice, bob = self.join("Alice"), self.join("Bob")
        alice.clear(); bob.clear()
        alice.send({"t": "spawn_request", "prefab": "box", "x": 10, "y": 20, "owner": alice.player_id,
                    "kwargs": {"color": "red"}})
        self.assertTrue(self.pump(2, until=lambda: alice.messages("spawn") and bob.messages("spawn")))
        spawn = bob.messages("spawn")[0]
        self.assertEqual((spawn["prefab"], spawn["x"], spawn["y"], spawn["owner"], spawn["kwargs"]),
                         ("box", 10, 20, alice.player_id, {"color": "red"}))
        self.assertEqual(alice.messages("spawn")[0], spawn, "the requester receives the spawn like everybody else")
        go = NetworkManager.get_networked_object(spawn["id"])
        identity = go.get_component(NetworkIdentity)
        self.assertEqual((identity.owner_id, identity.is_owner), (alice.player_id, False))
        self.assertEqual(calls, [(10, 20, {"color": "red"})], "the factory receives the same kwargs on every peer")
        self.assertEqual(self.events_named("network_object_spawned")[0]["owner_id"], alice.player_id)
        self.assertEqual(NetworkManager.objects_owned_by(alice.player_id), [go])
        self.assertEqual(NetworkManager.objects_owned_by(), [])        # the host owns nothing here

    def test_bad_spawn_requests_are_refused_without_a_trace(self):
        NetworkManager.register_prefab("box", self.box_factory())
        NetworkManager.register_prefab("broken", lambda x, y, **k: 1 / 0)
        NetworkManager.register_prefab("not_an_object", lambda x, y, **k: "hello")
        self.start_host()
        alice = self.join("Alice")
        alice.clear()
        for request in ({"prefab": "box", "x": "1", "y": 1, "owner": 1, "kwargs": {}},          # not numbers
                        {"prefab": "box", "x": 1, "y": None, "owner": 1, "kwargs": {}},
                        {"prefab": "box", "x": True, "y": 1, "owner": 1, "kwargs": {}},         # a bool is no number
                        {"prefab": "box", "x": 1, "y": 1, "owner": "1", "kwargs": {}},          # owner not an id
                        {"prefab": "box", "x": 1, "y": 1, "owner": 1, "kwargs": [1]},           # kwargs not a dict
                        {"prefab": None, "x": 1, "y": 1, "owner": 1, "kwargs": {}},
                        {"prefab": "box", "x": 1, "y": 1, "owner": 7, "kwargs": {}}):           # impersonation
            alice.send({"t": "spawn_request", **request})
        alice.send_raw(b'{"t":"spawn_request","prefab":"box","x":1e999,"y":1,"owner":1,"kwargs":{}}')  # inf
        self.pump(0.5)
        self.assertEqual((alice.messages("spawn"), NetworkManager.networked_objects(), alice.closed), ([], [], False))
        self.assertEqual(self.logs("ERROR"), [], "plain bad input is dropped silently, not reported as errors")

        # Problems that point at the *game's* setup rather than at a bad message ARE worth an error line:
        # a prefab nobody registered, one whose factory crashes, one that returns something else.
        for prefab in ("nope", "broken", "not_an_object"):
            alice.send({"t": "spawn_request", "prefab": prefab, "x": 1, "y": 1, "owner": 1, "kwargs": {}})
        self.pump(0.4)
        self.assertEqual(NetworkManager.networked_objects(), [])
        errors = self.logs("ERROR")
        self.assertEqual(len(errors), 3)
        self.assertTrue(any("no prefab registered as 'nope'" in e for e in errors))
        self.assertTrue(any("ZeroDivisionError" in e for e in errors))
        self.assertTrue(any("did not return a GameObject" in e for e in errors))

    def test_position_and_state_relay_to_the_others_never_back_and_only_from_the_owner(self):
        NetworkManager.register_prefab("box", self.state_box_factory())
        self.start_host()
        alice, bob = self.join("Alice"), self.join("Bob")
        go = NetworkManager.spawn("box", 0, 0, owner_id=alice.player_id)
        self.assertTrue(self.pump(2, until=lambda: alice.messages("spawn") and bob.messages("spawn")))
        nid = self.spawned_id(alice)
        alice.clear(); bob.clear()

        alice.send({"t": "transform", "id": nid, "x": 5, "y": 6, "rot": 0})
        alice.send({"t": "state", "id": nid, "vars": {"hp": 3}})
        self.assertTrue(self.pump(2, until=lambda: bob.messages("transform") and bob.messages("state")))
        self.assertEqual(bob.messages("transform")[0], {"t": "transform", "id": nid, "x": 5, "y": 6, "rot": 0})
        self.assertEqual(bob.messages("state")[0], {"t": "state", "id": nid, "vars": {"hp": 3}})
        self.assertEqual((alice.messages("transform"), alice.messages("state")), ([], []), "never echoed to the sender")
        self.assertEqual(go.get_component(NetworkTransform)._target_x, 5)       # the host's own copy follows too
        self.assertEqual(go.get_component(NetworkState).get("hp"), 3)

        bob.send({"t": "transform", "id": nid, "x": -1, "y": -1, "rot": 0})    # not Bob's object
        bob.send({"t": "state", "id": nid, "vars": {"hp": 999}})
        self.pump(0.4)
        self.assertEqual((alice.messages("transform"), alice.messages("state")), ([], []))
        self.assertEqual(go.get_component(NetworkTransform)._target_x, 5)
        self.assertEqual(go.get_component(NetworkState).get("hp"), 3)

    def test_a_late_joiner_is_caught_up_before_anything_else(self):
        NetworkManager.register_prefab("box", self.state_box_factory())
        self.start_host()
        NetworkManager.spawn("box", 1, 2, owner_id=0)
        second = NetworkManager.spawn("box", 3, 4, owner_id=0, tag="b")
        second.get_component(NetworkState).set("hp", 77)
        alice = self.join("Alice")
        self.assertEqual(alice.types()[:3], ["welcome", "spawn", "spawn"])
        first_spawn, second_spawn = alice.messages("spawn")
        self.assertEqual(((first_spawn["x"], first_spawn["y"]), first_spawn["state"]), ((1, 2), {"hp": 10}))
        self.assertEqual(((second_spawn["x"], second_spawn["y"]), second_spawn["state"], second_spawn["kwargs"]),
                         ((3, 4), {"hp": 77}, {"tag": "b"}), "the *current* state and the original spawn kwargs")
        self.assertTrue(self.pump(2, until=lambda: alice.messages("transform")),
                        "owners re-send their position when somebody joins")

    def test_despawn_by_the_owner_by_the_host_and_for_ids_that_do_not_exist(self):
        NetworkManager.register_prefab("box", self.box_factory())
        self.start_host()
        alice, bob = self.join("Alice"), self.join("Bob")
        mine = NetworkManager.spawn("box", 0, 0, owner_id=alice.player_id)
        theirs = NetworkManager.spawn("box", 0, 0, owner_id=0)
        self.pump(0.3)
        alice.clear(); bob.clear()

        alice.send({"t": "despawn_request", "id": mine.get_component(NetworkIdentity).network_id})
        self.assertTrue(self.pump(2, until=lambda: alice.messages("despawn") and bob.messages("despawn")))
        self.assertIsNone(NetworkManager.get_networked_object(mine.get_component(NetworkIdentity).network_id))
        self.assertEqual(len(self.events_named("network_object_despawned")), 1)

        alice.clear(); bob.clear()
        NetworkManager.despawn(theirs)
        NetworkManager.despawn(theirs)              # a second time: already gone, nothing more to say
        NetworkManager.despawn(123456)              # never existed
        self.pump(0.3)
        self.assertEqual((len(alice.messages("despawn")), len(bob.messages("despawn"))), (1, 1))
        self.assertEqual(NetworkManager.networked_objects(), [])

        with self.assertRaises(TypeError):
            NetworkManager.despawn("not a thing")
        NetworkManager.despawn(GameObject(name="plain"))
        self.assertTrue(any("no NetworkIdentity" in m for m in self.logs("WARNING")))

    def test_when_an_owner_leaves_what_they_owned_is_removed_for_everyone(self):
        NetworkManager.register_prefab("box", self.box_factory())
        self.start_host()
        alice, bob = self.join("Alice"), self.join("Bob")
        NetworkManager.spawn("box", 0, 0, owner_id=alice.player_id)
        NetworkManager.spawn("box", 0, 0, owner_id=alice.player_id)
        NetworkManager.spawn("box", 0, 0, owner_id=bob.player_id)
        NetworkManager.spawn("box", 0, 0, owner_id=0)
        self.pump(0.3)
        bob.clear()

        alice.close()
        self.assertTrue(self.pump(3, until=lambda: bob.messages("player_left")))
        self.assertEqual([t for t in bob.types() if t != "ping"], ["despawn", "despawn", "player_left"],
                         "the objects go first, then the news that their owner left")
        self.assertEqual(sorted(go.get_component(NetworkIdentity).owner_id for go in NetworkManager.networked_objects()),
                         [0, bob.player_id])
        self.assertEqual(len(self.events_named("network_object_despawned")), 2)

    def test_destroying_a_networked_object_directly_on_the_host_is_still_told_to_everyone(self):
        NetworkManager.register_prefab("box", self.box_factory())
        self.start_host()
        bob = self.join("Bob")
        go = NetworkManager.spawn("box", 0, 0, owner_id=0)
        self.pump(0.3)
        bob.clear()
        go.destroy()                                 # not NetworkManager.despawn(): the safety net must cover it
        self.assertTrue(self.pump(2, until=lambda: bob.messages("despawn")))
        self.assertEqual(NetworkManager.networked_objects(), [])
        self.assertEqual(len(self.events_named("network_object_despawned")), 1)
        self.assertEqual(self.logs("ERROR"), [])

    def test_changing_scene_on_the_host_despawns_every_networked_object_everywhere(self):
        NetworkManager.register_prefab("box", self.box_factory())
        self.start_host()
        bob = self.join("Bob")
        for _ in range(3):
            NetworkManager.spawn("box", 0, 0, owner_id=0)
        self.pump(0.3)
        bob.clear()
        SceneManager.change_scene(Scene("next-level"))
        self.assertTrue(self.pump(2, until=lambda: len(bob.messages("despawn")) == 3))
        self.assertEqual(NetworkManager.networked_objects(), [])
        self.assertEqual(self.logs("ERROR"), [])
        self.assertTrue(NetworkManager.is_host and NetworkManager.is_connected, "the session itself carries on")

    def test_garbage_from_a_client_is_ignored_without_noise(self):
        NetworkManager.register_prefab("box", self.state_box_factory())
        self.start_host()
        alice = self.join("Alice")
        NetworkManager.spawn("box", 0, 0, owner_id=alice.player_id)
        self.pump(0.2)
        garbage = [
            {"t": 5}, {"t": None}, {"t": ["rpc"]}, {"t": {"a": 1}},
            {"t": "rpc"}, {"t": "rpc", "name": "x", "args": 5, "kwargs": {}},
            {"t": "rpc", "name": "x", "args": [], "kwargs": "k"}, {"t": "rpc", "name": ["x"], "args": [], "kwargs": {}},
            {"t": "transform"}, {"t": "transform", "id": 1.5, "x": 1, "y": 1},
            {"t": "transform", "id": -1, "x": 1, "y": 1}, {"t": "transform", "id": 10 ** 30, "x": 1, "y": 1},
            {"t": "transform", "id": True, "x": 1, "y": 1}, {"t": "transform", "id": 1, "x": "1", "y": 2, "rot": "r"},
            {"t": "state"}, {"t": "state", "id": 1, "vars": []}, {"t": "state", "id": "a", "vars": {}},
            {"t": "despawn_request"}, {"t": "despawn_request", "id": None}, {"t": "despawn_request", "id": {"a": 1}},
            {"t": "spawn_request"}, {"t": "spawn_request", "prefab": {"a": 1}},
            {"t": "ping"}, {"t": "ping", "token": {"a": 1}}, {"t": "pong"}, {"t": "pong", "token": [1]},
            {"t": "hello"}, {"t": "welcome"}, {"t": "player_joined"}, {"t": "spawn"}, {"t": "despawn"},
            {"t": "no_such_message"},
        ]
        for message in garbage:
            alice.send(message)
        self.pump(0.6)
        self.assertEqual(self.logs("ERROR"), [], "malformed input must be dropped, not turned into error reports")
        self.assertFalse(alice.closed)
        self.assertEqual(len(NetworkManager.players()), 2)

    def test_protocol_violations_drop_only_the_offender(self):
        self.start_host(max_players=10)
        innocent = self.join("Innocent")
        violations = {
            "length prefix over the limit": struct.pack(">I", protocol.MAX_MESSAGE_SIZE + 1) + b"x",
            "not JSON": frame(b"{not json"),
            "invalid UTF-8": frame(b"\xff\xfe\xfd"),
            "a NaN literal": frame(b'{"t":"transform","id":1,"x":NaN,"y":0,"rot":0}'),
            "an Infinity literal": frame(b'{"t":"transform","id":1,"x":Infinity,"y":0,"rot":0}'),
            "a top-level list": frame(b"[1,2,3]"),
            "no type field": frame(b'{"x":1}'),
        }
        for name, data in violations.items():
            offender = self.join(f"Bad-{name[:10]}")
            offender.send_bytes(data)
            self.assertTrue(self.pump(3, until=lambda: offender.closed), f"{name}: the offender must be dropped")
            self.assertFalse(innocent.closed, f"{name}: an innocent player must not be affected")
        self.assertEqual(len(self.events_named("network_player_left")), len(violations))
        self.assertTrue(all(kw["reason"] == "disconnected" for kw in self.events_named("network_player_left")))
        self.assertEqual([p.id for p in NetworkManager.players()], [0, innocent.player_id])

    def test_even_a_bug_deep_inside_a_handler_cannot_take_the_host_down(self):
        """Validation catches bad *input*; this is the last line of defence for a bug in the engine or in
        a game's own prefab/RPC code - it is logged, and the host carries on serving everybody."""
        NetworkManager.register_prefab("box", self.box_factory())
        self.start_host()
        alice = self.join("Alice")
        original = NetworkManager.__dict__["_perform_spawn"]
        NetworkManager._perform_spawn = classmethod(lambda cls, *args, **kwargs: 1 / 0)
        try:
            alice.send({"t": "spawn_request", "prefab": "box", "x": 1, "y": 1, "owner": 1, "kwargs": {}})
            alice.send({"t": "ping", "token": 9})
            self.assertTrue(self.pump(2, until=lambda: alice.messages("pong")), "the host stopped serving after the bug")
        finally:
            NetworkManager._perform_spawn = original
        self.assertTrue(any("error handling a 'spawn_request' message" in e and "ZeroDivisionError" in e
                            for e in self.logs("ERROR")))
        self.assertFalse(alice.closed)
        self.assertEqual(len(NetworkManager.players()), 2)

    def test_the_host_can_shut_down_and_start_over_with_a_clean_slate(self):
        NetworkManager.register_prefab("box", self.box_factory())
        self.start_host()
        first_port = self.port
        alice = self.join("Alice")
        NetworkManager.spawn("box", 0, 0, owner_id=0)
        self.pump(0.2)
        alice.clear()

        NetworkManager.disconnect()
        self.assertTrue(self.pump(2, until=lambda: alice.closed))
        self.assertEqual(alice.messages("disconnect")[0]["reason"], "host_closed")
        self.assertEqual(self.events_named("network_disconnected")[-1], {"reason": "left"})
        self.assertEqual((NetworkManager.is_host, NetworkManager.is_connected, NetworkManager.local_player_id,
                          NetworkManager.players(), NetworkManager.networked_objects()), (False, False, None, [], []))
        self.assertEqual(self.logs("ERROR"), [])
        # The port was released, and closed connections lingering in TIME_WAIT don't block restarting the host
        # on the very same port right away (a plain bind() without SO_REUSEADDR would hit them; host() doesn't).
        self.start_host(port=first_port)
        self.assertEqual(self.port, first_port)                          # ...and a fresh session has fresh numbering
        bob = self.join("Bob")
        self.assertEqual(bob.player_id, 1)
        self.assertEqual(NetworkManager.spawn("box", 0, 0, owner_id=0).get_component(NetworkIdentity).network_id, 1)
        NetworkManager.disconnect()                                      # calling it again, or when idle, is harmless
        NetworkManager.disconnect()

    def test_hosting_can_fail_and_does_so_cleanly(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("0.0.0.0", 0))
        blocker.listen(1)
        try:
            busy_port = blocker.getsockname()[1]
            self.assertFalse(NetworkManager.host(port=busy_port, discoverable=False))
            self.assertTrue(any(str(busy_port) in m for m in self.logs("ERROR")))
            for bad_port in (-1, 70000, "abc", None):
                self.assertFalse(NetworkManager.host(port=bad_port, discoverable=False), f"port={bad_port!r}")
            self.assertFalse(NetworkManager.host(port=0, max_players="many", discoverable=False))
            self.assertEqual((NetworkManager.is_host, NetworkManager.is_connected, NetworkManager.port),
                             (False, False, None))
        finally:
            blocker.close()
        self.start_host()                                   # ...and nothing is left half-set-up afterwards

    def test_hosting_or_joining_twice_is_refused(self):
        self.start_host()
        self.assertFalse(NetworkManager.host(port=0, discoverable=False))
        NetworkManager.join("127.0.0.1", port=self.port)
        self.assertEqual(len([w for w in self.logs("WARNING") if "already hosting" in w]), 2)
        self.assertTrue(NetworkManager.is_host and not NetworkManager.is_client)

    def test_discovery_advertises_the_live_player_count_and_stops_when_closed(self):
        import engine.networking.discovery as discovery
        saved = discovery.ADVERTISE_INTERVAL, discovery.SERVER_TIMEOUT
        discovery.ADVERTISE_INTERVAL, discovery.SERVER_TIMEOUT = 0.1, 0.6
        try:
            dport = free_udp_port()
            NetworkManager.start_discovery(dport)
            self.start_host(discoverable=True, discovery_port=dport, name="Adv")
            self.assertTrue(self.pump(4, until=lambda: NetworkManager.discovered_servers()),
                            "the browser never heard the host")
            info = NetworkManager.discovered_servers()[0]
            self.assertEqual((info.name, info.port, info.max_players, info.players),
                             ("Adv", NetworkManager.port, 4, 1))
            self.join("Alice")
            self.assertTrue(self.pump(4, until=lambda: NetworkManager.discovered_servers()[0].players == 2))
            NetworkManager.accepting_players = False        # a closed session stops advertising itself
            self.assertTrue(self.pump(4, until=lambda: not NetworkManager.discovered_servers()))
            NetworkManager.stop_discovery()
            self.assertEqual(NetworkManager.discovered_servers(), [])
        finally:
            discovery.ADVERTISE_INTERVAL, discovery.SERVER_TIMEOUT = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
