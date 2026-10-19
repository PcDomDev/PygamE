"""Wire protocol: message framing, and the vocabulary of message types
NetworkManager speaks. Two things live here on purpose - the byte-level
framing (so a message boundary in a TCP stream is never ambiguous) and the
*names* of every message type as constants, so a typo in a type string is a
NameError at import time instead of a silent protocol mismatch at runtime.

Wire format, one message: a 4-byte big-endian unsigned length prefix,
followed by exactly that many bytes of UTF-8-encoded JSON. JSON rather than
pickle is deliberate: it can never execute arbitrary code from a hostile or
corrupted peer, and it's readable in a packet capture while debugging.
"""
import json
import struct

PROTOCOL_VERSION = 1

# A generous but bounded ceiling on one message's payload size, so a garbled
# length prefix - or a hostile peer - can never make a receiver try to
# allocate gigabytes of memory for "one message". Legitimate traffic (a
# spawn, an RPC, a position update) never comes close to this.
MAX_MESSAGE_SIZE = 1 * 1024 * 1024  # 1 MiB

_HEADER = struct.Struct(">I")  # unsigned 32-bit big-endian length prefix
HEADER_SIZE = _HEADER.size

# -- session / control (handled internally by NetworkManager) ------------------
HELLO = "hello"                 # client -> host, right after connecting
WELCOME = "welcome"             # host -> client, handshake accepted
REJECT = "reject"               # host -> client, handshake refused (then the socket is closed)
PLAYER_JOINED = "player_joined"  # host -> other clients, a new player finished the handshake
PLAYER_LEFT = "player_left"      # host -> clients, a player disconnected
PING = "ping"                    # either direction, latency/liveness probe
PONG = "pong"                    # reply to a ping, echoes its token
DISCONNECT = "disconnect"        # either direction, "I'm leaving on purpose"

# -- gameplay (surfaced to game code through NetworkManager) --------------------
RPC = "rpc"
SPAWN_REQUEST = "spawn_request"   # client -> host, "please spawn this for everyone"
SPAWN = "spawn"                   # host -> everyone (including itself), the actual creation
DESPAWN_REQUEST = "despawn_request"  # client -> host
DESPAWN = "despawn"               # host -> everyone
TRANSFORM = "transform"           # owner -> host [-> everyone else], a position update
STATE = "state"                   # owner -> host [-> everyone else], changed NetworkState values


class ProtocolError(Exception):
    """A peer sent something that doesn't parse as a valid framed message, or
    a message bigger than MAX_MESSAGE_SIZE. Whoever catches this must close
    that connection - once framing is violated, the stream can no longer be
    trusted to be aligned on message boundaries, so there is no way to
    "resync" and keep reading it."""


def _reject_constant(name):
    # json.loads() accepts the non-standard literals NaN / Infinity / -Infinity by
    # default. A position that is NaN would poison every calculation that touches it
    # on the receiving side, so they are refused at the door.
    raise ValueError(f"non-finite number literal {name} is not allowed")


def _check_plain(value, path):
    """Raise TypeError, naming the exact spot, if `value` holds anything that is not plain JSON data."""
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TypeError(f"{path} is {value}, which can't be sent (NaN and infinity are not valid JSON numbers)")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_plain(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                # JSON would quietly turn 1 into "1" - and merge {1: "a", "1": "b"} into one entry, losing data.
                raise TypeError(f"{path} has a {type(key).__name__} key ({key!r}); dict keys must be strings")
            _check_plain(item, f"{path}[{key!r}]")
        return
    raise TypeError(f"{path} is a {type(value).__name__}, which can't be sent over the network")


def normalize_json(value, what="value"):
    """Check that `value` is plain JSON data - numbers (finite), strings, booleans, None, lists/tuples, and
    dicts with *string* keys - and return a copy of it as every receiver will see it (tuples become lists).
    Raises a TypeError naming the exact offending spot, *at the call site*, instead of failing later in the
    middle of a broadcast; and because the sender uses the returned copy too, host and clients can never
    disagree about what a payload was."""
    _check_plain(value, what)
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:   # pragma: no cover - _check_plain has caught the realistic cases
        raise TypeError(f"{what} must be JSON-serializable: {exc}") from exc


def encode(message):
    """A dict (must be JSON-serializable, and should have a "t" field) -> the
    exact bytes to place on the wire (length header + payload)."""
    try:
        payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"message is not JSON-serializable: {exc}") from exc
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"outgoing message of {len(payload)} bytes exceeds "
                            f"MAX_MESSAGE_SIZE ({MAX_MESSAGE_SIZE})")
    return _HEADER.pack(len(payload)) + payload


def try_decode_one(buffer):
    """Try to pull exactly one complete message off the front of `buffer` (a
    bytearray). Returns (message_dict, bytes_consumed) if a full message was
    available, or (None, 0) if `buffer` doesn't hold a complete message yet -
    normal; the caller should wait for more data to arrive and try again.
    Raises ProtocolError if the length prefix is unreasonable or the payload
    isn't valid UTF-8 JSON; the caller should treat the whole connection as
    broken in that case (see the note on ProtocolError above)."""
    if len(buffer) < HEADER_SIZE:
        return None, 0
    (length,) = _HEADER.unpack_from(buffer, 0)
    if length > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"peer announced a {length}-byte message (max {MAX_MESSAGE_SIZE})")
    total = HEADER_SIZE + length
    if len(buffer) < total:
        return None, 0
    raw = bytes(buffer[HEADER_SIZE:total])
    try:
        message = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:   # JSONDecodeError is a ValueError
        raise ProtocolError(f"malformed message payload: {exc}") from exc
    if not isinstance(message, dict) or "t" not in message:
        raise ProtocolError("a decoded message is not an object with a 't' (type) field")
    return message, total
