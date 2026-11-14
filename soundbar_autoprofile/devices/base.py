"""What every supported soundbar driver provides."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..protocol import REPORT_ID, REPORT_SIZE, parse_hex


class DeviceError(OSError):
    """The soundbar is missing, unplugged, or cannot be opened (the daemon reconnects)."""


class CommandError(DeviceError):
    """The soundbar is connected but refused or ignored one command (the daemon does not reconnect)."""


@dataclass
class Profile:
    """Settings to put on the soundbar. ``None`` means "leave as it is"."""

    name: str
    sound_mode: str | None = None               # Creative App Sound Mode (EQ + SuperWide + effects), Windows
    eq: str | None = None
    superwide: bool | None = None
    rgb: str | list[str] | None = None          # one RRGGBB for the whole strip, or one per segment
    brightness: int | None = None               # lighting brightness, 0-100 %
    lighting: bool | None = None                # False turns the strip off
    frames: list[str] = field(default_factory=list)   # raw hex frames, sent as-is (for new/unknown commands)

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any] | None) -> Profile:
        """Build a profile from its YAML mapping, rejecting values the soundbar could not use.

        The checks catch YAML surprises at load time: an unquoted colour such as ``112233`` is read as a number
        (``001100`` even as an octal one), and ``brightness: 50%`` is text.
        """
        if d is not None and not isinstance(d, dict):
            raise ValueError(f"profile {name!r}: needs a mapping of settings, got {d!r}")
        d = {k: v for k, v in (d or {}).items() if v is not None}
        known = {"sound_mode", "eq", "superwide", "rgb", "brightness", "lighting", "frames"}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"profile {name!r}: unknown setting(s) {', '.join(sorted(map(str, unknown)))}; "
                             f"valid: {', '.join(sorted(known))}")
        where = f"profile {name!r}"
        for key in ("sound_mode", "eq"):
            if key in d and (not isinstance(d[key], str) or not d[key].strip()):
                raise ValueError(f"{where}: {key} must be a name (text), got {d[key]!r}")
        for key in ("superwide", "lighting"):
            if key in d and not isinstance(d[key], bool):
                raise ValueError(f"{where}: {key} must be true or false, got {d[key]!r}")
        if "rgb" in d:
            _check_rgb(where, d["rgb"])
        if "brightness" in d:
            b = d["brightness"]
            if isinstance(b, bool) or not isinstance(b, (int, float)) or not 0 <= b <= 100:
                raise ValueError(f"{where}: brightness must be a number from 0 to 100 (no %), got {b!r}")
            d["brightness"] = round(b)
        if "frames" in d:
            frames = d["frames"] if isinstance(d["frames"], list) else [d["frames"]]
            for f in frames:
                _check_frame(where, f)
            d["frames"] = frames
        return cls(name=name, **d)


def _check_rgb(where: str, value: Any) -> None:
    colours = value if isinstance(value, list) else [value]
    if not colours:
        raise ValueError(f"{where}: rgb needs at least one colour")
    for c in colours:
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            raise ValueError(f"{where}: rgb colour {c!r} was read as a number; quote it, e.g. rgb: \"112233\"")
        if not isinstance(c, str):
            raise ValueError(f"{where}: rgb colour must be a quoted \"RRGGBB\", got {c!r}")
        hex_part = c.strip().removeprefix("#")
        if len(hex_part) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in hex_part):
            raise ValueError(f"{where}: rgb colour must be RRGGBB (6 hex digits, optional #), got {c!r}")


def _check_frame(where: str, frame: Any) -> None:
    if not isinstance(frame, str):
        raise ValueError(f"{where}: frames must be quoted hex strings such as \"05 6a 2c 01 00 01\", got {frame!r}")
    try:
        raw = parse_hex(frame)
    except ValueError:
        raise ValueError(f"{where}: frame {frame!r} is not valid hex") from None
    if raw[:1] != bytes([REPORT_ID]):
        raise ValueError(f"{where}: frame {frame!r} must start with the report id {REPORT_ID:02x}")
    if len(raw) > REPORT_SIZE:
        raise ValueError(f"{where}: frame {frame!r} is {len(raw)} bytes, the limit is {REPORT_SIZE}")


class Device(ABC):
    """One open soundbar."""

    name = "device"

    @abstractmethod
    def apply(self, profile: Profile) -> list[str]:
        """Put the profile's settings on the device. Returns warnings for settings it could not apply."""

    @abstractmethod
    def probe(self) -> dict[str, Any]:
        """Read-only information about the device."""

    def keepalive(self) -> None:
        """Called periodically by the daemon. Drivers can use it to undo the device's own standby quirks."""

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class DryRunDevice(Device):
    """Prints what would be sent instead of talking to hardware."""

    name = "dry-run"

    def __init__(self, log=print):
        self.log = log
        self.applied: list[Profile] = []

    def apply(self, profile: Profile) -> list[str]:
        self.applied.append(profile)
        self.log(f"[dry-run] would apply profile {profile.name!r}: {profile}")
        return []

    def probe(self) -> dict[str, Any]:
        return {"device": "dry-run"}
