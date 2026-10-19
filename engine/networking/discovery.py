"""LAN discovery: find a hosted game on the local network without anyone
typing an IP address. Two small, independent pieces built on UDP broadcast:

  - `LanAdvertiser` (host side): repeats a small "I'm here" broadcast packet
    while a game is being hosted.
  - `LanBrowser` (client side): listens for those broadcasts and keeps a
    short-lived list of servers it has heard from recently.

Both are best-effort, and NetworkManager treats them that way: UDP broadcast
never crosses a router, and some networks (guest Wi-Fi with client isolation,
some VPNs, some firewalls) block it even within a single subnet. Neither
class raises if broadcast isn't available here - they log one warning and
quietly do nothing from then on, so a game that also offers "enter an IP
address manually" (which doesn't depend on broadcast at all - see
NetworkManager.join()) keeps working regardless.
"""
import json
import socket

from engine.core.debug_manager import DebugManager

# Rejects stray UDP traffic from anything else that happens to be broadcasting
# on the same port (other apps, other games, noise) without logging about it.
DISCOVERY_MAGIC = "pygame_engine_lan_v1"
ADVERTISE_INTERVAL = 1.0     # seconds between broadcast pings
SERVER_TIMEOUT = 3.0         # a browser forgets a server it hasn't heard from in this long


def _guess_directed_broadcast():
    """Best-effort "a.b.c.255" for this machine's LAN address (assuming a /24
    network, by far the most common home setup), or None if it can't be
    worked out. Sent to *in addition to* 255.255.255.255: on some systems the
    limited broadcast leaves through the wrong network adapter (a VPN or
    virtual adapter), while the subnet-directed one follows the LAN route."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("198.51.100.1", 80))   # TEST-NET-2 (RFC 5737): nothing is ever actually sent
        ip = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    parts = ip.split(".")
    if len(parts) != 4 or ip.startswith("127."):
        return None
    return ".".join(parts[:3] + ["255"])


class LanAdvertiser:
    """Host side: broadcasts this game's presence on `discovery_port` every
    ADVERTISE_INTERVAL seconds. Call `update(dt)` every frame; it does
    nothing between intervals. Update `player_count` as players join and
    leave so browsers see a current count."""

    def __init__(self, name, game_port, discovery_port, max_players):
        self.name = name
        self.game_port = game_port
        self.discovery_port = discovery_port
        self.max_players = max_players
        self.player_count = 0
        self._sock = None
        self._timer = ADVERTISE_INTERVAL   # send one immediately, not after the first full interval
        self._available = False
        self._targets = ["255.255.255.255"]
        directed = _guess_directed_broadcast()
        if directed is not None and directed not in self._targets:
            self._targets.append(directed)
        self._open_socket()

    def _open_socket(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setblocking(False)
            self._sock = sock
            self._available = True
        except OSError as exc:
            DebugManager.log_warning(
                f"LAN discovery broadcast unavailable ({exc}); players on this network will "
                f"need to enter the host's IP address manually.", source="Networking")
            self._available = False

    def update(self, dt):
        if not self._available:
            return
        self._timer += dt
        if self._timer < ADVERTISE_INTERVAL:
            return
        self._timer = 0.0
        message = json.dumps({
            "magic": DISCOVERY_MAGIC, "name": self.name, "port": self.game_port,
            "players": self.player_count, "max_players": self.max_players,
        }).encode("utf-8")
        for address in self._targets:
            try:
                self._sock.sendto(message, (address, self.discovery_port))
            except OSError:
                continue   # one target failing (no route on that adapter) must not stop the others

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._available = False


class ServerInfo:
    """One server a LanBrowser has heard from. `address`/`port` are exactly
    what to pass to `NetworkManager.join()`."""

    __slots__ = ("name", "address", "port", "players", "max_players", "last_seen")

    def __init__(self, name, address, port, players, max_players, last_seen):
        self.name = name
        self.address = address
        self.port = port
        self.players = players
        self.max_players = max_players
        self.last_seen = last_seen

    def __repr__(self):
        return f"ServerInfo({self.name!r} at {self.address}:{self.port}, {self.players}/{self.max_players})"

    def __eq__(self, other):
        return isinstance(other, ServerInfo) and (self.name, self.address, self.port,
                                                   self.players, self.max_players) == \
            (other.name, other.address, other.port, other.players, other.max_players)


class LanBrowser:
    """Client side: listens on `discovery_port` for LanAdvertiser broadcasts
    and keeps a rolling list of servers currently on the network. Call
    `update(dt)` every frame; read `.servers` at any time - it's always a
    fresh snapshot, safe to iterate."""

    def __init__(self, discovery_port):
        self.discovery_port = discovery_port
        self._sock = None
        self._servers = {}    # (address, port) -> ServerInfo
        self._available = False
        self._clock = 0.0
        self._open_socket()

    def _open_socket(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.discovery_port))
            sock.setblocking(False)
            self._sock = sock
            self._available = True
        except OSError as exc:
            DebugManager.log_warning(
                f"LAN discovery listening unavailable ({exc}); enter the host's IP address "
                f"manually instead of browsing for it.", source="Networking")
            self._available = False

    def update(self, dt):
        self._clock += dt
        if self._available:
            while True:
                try:
                    data, addr = self._sock.recvfrom(4096)
                except BlockingIOError:
                    break
                except OSError:
                    break
                self._handle_packet(data, addr)
        stale = [key for key, info in self._servers.items() if self._clock - info.last_seen > SERVER_TIMEOUT]
        for key in stale:
            del self._servers[key]

    def _handle_packet(self, data, addr):
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return                          # not our protocol - ignore silently, a shared network is noisy
        if not isinstance(payload, dict) or payload.get("magic") != DISCOVERY_MAGIC:
            return
        port = payload.get("port")
        if not isinstance(port, int) or isinstance(port, bool):
            return
        players, max_players = payload.get("players"), payload.get("max_players")
        self._servers[(addr[0], port)] = ServerInfo(
            name=str(payload.get("name", "Game")), address=addr[0], port=port,
            players=int(players) if isinstance(players, (int, float)) and not isinstance(players, bool) else 0,
            max_players=int(max_players) if isinstance(max_players, (int, float)) and not isinstance(max_players, bool) else 0,
            last_seen=self._clock)

    @property
    def servers(self):
        """A fresh list of currently-known servers, most-recently-seen first."""
        return sorted(self._servers.values(), key=lambda info: -info.last_seen)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._servers.clear()
        self._available = False
