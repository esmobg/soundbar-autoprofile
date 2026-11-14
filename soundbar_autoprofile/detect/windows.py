"""Windows: media sessions (GlobalSystemMediaTransportControls), focused window, microphone use."""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import winreg
from ctypes import wintypes

import psutil

from . import Activity, Detector

log = logging.getLogger(__name__)

_PLAYING = 4          # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
_MEDIA_TYPES = {1: "music", 2: "video"}   # Windows.Media.MediaPlaybackType

_MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


class WindowsDetector(Detector):
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._manager = None
        self._user32 = ctypes.windll.user32

    def close(self) -> None:
        self._loop.close()

    def read(self) -> Activity:
        a = Activity()
        for part in (self._read_media, self._read_foreground, self._read_mic):
            try:
                part(a)
            except Exception as e:  # never let detection kill the daemon
                log.debug("detection step %s failed: %s", part.__name__, e)
        return a

    # --- media ------------------------------------------------------------------------------------------
    def _read_media(self, a: Activity) -> None:
        self._loop.run_until_complete(self._media(a))

    async def _media(self, a: Activity) -> None:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

        if self._manager is None:
            self._manager = await Manager.request_async()
        sessions = list(self._manager.get_sessions())
        current = self._manager.get_current_session()
        if current is not None:
            sessions.sort(key=lambda s: s.source_app_user_model_id != current.source_app_user_model_id)
        for s in sessions:
            info = s.get_playback_info()
            if info is None or int(info.playback_status) != _PLAYING:
                continue
            a.media_playing = True
            a.media_app = s.source_app_user_model_id or ""
            ptype = info.playback_type
            try:
                a.media_type = _MEDIA_TYPES.get(int(ptype), "") if ptype is not None else ""
            except (TypeError, ValueError):
                a.media_type = ""
            props = await s.try_get_media_properties_async()
            if props is not None:
                a.media_title = props.title or ""
                a.media_artist = props.artist or ""
                if not a.media_type and props.playback_type is not None:
                    try:
                        a.media_type = _MEDIA_TYPES.get(int(props.playback_type), "")
                    except (TypeError, ValueError):
                        pass
            return

    # --- focused window ---------------------------------------------------------------------------------
    def _read_foreground(self, a: Activity) -> None:
        u = self._user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        a.foreground_title = buf.value
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            a.foreground_app = psutil.Process(pid.value).name()
        except psutil.Error:
            pass
        rect = _RECT()
        if u.GetWindowRect(hwnd, ctypes.byref(rect)):
            mon = u.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
            if mon and u.GetMonitorInfoW(mon, ctypes.byref(mi)):
                m = mi.rcMonitor
                a.fullscreen = (rect.left <= m.left and rect.top <= m.top
                                and rect.right >= m.right and rect.bottom >= m.bottom)
        # the desktop / shell window covers the screen too
        if a.foreground_app.lower() == "explorer.exe":
            a.fullscreen = False

    # --- microphone -------------------------------------------------------------------------------------
    def _read_mic(self, a: Activity) -> None:
        apps: list[str] = []
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MIC_KEY)
        except OSError:
            return
        with root:
            for name in _subkeys(root):
                with winreg.OpenKey(root, name) as k:
                    if name == "NonPackaged":
                        for exe in _subkeys(k):
                            with winreg.OpenKey(k, exe) as ek:
                                if _in_use(ek):
                                    apps.append(os.path.basename(exe.replace("#", "\\")))
                    elif _in_use(k):
                        apps.append(name)
        a.mic_apps = apps
        a.mic_in_use = bool(apps)


def _subkeys(key) -> list[str]:
    out, i = [], 0
    while True:
        try:
            out.append(winreg.EnumKey(key, i))
        except OSError:
            return out
        i += 1


def _in_use(key) -> bool:
    try:
        stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
        start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
    except OSError:
        return False
    return stop == 0 and start != 0
