"""Detect what the user is doing: playing media, foreground app, microphone use."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field


@dataclass
class Activity:
    media_playing: bool = False
    # friendly name plus the raw player id, e.g. "Spotify (Spotify.exe)", "Firefox (308046B0AF4A39CB)",
    # "Chrome", "Spotify (com.spotify.client)", "VLC"; unknown ids are kept as they are
    media_app: str = ""
    media_title: str = ""
    media_artist: str = ""
    media_type: str = ""         # "music", "video" or "" when the player does not say
    foreground_app: str = ""     # process / application name of the focused window
    foreground_title: str = ""
    fullscreen: bool = False
    mic_in_use: bool = False
    mic_apps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


class Detector:
    def read(self) -> Activity:
        """Never raises: anything that cannot be read is left empty."""
        return Activity()

    def close(self) -> None:
        pass


def get_detector() -> Detector:
    if sys.platform == "win32":
        from .windows import WindowsDetector

        return WindowsDetector()
    if sys.platform == "darwin":
        from .macos import MacDetector

        return MacDetector()
    if sys.platform.startswith("linux"):
        from .linux import LinuxDetector

        return LinuxDetector()
    return Detector()
