"""Connection: one non-blocking TCP socket, doing length-prefixed message
framing over it (see protocol.py). The same class is used for the client's
single socket to the host and for each of the host's per-client sockets - a
Connection has no idea whether it's "the host side" or "the client side" of
anything, it just moves framed dict messages in both directions without ever
blocking the caller.

NetworkManager drives every Connection once per frame; there is no thread and
no lock anywhere in this module - the same single thread that runs your game
frame also runs this, so nothing here can preempt your code mid-frame, and
none of the engine's GameObject/Scene graph needs to be made thread-safe on
account of networking.
"""
import socket
import time

from engine.core.debug_manager import DebugManager
from engine.networking import protocol

# A peer that stops reading (a hung app) makes our outgoing buffer grow for as
# long as we keep queuing to it. Past this size we give up on it and close the
# connection - the owner of the Connection sees is_open == False and drops it.
MAX_SEND_BUFFER = 4 * 1024 * 1024

# One pump_recv() call reads at most this many chunks of _RECV_CHUNK bytes (so
# up to 1 MiB per frame) - enough to keep up with a burst, bounded so a flooding
# peer cannot monopolise a frame. The common case is still a single recv().
_RECV_CHUNK = 65536
_MAX_READS_PER_PUMP = 16


class Connection:
    """Wraps an already-connected, non-blocking socket. A brand new outbound
    connection (still completing `connect()`) is not yet a Connection - see
    NetworkManager's client-connect handling for that brief earlier phase."""

    def __init__(self, sock, address):
        sock.setblocking(False)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass  # not fatal - only means small messages may coalesce slightly more than ideal
        self.sock = sock
        self.address = address            # (ip, port) of the remote end
        self._recv_buffer = bytearray()
        self._send_buffer = bytearray()
        self.is_open = True
        # Filled in by NetworkManager once known; Connection itself never reads these.
        self.player_id = None
        self.name = None

    def queue_send(self, message):
        """Frame `message` and append it to the outgoing buffer. Never blocks
        and never raises for a full buffer - actually writing to the socket
        happens in `pump_send()`, called once per frame."""
        if not self.is_open:
            return
        # protocol.encode() raises ProtocolError for an unserializable/oversized
        # message: that is a bug in the caller, not a network fault - let it surface.
        self._send_buffer += protocol.encode(message)
        if len(self._send_buffer) > MAX_SEND_BUFFER:
            DebugManager.log_warning(f"Connection to {self.address} stopped reading "
                                     f"({len(self._send_buffer)} bytes queued); dropping it.", source="Networking")
            self.close()

    def pump_send(self):
        """Push as much of the outgoing buffer to the socket as it will
        accept right now, without blocking. Safe to call every frame even
        with nothing queued (the common case)."""
        while self._send_buffer and self.is_open:
            try:
                sent = self.sock.send(self._send_buffer)
            except BlockingIOError:
                break                       # the OS send buffer is full for now; retry next frame
            except OSError:
                self.close()
                return
            if sent <= 0:
                break
            del self._send_buffer[:sent]

    def pump_recv(self):
        """Read whatever is available without blocking and return every
        complete message that's now assembled (zero, one, or several).
        Closes the connection (is_open becomes False) if the peer closed the
        socket, or if it sent something that violates the protocol - in
        either case there is nothing more to read correctly."""
        if not self.is_open:
            return []
        peer_gone = False
        for _ in range(_MAX_READS_PER_PUMP):
            try:
                chunk = self.sock.recv(_RECV_CHUNK)
            except BlockingIOError:
                break                       # nothing (more) available right now - normal, not an error
            except OSError:
                peer_gone = True
                break
            if not chunk:                   # recv() returning empty on a "readable" socket means the peer closed it
                peer_gone = True
                break
            self._recv_buffer += chunk
            if len(chunk) < _RECV_CHUNK:
                break                       # a short read means the OS buffer is drained: skip a pointless extra syscall

        messages = []
        try:
            while True:
                message, consumed = protocol.try_decode_one(self._recv_buffer)
                if message is None:
                    break
                del self._recv_buffer[:consumed]
                messages.append(message)
        except protocol.ProtocolError:
            self.close()                    # framing is now unrecoverable on this connection
            return messages                 # still return whatever was validly decoded before the corruption
        if peer_gone:
            self.close()                    # but only after handing over everything that arrived before the close
        return messages

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        try:
            self.sock.close()
        except OSError:
            pass

    def flush_and_close(self, timeout=1.0):
        """A deliberate, graceful close: give any already-queued outgoing
        bytes (typically a final "disconnect" notice) up to `timeout`
        seconds to actually leave this machine, then perform a proper
        half-close (SHUT_WR) before closing outright. Plain `close()` can
        drop not-yet-transmitted bytes if the process exits immediately
        after - most visibly when unread incoming data is still sitting in
        this socket's receive buffer at that moment, which some OSes turn
        into an abortive RST instead of an orderly FIN. Use this instead of
        `close()` when the other side must actually receive what you just
        sent; the normal per-frame path keeps using plain `close()`."""
        if not self.is_open:
            return
        deadline = time.monotonic() + timeout
        while self._send_buffer and time.monotonic() < deadline:
            self.pump_send()
            if self._send_buffer:
                time.sleep(0.01)
        try:
            self.sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self.close()

    @property
    def has_pending_send(self):
        return bool(self._send_buffer)

    def fileno(self):
        return self.sock.fileno()

    def __repr__(self):
        return f"Connection({self.address}, player_id={self.player_id})"
