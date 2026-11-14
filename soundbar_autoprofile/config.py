"""Load the YAML configuration (user file, or the bundled defaults)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

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


def parse(text: str, source: str = "<string>") -> Config:
    raw = yaml.safe_load(text) or {}
    profiles = {name: Profile.from_dict(name, d) for name, d in (raw.get("profiles") or {}).items()}
    rules = [Rule.from_dict(r) for r in (raw.get("rules") or [])]
    cfg = Config(
        device=raw.get("device", "gs5"),
        hold_seconds=float(raw.get("hold_seconds", 3)),
        media_grace_seconds=float(raw.get("media_grace_seconds", 15)),
        poll_seconds=float(raw.get("poll_seconds", 1)),
        keepalive_seconds=float(raw.get("keepalive_seconds", 120)),
        default_profile=raw.get("default_profile", "default"),
        profiles=profiles,
        rules=rules,
        source=source,
    )
    missing = {r.profile for r in rules} | {cfg.default_profile}
    missing -= set(profiles)
    if missing:
        raise ValueError(f"{source}: rules refer to undefined profile(s): {', '.join(sorted(missing))}")
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
