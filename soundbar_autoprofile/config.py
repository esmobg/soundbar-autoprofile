"""Load the YAML configuration (user file, or the bundled defaults)."""

from __future__ import annotations

import difflib
import os
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .devices import DRIVERS
from .devices.base import Profile
from .rules import Rule

APP = "soundbar-autoprofile"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP


def config_path() -> Path:
    return Path(os.environ.get("SOUNDBAR_AUTOPROFILE_CONFIG", config_dir() / "config.yaml"))


def default_config_text() -> str:
    return resources.files(__package__).joinpath("default_config.yaml").read_text(encoding="utf-8")


@dataclass
class Config:
    device: str = "gs5"
    hold_seconds: float = 3.0
    media_grace_seconds: float = 15.0
    poll_seconds: float = 1.0
    keepalive_seconds: float = 120.0
    default_profile: str = "default"
    profiles: dict[str, Profile] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    source: str = "built-in defaults"
    warnings: list[str] = field(default_factory=list)   # non-fatal problems (e.g. unknown keys), for `config check`


TOP_LEVEL_KEYS = {"device", "hold_seconds", "media_grace_seconds", "poll_seconds", "keepalive_seconds",
                  "default_profile", "profiles", "rules"}


def _seconds(raw: dict[str, Any], key: str, default: float, source: str, positive: bool = False) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{source}: {key} must be a number of seconds, got {value!r}")
    if positive and value <= 0:
        raise ValueError(f"{source}: {key} must be more than 0, got {value!r}")
    if value < 0:
        raise ValueError(f"{source}: {key} must be 0 or more, got {value!r}")
    return float(value)


def parse(text: str, source: str = "<string>") -> Config:
    """Parse and validate a config. Raises ValueError (naming ``source``) for anything the daemon could not use."""
    raw = yaml.safe_load(text)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: the config must be a YAML mapping (device:, profiles:, rules:, ...), "
                         f"got {type(raw).__name__}")
    warnings = []
    for k in raw:
        if k not in TOP_LEVEL_KEYS:
            close = difflib.get_close_matches(str(k), TOP_LEVEL_KEYS, n=1)
            hint = f"did you mean {close[0]!r}?" if close else f"valid: {', '.join(sorted(TOP_LEVEL_KEYS))}"
            warnings.append(f"{source}: unknown setting {k!r} is ignored; {hint}")

    device = raw.get("device", "gs5")
    if device not in DRIVERS:
        raise ValueError(f"{source}: unknown device {device!r}; supported: {', '.join(DRIVERS)}")
    default_profile = raw.get("default_profile", "default")
    if not isinstance(default_profile, str):
        raise ValueError(f"{source}: default_profile must be a profile name, got {default_profile!r}")

    raw_profiles = raw.get("profiles") or {}
    if not isinstance(raw_profiles, dict):
        raise ValueError(f"{source}: profiles must be a mapping of name -> settings")
    raw_rules = raw.get("rules") or []
    if not isinstance(raw_rules, list):
        raise ValueError(f"{source}: rules must be a list")
    try:
        profiles = {str(name): Profile.from_dict(str(name), d) for name, d in raw_profiles.items()}
        rules = [Rule.from_dict(r) for r in raw_rules]
    except ValueError as e:
        raise ValueError(f"{source}: {e}") from None
    if device == "gs5":
        from .devices.gs5 import SEGMENTS

        for p in profiles.values():
            if isinstance(p.rgb, list) and len(p.rgb) not in (1, SEGMENTS):
                raise ValueError(f"{source}: profile {p.name!r}: rgb needs 1 colour or {SEGMENTS} (one per "
                                 f"segment, left to right), got {len(p.rgb)}")

    cfg = Config(
        device=device,
        hold_seconds=_seconds(raw, "hold_seconds", 3, source),
        media_grace_seconds=_seconds(raw, "media_grace_seconds", 15, source),
        poll_seconds=_seconds(raw, "poll_seconds", 1, source, positive=True),
        keepalive_seconds=_seconds(raw, "keepalive_seconds", 120, source),
        default_profile=default_profile,
        profiles=profiles,
        rules=rules,
        source=source,
        warnings=warnings,
    )
    defined = set(profiles)
    if default_profile not in defined:
        raise ValueError(f"{source}: default_profile refers to undefined profile {default_profile!r}; "
                         f"defined: {', '.join(sorted(defined)) or 'none'}")
    missing = {r.profile for r in rules} - defined
    if missing:
        raise ValueError(f"{source}: rules refer to undefined profile(s): {', '.join(sorted(missing))}; "
                         f"defined: {', '.join(sorted(defined)) or 'none'}")
    return cfg


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if path.exists():
        return parse(path.read_text(encoding="utf-8"), str(path))
    return parse(default_config_text(), "built-in defaults")


def write_default(path: Path | None = None, overwrite: bool = False) -> Path:
    path = path or config_path()
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_text(), encoding="utf-8")
    return path
