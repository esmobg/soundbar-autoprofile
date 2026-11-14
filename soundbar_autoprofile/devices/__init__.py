"""Soundbar drivers. Add a new model by implementing ``Device`` and registering it in ``DRIVERS``."""

from __future__ import annotations

from .base import Device, DeviceError, DryRunDevice, Profile

DRIVERS = ("gs5",)


def open_device(name: str = "gs5", dry_run: bool = False, path: str | None = None) -> Device:
    if dry_run:
        return DryRunDevice()
    if name == "gs5":
        from .gs5 import GS5

        return GS5.open(path)
    raise DeviceError(f"unknown device {name!r}; supported: {', '.join(DRIVERS)}")


__all__ = ["Device", "DeviceError", "DryRunDevice", "Profile", "open_device", "DRIVERS"]
