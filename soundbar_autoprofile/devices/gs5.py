"""Creative Sound Blaster GS5 driver (USB 041e:329d, vendor HID interface).

The lighting commands come from the reverse-engineering work in https://github.com/JRiley2025/gs5-rgb
(MIT, Copyright (c) 2026 JRiley2025), reimplemented here on top of hidapi so it runs on Windows, macOS and Linux.
EQ / SuperWide commands are filled in from USB captures of Creative App (see docs/CAPTURE_GUIDE.md); until a
setting is decoded, put the captured frames in a profile's ``frames:`` list.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..protocol import (
    MAGIC,
    OP_CONNECT,
    OP_HELLO,
    OP_LIGHTING,
    REPORT_ID,
    REPORT_SIZE,
    ack_status,
    build_frame,
    is_ack_for,
    parse_hex,
)
from .base import Device, DeviceError, Profile

VENDOR_ID = 0x041E
PRODUCT_ID = 0x329D
VENDOR_USAGE_PAGE = 0xFF01

SEGMENTS = 7
LIGHTING_MODES = {"static": 0x03, "cycle": 0x01, "wave": 0x04, "aurora": 0x08, "glowing": 0x09,
                  "peak": 0x0A, "chasers": 0x0B}

# Decoded from Creative App captures: preset name -> frames (hex) that select it. Empty until decoded.
EQ_PRESETS: dict[str, list[str]] = {}
# SuperWide on/off -> frames (hex). Empty until decoded.
SUPERWIDE: dict[bool, list[str]] = {}


class Transport:
    """Minimal interface the driver needs; lets tests use a fake device."""

    def write(self, report: bytes) -> None: ...

    def read(self, timeout_s: float) -> bytes | None: ...

    def close(self) -> None: ...


class HidTransport(Transport):
    def __init__(self, path: bytes | str):
        import hid  # hidapi; imported lazily so tests and --dry-run work without it

        self._dev = hid.device()
        try:
            self._dev.open_path(path if isinstance(path, bytes) else path.encode())
        except OSError as e:
            raise DeviceError(f"cannot open the GS5 HID interface ({e}). On Linux install "
                              "udev/70-gs5-hidraw.rules, see README.") from e
        self._dev.set_nonblocking(False)

    def write(self, report: bytes) -> None:
        if self._dev.write(report) < 0:
            raise DeviceError("writing to the GS5 failed (was it unplugged?)")

    def read(self, timeout_s: float) -> bytes | None:
        data = self._dev.read(REPORT_SIZE, max(1, int(timeout_s * 1000)))
        return bytes(data) if data else None

    def close(self) -> None:
        self._dev.close()


def find_paths() -> list[bytes]:
    """hidapi paths of connected GS5 vendor interfaces."""
    import hid

    found = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    vendor = [d["path"] for d in found if d.get("usage_page") == VENDOR_USAGE_PAGE]
    if vendor:
        return vendor
    # Some backends (old Linux hidraw builds) report usage_page 0: fall back to interface 0.
    return [d["path"] for d in found if d.get("interface_number") in (0, -1) and d.get("usage_page") in (0, None)]


def _colour_bytes(colours: list[str]) -> list[int]:
    out: list[int] = []
    for c in colours:
        c = c.strip().lstrip("#")
        if len(c) != 6:
            raise ValueError(f"colour must be RRGGBB, got {c!r}")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        out += [0xFF, b, g, r]  # sent as ff B G R
    return out


class GS5(Device):
    name = "Sound Blaster GS5"

    def __init__(self, transport: Transport, timeout: float = 0.3, sleep: Callable[[float], None] = time.sleep):
        self.t = transport
        self.timeout = timeout
        self._sleep = sleep
        self.hello_reply: bytes | None = None
        self._lighting_wanted = False
        self._drain(0.05)
        self.handshake()

    @classmethod
    def open(cls, path: bytes | str | None = None, **kw) -> GS5:
        if path is None:
            paths = find_paths()
            if not paths:
                raise DeviceError("no Sound Blaster GS5 found. It must be connected with the USB-C cable "
                                  "(Bluetooth/optical/AUX cannot be controlled).")
            path = paths[0]
        return cls(HidTransport(path), **kw)

    def close(self) -> None:
        self.t.close()

    # --- transport -------------------------------------------------------------------------------------
    def _drain(self, secs: float) -> None:
        end = time.monotonic() + secs
        while (left := end - time.monotonic()) > 0 and self.t.read(left) is not None:
            pass

    def _wait(self, match: Callable[[bytes], bool], timeout: float | None = None) -> bytes | None:
        end = time.monotonic() + (timeout or self.timeout)
        while (left := end - time.monotonic()) > 0:
            rep = self.t.read(left)
            if rep is None:
                return None
            if match(rep):
                return rep
        return None

    def request(self, op: int, data: bytes | list[int] = b"", match: Callable[[bytes], bool] | None = None,
                timeout: float | None = None) -> bytes | None:
        """Send one frame and wait for the first reply accepted by ``match`` (default: any reply).
        The GS5 ignores commands written back to back, so every command waits for its reply."""
        self.t.write(build_frame(op, data))
        return self._wait(match or (lambda r: True), timeout)

    def send_raw(self, frame: bytes, listen: float = 0.3) -> list[bytes]:
        """Send a raw frame and return every report received within ``listen`` seconds."""
        if frame[:1] != bytes([REPORT_ID]):
            raise ValueError("raw frames must start with the report id 05")
        self.t.write(frame.ljust(REPORT_SIZE, b"\0"))
        replies, end = [], time.monotonic() + listen
        while (left := end - time.monotonic()) > 0:
            rep = self.t.read(left)
            if rep is None:
                break
            replies.append(rep)
        return replies

    def handshake(self) -> None:
        self.hello_reply = self.request(OP_HELLO, [0x00], match=_starts(OP_HELLO))
        if self.hello_reply is None:
            raise DeviceError("the GS5 did not answer the hello frame")
        self.request(OP_CONNECT, [0x01], match=_starts(OP_CONNECT))  # Creative App sends this on connect

    # --- lighting (op 3a) --------------------------------------------------------------------------------
    def _set(self, cmd: int, args: list[int] | tuple[int, ...] = ()) -> None:
        for _ in range(2):
            rep = self.request(OP_LIGHTING, [cmd, *args], match=lambda r: is_ack_for(r, OP_LIGHTING, cmd))
            if rep is not None:
                if ack_status(rep) != 0:
                    raise DeviceError(f"GS5 rejected lighting command {cmd:02x} (status {ack_status(rep):02x})")
                return
        raise DeviceError(f"no reply to lighting command {cmd:02x}")

    def _get(self, cmd: int, args: list[int] | tuple[int, ...] = ()) -> bytes:
        def match(r: bytes) -> bool:
            return r[:3] == bytes([REPORT_ID, MAGIC, OP_LIGHTING]) and len(r) > 5 and r[5] == cmd

        for _ in range(2):
            rep = self.request(OP_LIGHTING, [cmd, *args], match=match)
            if rep is not None:
                n = rep[3] | rep[4] << 8
                return rep[6 : 5 + n]
        raise DeviceError(f"no reply to lighting query {cmd:02x}")

    def lighting_on(self, on: bool = True) -> None:
        self._set(0x25, [1 if on else 0])

    def lighting_is_on(self) -> bool:
        return self._get(0x26)[0] == 1

    def set_brightness(self, percent: int) -> None:
        self._set(0x27, [round(max(0, min(100, percent)) * 255 / 100)])

    def brightness(self) -> int:
        return round(self._get(0x28)[0] * 100 / 255)

    def active_slot(self) -> int:
        return self._get(0x2E)[0]

    def slot_mode(self, slot: int) -> int:
        return self._get(0x2A, [slot])[1]

    def set_mode(self, slot: int, mode: str) -> None:
        """A mode change resets the slot's colours and the global brightness; brightness is put back."""
        mid = LIGHTING_MODES[mode]
        level = self._get(0x28)[0]
        for _ in range(3):
            self._set(0x29, [slot, mid])
            self._drain(0.3)  # the GS5 pushes the slot's settings; commands sent now can be lost
            if self.slot_mode(slot) == mid:
                if self._get(0x28)[0] != level:
                    self._set(0x27, [level])
                return
        raise DeviceError(f"lighting slot {slot} would not switch to {mode}")

    def activate_slot(self, slot: int) -> None:
        self._set(0x2D, [slot])
        self._drain(0.3)

    def set_colours(self, slot: int, colours: list[str]) -> None:
        self._set(0x2B, [slot, 0x01, 0x01, *_colour_bytes(colours)])

    def static(self, colours: str | list[str], slot: int = 1) -> None:
        if isinstance(colours, str):
            colours = [colours] * SEGMENTS
        if len(colours) != SEGMENTS:
            raise ValueError(f"rgb needs 1 or {SEGMENTS} colours")
        if self.slot_mode(slot) != LIGHTING_MODES["static"]:
            self.set_mode(slot, "static")
        if self.active_slot() != slot:
            self.activate_slot(slot)
        if not self.lighting_is_on():
            self.lighting_on(True)
        self.set_colours(slot, colours)

    def wake(self) -> None:
        """The strip can go dark (auto-standby) while still reporting 'on'; re-assert it."""
        self.handshake()
        self.activate_slot(self.active_slot())
        self.lighting_on(True)

    # --- Device API ------------------------------------------------------------------------------------
    def _send_frames(self, frames: list[str]) -> None:
        for hx in frames:
            self.send_raw(parse_hex(hx))

    def apply(self, profile: Profile) -> list[str]:
        warnings: list[str] = []
        if profile.eq is not None:
            if profile.eq in EQ_PRESETS:
                self._send_frames(EQ_PRESETS[profile.eq])
            else:
                warnings.append(f"EQ preset {profile.eq!r} is not decoded yet for the GS5 "
                                "(see docs/CAPTURE_GUIDE.md); skipped")
        if profile.superwide is not None:
            if profile.superwide in SUPERWIDE:
                self._send_frames(SUPERWIDE[profile.superwide])
            else:
                warnings.append("SuperWide is not decoded yet for the GS5 (see docs/CAPTURE_GUIDE.md); skipped")
        if profile.frames:
            self._send_frames(profile.frames)
        if profile.lighting is False:
            self.lighting_on(False)
            self._lighting_wanted = False
        elif profile.rgb is not None:
            self.static(profile.rgb)
            self._lighting_wanted = True
        if profile.brightness is not None and profile.lighting is not False:
            self.set_brightness(profile.brightness)
        return warnings

    def keepalive(self) -> None:
        if self._lighting_wanted:
            self.wake()

    def probe(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "device": self.name,
            "usb_id": f"{VENDOR_ID:04x}:{PRODUCT_ID:04x}",
            "hello_reply": self.hello_reply.rstrip(b"\0").hex(" ") if self.hello_reply else None,
            "eq_presets_decoded": sorted(EQ_PRESETS),
            "superwide_decoded": bool(SUPERWIDE),
        }
        try:
            info["lighting"] = {
                "on": self.lighting_is_on(),
                "brightness_percent": self.brightness(),
                "active_slot": self.active_slot(),
            }
        except DeviceError as e:
            info["lighting"] = f"unavailable: {e}"
        return info


def _starts(op: int) -> Callable[[bytes], bool]:
    prefix = bytes([REPORT_ID, MAGIC, op])
    return lambda r: r.startswith(prefix)
