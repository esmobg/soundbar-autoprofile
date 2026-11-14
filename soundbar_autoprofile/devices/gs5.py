"""Creative Sound Blaster GS5 driver (USB 041e:329d, vendor HID interface).

The lighting commands come from the reverse-engineering work in https://github.com/JRiley2025/gs5-rgb
(MIT, Copyright (c) 2026 JRiley2025), reimplemented here on top of hidapi so it runs on Windows, macOS and Linux.
EQ, SuperWide and the other audio effects are NOT USB commands: on Windows Creative's audio-driver plugin applies
them on the PC (verified: Creative App sends nothing over the HID interface when they change). They are switched
through Creative App's Sound Modes instead (``sound_mode:``, see creative_app.py). ``EQ_PRESETS`` / ``SUPERWIDE``
stay for firmware/hosts where a USB command is found (Bluetooth, other OSes); ``frames:`` sends raw frames.
"""

from __future__ import annotations

import functools
import sys
import threading
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
from .base import CommandError, Device, DeviceError, Profile

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


def _hidapi():
    """The hidapi module to use (imported lazily so tests and --dry-run work without it).

    The PyPI ``hidapi`` wheels ship two modules on Linux: ``hid`` is the libusb backend (it detaches the kernel's
    usbhid driver, needs /dev/bus/usb access, reports usage_page 0 and claims the interface exclusively) and
    ``hidraw`` is the kernel hidraw backend, which shares the device with other apps. Prefer ``hidraw`` there.
    On macOS hidapi opens devices exclusively (seizing them from every other app); that is switched off."""
    mod = None
    if sys.platform.startswith("linux"):
        try:
            import hidraw as mod
        except ImportError:
            mod = None
    if mod is None:
        import hid as mod
    if sys.platform == "darwin":
        _darwin_shared_open(mod)
    return mod


def _darwin_shared_open(mod) -> None:
    try:
        mod.enumerate(0, 0)  # makes hidapi run hid_init(), which turns exclusive opens on
        import ctypes

        ctypes.CDLL(mod.__file__).hid_darwin_set_open_exclusive(0)
    except (OSError, AttributeError):
        pass  # hidapi without that call: opens stay exclusive


def _open_hint() -> str:
    if sys.platform.startswith("linux"):
        return "install udev/70-gs5-hidraw.rules (see README), then unplug and replug the USB cable"
    if sys.platform == "darwin":
        return ("allow your terminal or this app in System Settings > Privacy & Security > Input Monitoring, and "
                "check that no other app holds the soundbar open")
    return "unplug and replug the USB cable and try again"


class HidTransport(Transport):
    def __init__(self, path: bytes | str):
        self._dev = _hidapi().device()
        try:
            self._dev.open_path(path if isinstance(path, bytes) else path.encode())
        except OSError as e:
            raise DeviceError(f"cannot open the GS5 HID interface ({e}); {_open_hint()}") from e
        try:
            self._dev.set_nonblocking(False)
        except BaseException:
            self._dev.close()
            raise

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
    found = _hidapi().enumerate(VENDOR_ID, PRODUCT_ID)
    vendor = [d["path"] for d in found if d.get("usage_page") == VENDOR_USAGE_PAGE]
    if vendor:
        return vendor
    # Some backends (libusb, old Linux hidraw builds) report usage_page 0: fall back to interface 0.
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


def _level(percent: int) -> int:
    """Brightness percent -> the 00-ff value the GS5 uses."""
    return round(max(0, min(100, percent)) * 255 / 100)


def _locked(fn):
    """Run a method under the device lock, so callers on other threads (daemon, tray, keepalive) never interleave
    their frames or take each other's replies."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kw):
        with self._lock:
            return fn(self, *args, **kw)

    return wrapper


class GS5(Device):
    name = "Sound Blaster GS5"

    def __init__(self, transport: Transport, timeout: float = 0.3, sleep: Callable[[float], None] = time.sleep):
        self._lock = threading.RLock()
        self.t = transport
        self.timeout = timeout
        self._sleep = sleep
        self.hello_reply: bytes | None = None
        self.connect_reply: bytes | None = None
        self._lighting_wanted = False
        self._creative_app = None
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
        t = HidTransport(path)
        try:
            return cls(t, **kw)
        except BaseException:
            t.close()
            raise

    def close(self) -> None:
        self.t.close()

    # --- transport -------------------------------------------------------------------------------------
    def _drain(self, secs: float) -> None:
        end = time.monotonic() + secs
        while (left := end - time.monotonic()) > 0 and self.t.read(left) is not None:
            pass

    def _flush(self) -> None:
        """Drop input reports already queued. Every open handle (Creative App's too) receives every report, and
        late replies to earlier commands stay queued; either would be taken for the reply to the next command."""
        for _ in range(256):
            if self.t.read(0.001) is None:
                return

    def _wait(self, match: Callable[[bytes], bool], timeout: float | None = None) -> bytes | None:
        end = time.monotonic() + (timeout or self.timeout)
        while (left := end - time.monotonic()) > 0:
            rep = self.t.read(left)
            if rep is None:
                return None
            if match(rep):
                return rep
        return None

    @_locked
    def request(self, op: int, data: bytes | list[int] = b"", match: Callable[[bytes], bool] | None = None,
                timeout: float | None = None) -> bytes | None:
        """Send one frame and wait for the first reply accepted by ``match`` (default: any reply).
        The GS5 ignores commands written back to back, so every command waits for its reply."""
        frame = build_frame(op, data)
        self._flush()
        self.t.write(frame)
        return self._wait(match or (lambda r: True), timeout)

    @_locked
    def send_raw(self, frame: bytes, listen: float = 0.3) -> list[bytes]:
        """Send a raw frame and return every report received within ``listen`` seconds."""
        if frame[:1] != bytes([REPORT_ID]):
            raise ValueError("raw frames must start with the report id 05")
        if len(frame) > REPORT_SIZE:
            raise ValueError(f"raw frame is {len(frame)} bytes, the limit is {REPORT_SIZE}")
        self._flush()
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
        # Creative App sends this on connect; the GS5 answers with a 2c frame or a plain ACK.
        connected = _starts(OP_CONNECT)
        self.connect_reply = self.request(OP_CONNECT, [0x01],
                                          match=lambda r: connected(r) or is_ack_for(r, OP_CONNECT, 0x01))

    # --- lighting (op 3a) --------------------------------------------------------------------------------
    def _set(self, cmd: int, args: list[int] | tuple[int, ...] = ()) -> None:
        for _ in range(2):
            rep = self.request(OP_LIGHTING, [cmd, *args], match=lambda r: is_ack_for(r, OP_LIGHTING, cmd))
            if rep is not None:
                if ack_status(rep) != 0:
                    raise CommandError(f"GS5 rejected lighting command {cmd:02x} (status {ack_status(rep):02x})")
                return
        raise CommandError(f"no reply to lighting command {cmd:02x}")

    def _get(self, cmd: int, args: list[int] | tuple[int, ...] = (), size: int = 1) -> bytes:
        """Query ``cmd``. The reply echoes the command and its args (``2a <slot>`` -> ``2a <slot> <mode>``), so only
        a reply with the same key is accepted. Returns the bytes after ``cmd`` (echoed args included), at least
        ``len(args) + size`` of them."""
        key = bytes([cmd, *args])

        def match(r: bytes) -> bool:
            return (r[:3] == bytes([REPORT_ID, MAGIC, OP_LIGHTING]) and (r[3] | r[4] << 8) >= len(key)
                    and r[5 : 5 + len(key)] == key)

        for _ in range(2):
            rep = self.request(OP_LIGHTING, list(key), match=match)
            if rep is not None:
                value = rep[6 : 5 + (rep[3] | rep[4] << 8)]
                if len(value) < len(args) + size:
                    raise CommandError(f"short reply to lighting query {cmd:02x}: {rep.rstrip(bytes(1)).hex(' ')}")
                return value
        raise CommandError(f"no reply to lighting query {cmd:02x}")

    def lighting_on(self, on: bool = True) -> None:
        self._set(0x25, [1 if on else 0])

    def lighting_is_on(self) -> bool:
        return self._get(0x26)[0] == 1

    def set_brightness(self, percent: int) -> None:
        self._set(0x27, [_level(percent)])

    def brightness(self) -> int:
        return round(self._get(0x28)[0] * 100 / 255)

    def active_slot(self) -> int:
        return self._get(0x2E)[0]

    def slot_mode(self, slot: int) -> int:
        return self._get(0x2A, [slot])[1]

    def set_mode(self, slot: int, mode: str, brightness: int | None = None) -> None:
        """A mode change resets the slot's colours and the global brightness. The brightness is put back, or set
        to ``brightness`` percent when given, so a caller that wants a new level does not set it twice."""
        mid = LIGHTING_MODES[mode]
        level = _level(brightness) if brightness is not None else self._get(0x28)[0]
        for _ in range(3):
            self._set(0x29, [slot, mid])
            self._drain(0.3)  # the GS5 pushes the slot's settings; commands sent now can be lost
            if self.slot_mode(slot) == mid:
                if self._get(0x28)[0] != level:
                    self._set(0x27, [level])
                return
        raise CommandError(f"lighting slot {slot} would not switch to {mode}")

    def activate_slot(self, slot: int) -> None:
        self._set(0x2D, [slot])
        self._drain(0.3)

    def set_colours(self, slot: int, colours: list[str]) -> None:
        self._set(0x2B, [slot, 0x01, 0x01, *_colour_bytes(colours)])

    @_locked
    def static(self, colours: str | list[str], slot: int = 1, brightness: int | None = None) -> None:
        """Show fixed colours, at ``brightness`` percent when given. The slot is always (re)activated and the
        strip turned on afterwards: it can be dark while reporting 'on'."""
        if isinstance(colours, str):
            colours = [colours] * SEGMENTS
        if len(colours) != SEGMENTS:
            raise ValueError(f"rgb needs 1 or {SEGMENTS} colours")
        _colour_bytes(colours)  # validate before touching the device
        if self.slot_mode(slot) != LIGHTING_MODES["static"]:
            self.set_mode(slot, "static", brightness)
        elif brightness is not None:
            self.set_brightness(brightness)
        self.set_colours(slot, colours)
        self.activate_slot(slot)
        self.lighting_on(True)

    def _reassert(self) -> None:
        self.activate_slot(self.active_slot())
        self.lighting_on(True)

    @_locked
    def wake(self) -> None:
        """The strip can go dark (auto-standby) while still reporting 'on'; re-assert it."""
        self.handshake()
        self._reassert()

    # --- Device API ------------------------------------------------------------------------------------
    def _send_frames(self, frames: list[str]) -> None:
        for hx in frames:
            self.send_raw(parse_hex(hx))

    def _sound_mode(self, name: str) -> list[str]:
        if sys.platform != "win32":
            return [f"sound_mode {name!r}: Creative App sound modes can only be switched on Windows; skipped"]
        if self._creative_app is None:
            from .creative_app import CreativeApp

            self._creative_app = CreativeApp()
        try:
            self._creative_app.select(name)
        except DeviceError as e:
            return [f"sound_mode: {e}"]
        return []

    @_locked
    def apply(self, profile: Profile) -> list[str]:
        warnings: list[str] = []
        if profile.sound_mode is not None:
            warnings += self._sound_mode(profile.sound_mode)
        if profile.eq is not None:
            if profile.eq in EQ_PRESETS:
                self._send_frames(EQ_PRESETS[profile.eq])
            else:
                warnings.append(f"eq {profile.eq!r}: the GS5 has no USB command for EQ presets "
                                "(Creative App applies EQ on the PC); use sound_mode instead")
        if profile.superwide is not None:
            if profile.superwide in SUPERWIDE:
                self._send_frames(SUPERWIDE[profile.superwide])
            else:
                warnings.append("superwide: the GS5 has no USB command for SuperWide (Creative App applies it on "
                                "the PC); use a sound_mode with SuperWide on/off instead")
        if profile.frames:
            self._send_frames(profile.frames)
        if profile.lighting is False:
            self.lighting_on(False)
            self._lighting_wanted = False
        elif profile.rgb is not None:
            self.static(profile.rgb, brightness=profile.brightness)  # sets the brightness too, once
            self._lighting_wanted = True
        else:
            if profile.lighting is True:
                self.lighting_on(True)
                self._lighting_wanted = True
            if profile.brightness is not None:
                self.set_brightness(profile.brightness)
        return warnings

    @_locked
    def keepalive(self) -> None:
        """Undo the strip's auto-standby. If the user turned the lighting off (on the bar or in Creative App),
        stop re-asserting it instead of fighting them."""
        if not self._lighting_wanted:
            return
        self.handshake()
        if not self.lighting_is_on():
            self._lighting_wanted = False
            return
        self._reassert()

    @_locked
    def probe(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "device": self.name,
            "usb_id": f"{VENDOR_ID:04x}:{PRODUCT_ID:04x}",
            "hello_reply": self.hello_reply.rstrip(b"\0").hex(" ") if self.hello_reply else None,
            "sound_settings": ("Creative App sound modes (gs5 modes)" if sys.platform == "win32"
                               else "not available on this OS (Creative App is Windows-only)"),
        }
        try:
            info["lighting"] = {
                "on": self.lighting_is_on(),
                "brightness_percent": self.brightness(),
                "active_slot": self.active_slot(),
            }
        except CommandError as e:  # a lost connection (plain DeviceError) propagates so the caller reconnects
            info["lighting"] = f"unavailable: {e}"
        return info


def _starts(op: int) -> Callable[[bytes], bool]:
    prefix = bytes([REPORT_ID, MAGIC, op])
    return lambda r: r.startswith(prefix)
