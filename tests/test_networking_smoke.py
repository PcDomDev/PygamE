"""Cross-process smoke test of the networking module: a real host process and a real client process, talking
over real loopback TCP through NetworkManager's public API (host / join / spawn / physics hand-over / despawn on
leaving). The detailed, fast tests live in test_networking_inprocess.py; this one proves the two real halves
work together.

Run with: python -m unittest tests.test_networking_smoke -v
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _role_main(role, port):
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    sys.path.insert(0, ROOT)
    import pygame
    pygame.init()
    pygame.display.set_mode((64, 64))
    from engine.components.rigidbody2d import Rigidbody2D
    from engine.core.event_bus import EventBus
    from engine.core.game_object import GameObject
    from engine.core.scene import Scene
    from engine.core.scene_manager import SceneManager
    from engine.networking.network_manager import NetworkManager

    def make_ball(x, y, **kwargs):
        go = GameObject(x, y, name="Ball")
        go.add_component(Rigidbody2D(gravity=500))
        return go

    scene = Scene("smoke")
    SceneManager.change_scene(scene)
    NetworkManager.register_prefab("ball", make_ball)

    def pump(seconds):
        for _ in range(max(1, int(seconds * 60))):
            NetworkManager.update()
            scene.tick(1 / 60)
            time.sleep(1 / 60)

    def wait_until(condition, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not condition():
            pump(0.05)
        return bool(condition())

    if role == "host":
        left = []
        EventBus.subscribe("network_player_left", lambda **kw: left.append(kw))
        assert NetworkManager.host(port=port, max_players=2, discoverable=False)
        print("READY", flush=True)
        assert wait_until(lambda: len(NetworkManager.players()) == 2), "the client never joined"
        host_ball = NetworkManager.spawn("ball", 0, 100, owner_id=0)
        client_ball_seen = wait_until(lambda: NetworkManager.objects_owned_by(1))
        pump(1.0)
        fell = host_ball.transform.world_y > 150
        wait_until(lambda: left)
        pump(0.3)
        result = {"host_ball_fell": fell, "client_ball_seen": client_ball_seen,
                  "left_reason": left[0]["reason"] if left else None,
                  "orphans_after_leave": len(NetworkManager.objects_owned_by(1))}
    else:
        NetworkManager.join("127.0.0.1", port=port, name="Bob", timeout=5.0)
        assert wait_until(lambda: NetworkManager.is_connected), "could not connect"
        assert wait_until(lambda: NetworkManager.objects_owned_by(0)), "the host's ball never arrived"
        copy = NetworkManager.objects_owned_by(0)[0]
        body = copy.get_component(Rigidbody2D)
        y0 = copy.transform.world_y
        pump(1.0)
        y1 = copy.transform.world_y
        NetworkManager.spawn("ball", 50, 50)                 # a request; the ball appears when the host answers
        assert wait_until(lambda: NetworkManager.objects_owned_by()), "our own ball never appeared"
        mine = NetworkManager.objects_owned_by()[0]
        result = {"connected_as": NetworkManager.local_player_id,
                  "copy_has_no_physics": body is not None and not body.enabled,
                  "copy_followed_the_host": y1 > y0 + 20,
                  "own_ball_has_physics": mine.get_component(Rigidbody2D).enabled}
        pump(0.3)
        NetworkManager.disconnect()
    print("RESULT_JSON " + json.dumps(result), flush=True)


def _free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _result(output):
    for line in output.splitlines():
        if line.startswith("RESULT_JSON "):
            return json.loads(line[len("RESULT_JSON "):])
    return None


class TestRealHostAndClient(unittest.TestCase):
    def test_a_host_process_and_a_client_process_play_together(self):
        port = _free_port()

        def start(role):
            return subprocess.Popen([sys.executable, os.path.abspath(__file__), role, str(port)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        host = start("host")
        deadline = time.monotonic() + 20
        ready = False
        while time.monotonic() < deadline and not ready:
            line = host.stdout.readline()
            ready = "READY" in line
            if line == "" and host.poll() is not None:
                break
        if not ready:
            host.kill()
            out, err = host.communicate()
            self.fail(f"the host never became ready:\n{err}")
        client = start("client")
        try:
            host_out, host_err = host.communicate(timeout=60)
            client_out, client_err = client.communicate(timeout=60)
        finally:
            for proc in (host, client):
                if proc.poll() is None:
                    proc.kill()
        self.assertEqual(host.returncode, 0, host_err)
        self.assertEqual(client.returncode, 0, client_err)
        host_result, client_result = _result(host_out), _result(client_out)
        self.assertEqual(client_result, {"connected_as": 1, "copy_has_no_physics": True,
                                         "copy_followed_the_host": True, "own_ball_has_physics": True})
        self.assertEqual(host_result, {"host_ball_fell": True, "client_ball_seen": True,
                                       "left_reason": "left", "orphans_after_leave": 0})


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] in ("host", "client"):
        _role_main(sys.argv[1], int(sys.argv[2]))
    else:
        unittest.main(verbosity=2)
