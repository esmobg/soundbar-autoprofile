"""Linux: MPRIS players via ``playerctl``, focused window and full-screen, microphone via ``pactl``.

Focused window:

* X11: ``xdotool`` (window, title, pid) and ``xprop`` (``_NET_WM_STATE_FULLSCREEN``).
* Wayland has no common way to ask for the focused window; supported compositors: Hyprland (``hyprctl``), sway
  (``swaymsg``) and KDE Plasma (``kdotool``, no full-screen info). On GNOME and others only media and microphone
  rules apply.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from . import Activity, Detector
from .parsing import (
    PLAYERCTL_FORMAT,
    parse_hyprctl_activewindow,
    parse_pactl_monitor_sources,
    parse_pactl_source_outputs,
    parse_playerctl,
    parse_sway_tree,
    xprop_is_fullscreen,
)

log = logging.getLogger(__name__)


def _run(*cmd: str) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("%s failed: %r", cmd[0], e)
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _comm(pid: int | str | None) -> str:
    """Process name of a pid ("firefox", "mpv"), or ""."""
    if pid is None or not str(pid).isdigit():
        return ""
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


class LinuxDetector(Detector):
    def read(self) -> Activity:
        a = Activity()
        for part in (self._media, self._foreground, self._mic):
            try:
                part(a)
            except Exception as e:  # never let detection kill the daemon
                log.debug("detection step %s failed: %r", part.__name__, e)
        return a

    # --- media ------------------------------------------------------------------------------------------
    def _media(self, a: Activity) -> None:
        m = parse_playerctl(_run("playerctl", "-a", "metadata", "--format", PLAYERCTL_FORMAT))
        if m:
            a.media_playing = True
            a.media_app, a.media_title, a.media_artist, a.media_type = m["app"], m["title"], m["artist"], m["type"]

    # --- focused window ---------------------------------------------------------------------------------
    def _foreground(self, a: Activity) -> None:
        env = os.environ
        if env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland":
            # xdotool would only see XWayland windows here, so it is not used
            w = None
            if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
                w = parse_hyprctl_activewindow(_run("hyprctl", "activewindow", "-j"))
            if w is None and env.get("SWAYSOCK"):
                w = parse_sway_tree(_run("swaymsg", "-t", "get_tree"))
            if w is None and ("KDE" in env.get("XDG_CURRENT_DESKTOP", "").upper() or shutil.which("kdotool")):
                w = _kdotool_window()
        else:
            w = _x11_window()
        if not w:
            return
        a.foreground_app = _comm(w.get("pid")) or w.get("app", "")
        a.foreground_title = w.get("title", "")
        a.fullscreen = bool(w.get("fullscreen"))

    # --- microphone -------------------------------------------------------------------------------------
    def _mic(self, a: Activity) -> None:
        out = _run("pactl", "list", "source-outputs")
        if not out:
            return
        monitors = parse_pactl_monitor_sources(_run("pactl", "list", "short", "sources"))
        a.mic_apps = parse_pactl_source_outputs(out, monitors)
        a.mic_in_use = bool(a.mic_apps)


def _x11_window() -> dict | None:
    wid = _run("xdotool", "getactivewindow")
    if not wid:
        return None
    return {"title": _run("xdotool", "getwindowname", wid), "pid": _run("xdotool", "getwindowpid", wid),
            "app": "", "fullscreen": xprop_is_fullscreen(_run("xprop", "-id", wid, "_NET_WM_STATE"))}


def _kdotool_window() -> dict | None:
    wid = _run("kdotool", "getactivewindow")
    if not wid:
        return None
    return {"title": _run("kdotool", "getwindowname", wid), "pid": _run("kdotool", "getwindowpid", wid),
            "app": _run("kdotool", "getwindowclassname", wid), "fullscreen": False}
