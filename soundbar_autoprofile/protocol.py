"""Framing of the Creative vendor HID protocol used by the Sound Blaster GS5.

Every report is 64 bytes including the report ID, zero padded::

    05 6a <op> <len lo> <len hi> <data ...>

See docs/PROTOCOL.md for the full reference.
"""

from __future__ import annotations

from dataclasses import dataclass

REPORT_ID = 0x05
MAGIC = 0x6A
REPORT_SIZE = 64

OP_ACK = 0x02
OP_HELLO = 0x09
OP_CONNECT = 0x2C
OP_LIGHTING = 0x3A


def build_frame(op: int, data: bytes | list[int] = b"", magic: int = MAGIC) -> bytes:
    """Build one 64-byte output report."""
    data = bytes(data)
    frame = bytes([REPORT_ID, magic, op, len(data) & 0xFF, len(data) >> 8]) + data
    if len(frame) > REPORT_SIZE:
        raise ValueError(f"frame is {len(frame)} bytes, the limit is {REPORT_SIZE}")
    return frame.ljust(REPORT_SIZE, b"\0")


def parse_hex(text: str) -> bytes:
    """'05 6a 09 01 00 00' or '056a09010000' -> bytes."""
    cleaned = text.replace(",", " ").replace(":", " ").replace("0x", "").split()
    return bytes.fromhex("".join(cleaned))


@dataclass(frozen=True)
class Frame:
    report_id: int
    magic: int
    op: int
    data: bytes

    @classmethod
    def parse(cls, raw: bytes) -> Frame | None:
        raw = bytes(raw)
        if len(raw) < 5 or raw[0] != REPORT_ID:
            return None
        n = raw[3] | raw[4] << 8
        return cls(raw[0], raw[1], raw[2], raw[5 : 5 + n])

    def hex(self) -> str:
        head = bytes([self.report_id, self.magic, self.op, len(self.data) & 0xFF, len(self.data) >> 8])
        return (head + self.data).hex(" ")


def is_ack_for(raw: bytes, op: int, cmd: int) -> bool:
    """A set is acknowledged with 05 6a 02 03 00 <op> 00 <cmd> <status>."""
    return len(raw) >= 9 and raw[:3] == bytes([REPORT_ID, MAGIC, OP_ACK]) and raw[5] == op and raw[7] == cmd


def ack_status(raw: bytes) -> int:
    return raw[8]
