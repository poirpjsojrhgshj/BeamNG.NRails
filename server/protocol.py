"""Framing: 4-byte little-endian uint32 length + UTF-8 JSON payload."""
import asyncio
import json
import struct

HEADER = struct.Struct("<I")
MAX_FRAME = 16 * 1024 * 1024


class ProtocolError(Exception):
    pass


def encode(msg):
    # real UTF-8, not \u escapes: the game's jsonDecode leaves those as text ("Provence-Alpes-Cu00f4te d'Azur" in the status
    # bar, 2026-10-15)
    payload = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return HEADER.pack(len(payload)) + payload


def decode_payload(payload):
    try:
        msg = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError(f"bad JSON frame: {e}") from None
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        raise ProtocolError("frame is not an object with a 'type'")
    return msg


def _check_len(n):
    if n > MAX_FRAME:
        raise ProtocolError(f"frame too large: {n} bytes")
    return n


async def read_message(reader):
    """Next message from an asyncio StreamReader, or None on a clean EOF."""
    try:
        head = await reader.readexactly(HEADER.size)
    except asyncio.IncompleteReadError as e:
        if not e.partial:
            return None
        raise ProtocolError("connection closed inside a frame header") from None
    n = _check_len(HEADER.unpack(head)[0])
    try:
        payload = await reader.readexactly(n)
    except asyncio.IncompleteReadError:
        raise ProtocolError("connection closed inside a frame") from None
    return decode_payload(payload)


class Decoder:
    """Incremental decoder for blocking clients: feed() bytes, get messages."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        out = []
        while len(self.buf) >= HEADER.size:
            n = _check_len(HEADER.unpack_from(self.buf)[0])
            if len(self.buf) < HEADER.size + n:
                break
            out.append(decode_payload(bytes(self.buf[HEADER.size:HEADER.size + n])))
            del self.buf[:HEADER.size + n]
        return out
