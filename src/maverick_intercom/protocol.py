"""Version 1 framing. TCP is a byte stream; frame boundaries must be explicit."""

import asyncio
from dataclasses import dataclass
from enum import IntEnum
import json
import struct

HEADER = struct.Struct("!4sBBHI")
MAGIC = b"MVIC"
VERSION = 1
FRAME_BYTES = 640  # 320 little-endian signed int16 samples: 20 ms at 16 kHz.
MAX_CONTROL_BYTES = 2048


class Kind(IntEnum):
    HELLO = 1
    STATUS = 2
    AUDIO = 3
    PING = 4
    PONG = 5


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    kind: Kind
    payload: bytes = b""
    sequence: int = 0

    def encode(self) -> bytes:
        validate(self.kind, len(self.payload), self.sequence)
        return HEADER.pack(MAGIC, VERSION, self.kind, len(self.payload), self.sequence) + self.payload


def validate(kind: Kind, length: int, sequence: int) -> None:
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ProtocolError("invalid sequence")
    if kind == Kind.AUDIO:
        if length != FRAME_BYTES:
            raise ProtocolError("audio must contain exactly 640 bytes")
    elif kind in (Kind.PING, Kind.PONG):
        if length:
            raise ProtocolError("heartbeat must be empty")
    elif not 0 < length <= MAX_CONTROL_BYTES:
        raise ProtocolError("invalid control length")


async def read_frame(reader: asyncio.StreamReader) -> Frame:
    magic, version, raw_kind, length, sequence = HEADER.unpack(await reader.readexactly(HEADER.size))
    if magic != MAGIC or version != VERSION:
        raise ProtocolError("unsupported framing")
    try:
        kind = Kind(raw_kind)
    except ValueError as exc:
        raise ProtocolError("unknown frame kind") from exc
    validate(kind, length, sequence)  # Reject oversized headers before reading bodies.
    return Frame(kind, await reader.readexactly(length), sequence)


def control(kind: Kind, data: dict) -> Frame:
    return Frame(kind, json.dumps(data, separators=(",", ":")).encode("utf-8"))


def decode_control(frame: Frame) -> dict:
    try:
        value = json.loads(frame.payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError("invalid control JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("control must be an object")
    return value
