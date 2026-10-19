"""Stress and edge-case tests for NetworkManager (added in the review pass).

They reuse the raw-peer helpers from test_networking_inprocess.py and run over
real loopback TCP. Run with:  python -m unittest tests.test_networking_stress -v
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_networking_inprocess import HostTestCase, RawPeer  # noqa: E402
from engine.components.network_transform import NetworkTransform  # noqa: E402
from engine.core.game_object import GameObject  # noqa: E402
from engine.networking import protocol  # noqa: E402
from engine.networking.connection import Connection  # noqa: E402
from engine.networking.network_manager import NetworkManager  # noqa: E402


class TestHostUnderStress(HostTestCase):
    def setUp(self):
        super().setUp()
        NetworkManager.register_prefab("box", self.box_factory())

    def spawn_owned_by(self, peer):
        peer.send({"t": "spawn_request", "prefab": "box", "x": 0, "y": 0})
        self.assertTrue(self.pump(3, until=lambda: peer.messages("spawn")))
        return peer.messages("spawn")[0]["id"]

    # -- throughput ---------------------------------------------------------------

    def test_a_large_burst_from_one_client_is_drained_promptly(self):
        """~1 MB of position updates must be processed in a handful of frames, not
        spread over dozens (one recv() per frame caps throughput at 64 KB/frame)."""
        self.start_host()
        peer = self.join()
        network_id = self.spawn_owned_by(peer)
        count = 15000
        blob = b"".join(protocol.encode({"t": "transform", "id": network_id, "x": float(i), "y": 0.0, "rot": 0.0})
                        for i in range(count))
        peer.send_bytes(blob)
        frames = 0
        obj = NetworkManager.get_networked_object(network_id)
        target = obj.get_component(NetworkTransform)
        while frames < 200 and target._target_x != count - 1:
            NetworkManager.update()
            frames += 1
        self.assertEqual(target._target_x, count - 1, "the last update was never applied")
        self.assertLessEqual(frames, 12, f"draining {len(blob)} bytes took {frames} frames")

    def test_messages_split_into_single_bytes_still_assemble(self):
        self.start_host()
        peer = self.add_peer(RawPeer(self.port))
        wire = protocol.encode({"t": "hello", "protocol": protocol.PROTOCOL_VERSION, "name": "Slow"})
        for byte in wire:
            peer.send_bytes(bytes([byte]))
            NetworkManager.update()
        self.assertTrue(self.pump(2, until=lambda: peer.messages("welcome")))

    # -- liveness -----------------------------------------------------------------

    def test_a_host_that_stalls_longer_than_the_timeout_does_not_drop_healthy_peers(self):
        NetworkManager.peer_timeout = 0.4
        self.start_host()
        peer = self.join()
        peer.send({"t": "ping", "token": 1})
        time.sleep(0.9)                      # the host's frame loop is frozen (loading screen, window drag...)
        peer.send({"t": "ping", "token": 2})
        self.deliver(0.1)
        self.assertEqual([p.id for p in NetworkManager.players()], [0, peer.player_id])

    # -- backpressure ---------------------------------------------------------------

    def test_a_peer_that_never_reads_is_dropped_without_freezing_the_host_or_hurting_others(self):
        self.start_host(max_players=4)
        stuck = self.join("Stuck")
        healthy = self.join("Healthy")
        self.peers.remove(stuck)             # nobody polls (reads from) this one any more
        started = time.monotonic()
        for _ in range(40):
            NetworkManager.send_rpc("big", "x" * 600_000, target=stuck.player_id)   # only the stuck peer is flooded
            NetworkManager.send_rpc("small", 1, target=healthy.player_id)
            NetworkManager.update()
            healthy.poll()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.0, f"host frames stalled for {elapsed:.2f}s")
        self.pump(0.3)
        ids = [p.id for p in NetworkManager.players()]
        self.assertNotIn(stuck.player_id, ids)
        self.assertIn(healthy.player_id, ids)
        stuck.close()

    def test_kicking_or_closing_with_an_unreadable_peer_does_not_block_for_seconds(self):
        self.start_host(max_players=6)
        stuck = [self.join(f"S{i}") for i in range(3)]
        for peer in stuck:
            self.peers.remove(peer)
        for _ in range(3):
            NetworkManager.send_rpc("big", "x" * 1_000_000)   # fill the OS buffers
            NetworkManager.update()
        started = time.monotonic()
        NetworkManager.disconnect()
        elapsed = time.monotonic() - started
        for peer in stuck:
            peer.close()
        self.assertLess(elapsed, 1.5, f"disconnect() blocked the frame for {elapsed:.2f}s")

    # -- object churn --------------------------------------------------------------

    def test_spawn_despawn_churn_leaves_every_registry_consistent(self):
        self.start_host(max_players=4)
        a, b = self.join("A"), self.join("B")
        for i in range(60):
            a.send({"t": "spawn_request", "prefab": "box", "x": i, "y": 0})
            b.send({"t": "spawn_request", "prefab": "box", "x": i, "y": 1})
        self.pump(1.0, until=lambda: len(a.messages("spawn")) >= 120 and len(b.messages("spawn")) >= 120)
        ids = [m["id"] for m in a.messages("spawn")]
        self.assertEqual(len(ids), len(set(ids)), "duplicate network ids handed out")
        for network_id in ids[::2]:
            NetworkManager.despawn(network_id)
        self.pump(0.5)
        self.assertEqual(len(NetworkManager.networked_objects()), 60)
        self.assertEqual(len(a.messages("despawn")), 60)
        self.assertEqual(len(b.messages("despawn")), 60)
        a.close()
        self.pump(0.5)
        self.assertEqual(len(NetworkManager.objects_owned_by(a.player_id)), 0)

    def test_a_handler_that_tears_the_session_down_mid_update_is_handled_cleanly(self):
        self.start_host()
        from engine.core.event_bus import EventBus
        EventBus.subscribe("network_player_joined", lambda **kw: NetworkManager.disconnect())
        peer = self.add_peer(RawPeer(self.port))
        peer.send({"t": "hello", "protocol": protocol.PROTOCOL_VERSION, "name": "Doomed"})
        self.pump(0.4)
        self.assertFalse(NetworkManager.is_host)
        self.assertEqual(self.logs("error"), [])

    def test_kicking_from_inside_an_rpc_handler_is_handled_cleanly(self):
        self.start_host()
        peer = self.join()
        NetworkManager.register_rpc("bye", lambda sender, *a, **k: NetworkManager.kick(sender))
        peer.send({"t": "rpc", "name": "bye", "args": [], "kwargs": {}, "target": "host"})
        self.pump(0.4)
        self.assertEqual([p.id for p in NetworkManager.players()], [0])
        self.assertEqual(self.logs("error"), [])

    def test_a_teleport_is_not_smeared_across_the_screen_on_remote_copies(self):
        self.start_host()
        peer = self.join()
        network_id = self.spawn_owned_by(peer)
        obj = NetworkManager.get_networked_object(network_id)
        peer.send({"t": "transform", "id": network_id, "x": 5000.0, "y": 0.0, "rot": 0.0})
        self.deliver(0.05)
        self.step(1)
        x = obj.transform.get_world_xy()[0]
        self.assertGreater(x, 4000, f"remote copy only reached x={x:.0f} one frame after a 5000px jump")


if __name__ == "__main__":
    unittest.main()
