"""Pull Creative HID frames out of a USB capture (.pcapng / .pcap) to decode new commands.

Supports USBPcap captures (Windows, Wireshark's USBPcap option, link type 249) and Linux usbmon captures
(link types 189 and 220). Pure Python: Wireshark/tshark is only needed to make the capture.
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .protocol import OP_ACK, REPORT_ID, REPORT_SIZE

LINKTYPE_USBPCAP = 249
LINKTYPE_USB_LINUX = 189
LINKTYPE_USB_LINUX_MMAPPED = 220
MAGICS = (0x6A, 0x5A)  # second byte of Creative frames seen so far


@dataclass
class CapturedFrame:
    time: float          # seconds from the first packet
    direction: str       # "out" = app -> soundbar, "in" = soundbar -> app
    data: bytes

    def hex(self) -> str:
        return self.data.hex(" ")


def _packets(raw: bytes):
    """Yield (linktype, timestamp_seconds, packet_bytes) from pcap or pcapng data."""
    if len(raw) < 24:
        raise ValueError("file too short to be a capture")
    magic = raw[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
        yield from _pcap(raw)
    elif magic == b"\x0a\x0d\x0d\x0a":
        yield from _pcapng(raw)
    else:
        raise ValueError("not a pcap/pcapng file")


def _pcap(raw: bytes):
    m = raw[:4]
    e = "<" if m in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    nano = m in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
    linktype = struct.unpack_from(e + "I", raw, 20)[0] & 0x0FFFFFFF
    off = 24
    while off + 16 <= len(raw):
        sec, frac, caplen, _ = struct.unpack_from(e + "IIII", raw, off)
        off += 16
        yield linktype, sec + frac / (1e9 if nano else 1e6), raw[off : off + caplen]
        off += caplen


def _pcapng(raw: bytes):
    e = "<"
    interfaces: list[tuple[int, float]] = []  # (linktype, seconds per tick)
    off = 0
    while off + 12 <= len(raw):
        btype, blen = struct.unpack_from(e + "II", raw, off)
        if btype == 0x0A0D0D0A:  # section header: sets byte order
            bom = raw[off + 8 : off + 12]
            e = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
            btype, blen = struct.unpack_from(e + "II", raw, off)
            interfaces = []
        if blen < 12 or off + blen > len(raw):
            break
        body = raw[off + 8 : off + blen - 4]
        if btype == 1:  # interface description
            linktype = struct.unpack_from(e + "H", body, 0)[0]
            interfaces.append((linktype, _tsresol(body[8:], e)))
        elif btype == 6:  # enhanced packet
            iface, hi, lo, caplen, _ = struct.unpack_from(e + "IIIII", body, 0)
            if iface < len(interfaces):
                linktype, tick = interfaces[iface]
                yield linktype, ((hi << 32) | lo) * tick, body[20 : 20 + caplen]
        off += blen


def _tsresol(opts: bytes, e: str) -> float:
    i = 0
    while i + 4 <= len(opts):
        code, length = struct.unpack_from(e + "HH", opts, i)
        if code == 0:
            break
        if code == 9 and length >= 1:
            v = opts[i + 4]
            return 2.0 ** -(v & 0x7F) if v & 0x80 else 10.0 ** -v
        i += 4 + ((length + 3) & ~3)
    return 1e-6


# USB transfer types (same numbering in USBPcap and usbmon)
_XFER_INTERRUPT = 1
_XFER_CONTROL = 2
_HID_TRANSFERS = (_XFER_INTERRUPT, _XFER_CONTROL)  # iso (audio) and bulk never carry HID reports


def _usb_payload(linktype: int, pkt: bytes) -> tuple[str, bytes, bool] | None:
    """(direction, payload, is_control) of one HID (interrupt/control) USB packet, or None if it carries none."""
    if linktype == LINKTYPE_USBPCAP:
        # u16 headerLen, u64 irpId, u32 status, u16 function, u8 info, u16 bus, u16 device, u8 endpoint,
        # u8 transfer, u32 dataLength (+ u8 stage for control; headerLen covers it)
        if len(pkt) < 27:
            return None
        header_len = struct.unpack_from("<H", pkt, 0)[0]
        completion = bool(pkt[16] & 0x01)  # info bit 0: 1 = PDO -> FDO (completion, from the device)
        endpoint, transfer = pkt[21], pkt[22]
        if transfer not in _HID_TRANSFERS or header_len < 27:
            return None
        if transfer == _XFER_CONTROL:
            return ("in" if completion else "out"), pkt[header_len:], True
        endpoint_in = bool(endpoint & 0x80)
        if endpoint_in != completion:  # OUT data rides on the submit, IN data on the completion
            return None
        return ("in" if endpoint_in else "out"), pkt[header_len:], False
    if linktype in (LINKTYPE_USB_LINUX, LINKTYPE_USB_LINUX_MMAPPED):
        header_len = 48 if linktype == LINKTYPE_USB_LINUX else 64
        if len(pkt) < header_len:
            return None
        transfer, endpoint = pkt[9], pkt[10]
        if transfer not in _HID_TRANSFERS:
            return None
        return ("in" if endpoint & 0x80 else "out"), pkt[header_len:], transfer == _XFER_CONTROL
    return None


def _creative_frame(payload: bytes, control: bool = True) -> bytes | None:
    # interrupt transfers start with the report; control SET_REPORT may carry the 8-byte setup packet first
    for start in (0, 8) if control else (0,):
        p = payload[start:]
        if len(p) < 5 or p[0] != REPORT_ID or p[1] not in MAGICS:
            continue
        n = p[3] | p[4] << 8
        if n < 1 or 5 + n > REPORT_SIZE:
            continue
        if p[2] == OP_ACK:  # "05 6a 02 03 00 <op> 00 <cmd> <status>": the status byte is not counted
            n += 1
        return bytes(p[: 5 + n]) if 5 + n <= len(p) else bytes(p).rstrip(b"\0")
    return None


def read_frames(path: str | Path) -> list[CapturedFrame]:
    raw = Path(path).read_bytes()
    frames: list[CapturedFrame] = []
    t0: float | None = None
    for linktype, ts, pkt in _packets(raw):
        got = _usb_payload(linktype, pkt)
        if got is None:
            continue
        direction, payload, control = got
        frame = _creative_frame(payload, control)
        if frame is None:
            continue
        if t0 is None:
            t0 = ts
        frames.append(CapturedFrame(ts - t0, direction, frame))
    return frames


def polling_frames(frames: list[CapturedFrame], idle_seconds: float = 10.0, poll_threshold: int = 4) -> set[bytes]:
    """App->soundbar frames that are background polling, not settings changes.

    The capture guide has the user wait ``idle_seconds`` after opening the app before touching anything, so whatever
    the app sends in that window is its own traffic (handshake and polling). Without frames in that window (or with
    ``idle_seconds=0``), frames sent at least ``poll_threshold`` times count as polling instead."""
    outs = [f for f in frames if f.direction == "out"]
    idle = {f.data for f in outs if f.time < idle_seconds}
    if idle:
        return idle
    counts = Counter(f.data for f in outs)
    return {data for data, n in counts.items() if n >= poll_threshold}


def bursts(frames: list[CapturedFrame], gap: float = 1.5, poll_threshold: int = 4,
           keep_polling: bool = False, idle_seconds: float = 10.0) -> list[list[CapturedFrame]]:
    """Group app->soundbar frames into bursts separated by quiet gaps. Polling (see :func:`polling_frames`) is
    dropped unless ``keep_polling``."""
    outs = [f for f in frames if f.direction == "out"]
    if not keep_polling:
        polling = polling_frames(frames, idle_seconds, poll_threshold)
        outs = [f for f in outs if f.data not in polling]
    groups: list[list[CapturedFrame]] = []
    for f in outs:
        if groups and f.time - groups[-1][-1].time <= gap:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def reply_to(frames: list[CapturedFrame], sent: CapturedFrame, window: float = 0.2) -> CapturedFrame | None:
    for f in frames:
        if f.direction == "in" and sent.time <= f.time <= sent.time + window:
            return f
    return None
