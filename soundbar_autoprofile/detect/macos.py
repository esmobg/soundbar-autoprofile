"""macOS: frontmost application, and what Music / Spotify are playing (via AppleScript).

macOS 15.4+ no longer lets third-party tools read the system-wide "Now Playing" info, so browser media is
only seen through the frontmost app and window rules.
"""

from __future__ import annotations

import logging
import subprocess

import psutil

from . import Activity, Detector

log = logging.getLogger(__name__)

# app name -> AppleScript that prints "playing<TAB>title<TAB>artist" (only run when the app is open)
_PLAYERS = {
    "Spotify": 'tell application "Spotify" to if player state is playing then '
               'return "playing" & tab & (name of current track) & tab & (artist of current track)',
    "Music": 'tell application "Music" to if player state is playing then '
             'return "playing" & tab & (name of current track) & tab & (artist of current track)',
}


def _osascript(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
    return r.stdout.strip()


class MacDetector(Detector):
    def read(self) -> Activity:
        a = Activity()
        try:
            self._frontmost(a)
        except Exception as e:
            log.debug("frontmost app failed: %s", e)
        try:
            self._players(a)
        except Exception as e:
            log.debug("player query failed: %s", e)
        return a

    def _frontmost(self, a: Activity) -> None:
        try:
            from AppKit import NSWorkspace

            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            a.foreground_app = str(app.localizedName() or "")
        except ImportError:
            a.foreground_app = _osascript(
                'tell application "System Events" to get name of first process whose frontmost is true')

    def _players(self, a: Activity) -> None:
        running = {p.info["name"] for p in psutil.process_iter(["name"])}
        for app, script in _PLAYERS.items():
            if app not in running:
                continue  # never launch a player just to ask it
            out = _osascript(script)
            if out.startswith("playing"):
                parts = out.split("\t") + ["", ""]
                a.media_playing, a.media_app, a.media_type = True, app, "music"
                a.media_title, a.media_artist = parts[1], parts[2]
                return
