"""macOS: frontmost application, full-screen, and what is playing.

Playing media, in this order:

1. ``media-control`` (https://github.com/ungive/media-control, ``brew install media-control``) if installed: the
   system-wide "Now Playing" of any app, browsers included. It keeps working on macOS 15.4+, where Apple closed
   the MediaRemote framework to other apps.
2. ``nowplaying-cli`` if installed (title / artist only; broken on macOS 15.4+).
3. AppleScript to Spotify and Music, only when they are already running (players are never launched).

Full-screen needs ``pyobjc-framework-Quartz`` (window bounds); without it ``fullscreen`` stays False.
Microphone use is not detected: macOS has no cheap, permission-free way to ask which app records.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

import psutil

from . import Activity, Detector
from .parsing import NOWPLAYING_CLI_PROPS, mac_window_is_fullscreen, parse_media_control, parse_nowplaying_cli

log = logging.getLogger(__name__)

# app name -> AppleScript that prints "playing<TAB>title<TAB>artist" (only run when the app is open)
_PLAYERS = {
    "Spotify": 'tell application "Spotify" to if player state is playing then '
               'return "playing" & tab & (name of current track) & tab & (artist of current track)',
    "Music": 'tell application "Music" to if player state is playing then '
             'return "playing" & tab & (name of current track) & tab & (artist of current track)',
}


def _run(cmd: list[str], timeout: float = 3) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("%s failed: %r", cmd[0], e)
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _osascript(script: str) -> str:
    return _run(["osascript", "-e", script])


def parse_osascript_player(app: str, out: str) -> dict[str, Any] | None:
    if not out.startswith("playing"):
        return None
    parts = out.split("\t") + ["", ""]
    return {"playing": True, "app": app, "title": parts[1], "artist": parts[2], "type": "music"}


class MacDetector(Detector):
    def __init__(self) -> None:
        self._media_control = shutil.which("media-control")
        self._nowplaying_cli = shutil.which("nowplaying-cli")

    def read(self) -> Activity:
        a = Activity()
        for part in (self._frontmost, self._media):
            try:
                part(a)
            except Exception as e:  # never let detection kill the daemon
                log.debug("detection step %s failed: %r", part.__name__, e)
        return a

    # --- focused app ------------------------------------------------------------------------------------
    def _frontmost(self, a: Activity) -> None:
        try:
            from AppKit import NSWorkspace
        except ImportError:
            a.foreground_app = _osascript(
                'tell application "System Events" to get name of first process whose frontmost is true')
            return
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return
        a.foreground_app = str(app.localizedName() or "")
        try:
            a.fullscreen = _fullscreen(int(app.processIdentifier()))
        except Exception as e:
            log.debug("full-screen check failed: %r", e)

    # --- media ------------------------------------------------------------------------------------------
    def _media(self, a: Activity) -> None:
        # the first source that gives an answer decides, "nothing is playing" included
        for source in (self._from_media_control, self._from_nowplaying_cli, self._from_players):
            m = source()
            if m is None:
                continue
            if m.get("playing"):
                a.media_playing = True
                a.media_app, a.media_title, a.media_artist, a.media_type = (
                    m["app"], m["title"], m["artist"], m["type"])
            return

    def _from_media_control(self) -> dict[str, Any] | None:
        if not self._media_control:
            return None
        out = _run([self._media_control, "get"])
        if out == "null":        # media-control works, nothing is loaded
            return {"playing": False}
        return parse_media_control(out)

    def _from_nowplaying_cli(self) -> dict[str, Any] | None:
        if not self._nowplaying_cli:
            return None
        return parse_nowplaying_cli(_run([self._nowplaying_cli, "get", *NOWPLAYING_CLI_PROPS]))

    def _from_players(self) -> dict[str, Any] | None:
        running = {p.info["name"] for p in psutil.process_iter(["name"])}
        for app, script in _PLAYERS.items():
            if app not in running:
                continue  # never launch a player just to ask it
            m = parse_osascript_player(app, _osascript(script))
            if m:
                return m
        return None


def _fullscreen(pid: int) -> bool:
    try:
        import Quartz
        from AppKit import NSScreen
    except ImportError:
        return False
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    screens = [(s.frame().size.width, s.frame().size.height) for s in NSScreen.screens()]
    return mac_window_is_fullscreen(
        [{"kCGWindowOwnerPID": int(w.get("kCGWindowOwnerPID", -1)), "kCGWindowLayer": int(w.get("kCGWindowLayer", 0)),
          "kCGWindowBounds": dict(w.get("kCGWindowBounds") or {})} for w in windows or []],
        pid, screens)
