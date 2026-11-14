"""Linux: MPRIS players via `playerctl`, focused window via `xdotool` (X11), microphone via `pactl`.

Wayland compositors do not expose the focused window to other programs, so there only media rules apply.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

from . import Activity, Detector

log = logging.getLogger(__name__)


def _run(*cmd: str) -> str:
    if not shutil.which(cmd[0]):
        return ""
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
    return r.stdout.strip() if r.returncode == 0 else ""


class LinuxDetector(Detector):
    def read(self) -> Activity:
        a = Activity()
        for part in (self._media, self._foreground, self._mic):
            try:
                part(a)
            except Exception as e:
                log.debug("detection step %s failed: %s", part.__name__, e)
        return a

    def _media(self, a: Activity) -> None:
        out = _run("playerctl", "-a", "metadata", "--format",
                   "{{playerName}}\t{{status}}\t{{title}}\t{{artist}}\t{{mpris:trackid}}")
        for line in out.splitlines():
            name, status, title, artist, trackid = (line.split("\t") + [""] * 5)[:5]
            if status != "Playing":
                continue
            a.media_playing, a.media_app, a.media_title, a.media_artist = True, name, title, artist
            # browsers and video players expose video tracks without an artist
            a.media_type = "music" if artist else ""
            return

    def _foreground(self, a: Activity) -> None:
        wid = _run("xdotool", "getactivewindow")
        if not wid:
            return
        a.foreground_title = _run("xdotool", "getwindowname", wid)
        pid = _run("xdotool", "getwindowpid", wid)
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm") as f:
                    a.foreground_app = f.read().strip()
            except OSError:
                pass

    def _mic(self, a: Activity) -> None:
        out = _run("pactl", "list", "source-outputs")
        apps = [line.split("=", 1)[1].strip().strip('"') for line in out.splitlines()
                if line.strip().startswith("application.name")]
        a.mic_apps = apps
        a.mic_in_use = bool(apps)
