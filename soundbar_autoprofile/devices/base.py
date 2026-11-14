"""What every supported soundbar driver provides."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class DeviceError(OSError):
    """The soundbar is missing, refused a command, or did not answer."""


@dataclass
class Profile:
    """Settings to put on the soundbar. ``None`` means "leave as it is"."""

    name: str
    eq: str | None = None
    superwide: bool | None = None
    rgb: str | list[str] | None = None          # one RRGGBB for the whole strip, or one per segment
    brightness: int | None = None               # lighting brightness, 0-100 %
    lighting: bool | None = None                # False turns the strip off
    frames: list[str] = field(default_factory=list)   # raw hex frames, sent as-is (for new/unknown commands)

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any] | None) -> Profile:
        d = dict(d or {})
        known = {"eq", "superwide", "rgb", "brightness", "lighting", "frames"}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"profile {name!r}: unknown setting(s) {', '.join(sorted(unknown))}")
        return cls(name=name, **{k: d[k] for k in known if k in d and d[k] is not None})


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
