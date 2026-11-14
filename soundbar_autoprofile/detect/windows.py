"""Windows: media sessions (GlobalSystemMediaTransportControls), focused window, microphone use.

The module imports on any OS (``winreg`` / ``ctypes.WinDLL`` / ``winrt`` are only touched when reading), so its
logic can be tested with fakes elsewhere.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import time
from typing import Any

import psutil

from . import Activity, Detector
from .parsing import is_windows_shell, media_app_label, mic_nonpackaged_name

try:
    import winreg
except ImportError:  # not Windows
    winreg = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

_PLAYING = 4          # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
_MEDIA_TYPES = {1: "music", 2: "video"}   # Windows.Media.MediaPlaybackType
_MEDIA_TIMEOUT = 3.0  # seconds; a hung app must not stall the daemon

_MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
# vendor keys whose <Product>\TaskBarIDs map install folders to the hashed AUMIDs Firefox & co. use
_TASKBAR_ID_VENDORS = ("Mozilla", "LibreWolf", "Waterfox")
_HASH_REFRESH = 300.0

_QUNS_RUNNING_D3D_FULL_SCREEN = 3
_MONITOR_DEFAULTTONEAREST = 2


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", ctypes.c_uint32)]


def _load_user32() -> Any:
    """A private user32 handle with proper handle types (64-bit HWNDs are not truncated)."""
    u = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    vp = ctypes.c_void_p
    u.GetForegroundWindow.restype = vp
    u.GetForegroundWindow.argtypes = []
    u.GetWindowTextLengthW.argtypes = [vp]
    u.GetWindowTextW.argtypes = [vp, ctypes.c_wchar_p, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [vp, ctypes.POINTER(ctypes.c_uint32)]
    u.GetWindowThreadProcessId.restype = ctypes.c_uint32
    u.GetWindowRect.argtypes = [vp, ctypes.POINTER(_RECT)]
    u.MonitorFromWindow.argtypes = [vp, ctypes.c_uint32]
    u.MonitorFromWindow.restype = vp
    u.GetMonitorInfoW.argtypes = [vp, ctypes.POINTER(_MONITORINFO)]
    return u


class WindowsDetector(Detector):
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager = None
        self._user32: Any = None
        self._hash_names: dict[str, str] = {}
        self._hash_loaded_at = float("-inf")

    def close(self) -> None:
        self._manager = None
        if self._loop is not None and not self._loop.is_closed():
            self._loop.close()
        self._loop = None

    def read(self) -> Activity:
        a = Activity()
        for part in (self._read_media, self._read_foreground, self._read_mic):
            try:
                part(a)
            except Exception as e:  # never let detection kill the daemon
                log.debug("detection step %s failed: %r", part.__name__, e)
        return a

    # --- media ------------------------------------------------------------------------------------------
    def _read_media(self, a: Activity) -> None:
        result = None
        for attempt in (1, 2):
            try:
                result = self._run(self._media())
                break
            except Exception as e:
                # e.g. explorer restarted / RPC server gone: the cached manager is dead, ask for a new one
                log.debug("media sessions failed (attempt %d): %r", attempt, e)
                self._manager = None
                if self._loop is not None and (self._loop.is_closed() or self._loop.is_running()):
                    self._loop = None
        if not result:
            return
        app_id, title, artist, mtype = result
        a.media_playing = True
        a.media_app = media_app_label(app_id, self._mozilla_hash_names(app_id))
        a.media_title, a.media_artist, a.media_type = title, artist, mtype

    def _run(self, coro):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(asyncio.wait_for(coro, _MEDIA_TIMEOUT))

    async def _request_manager(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

        return await Manager.request_async()

    async def _media(self) -> tuple[str, str, str, str] | None:
        """(app id, title, artist, type) of the playing session, the system's "current" one first."""
        if self._manager is None:
            self._manager = await self._request_manager()
        manager = self._manager
        sessions = list(manager.get_sessions())
        current = manager.get_current_session()
        if current is not None:
            cur_id = current.source_app_user_model_id
            sessions.sort(key=lambda s: s.source_app_user_model_id != cur_id)
        for s in sessions:
            info = s.get_playback_info()
            if info is None or _int(info.playback_status) != _PLAYING:
                continue
            mtype = _media_type(info)
            title = artist = ""
            try:
                props = await s.try_get_media_properties_async()
            except Exception as e:  # some apps fail this while switching tracks
                log.debug("media properties of %s failed: %r", s.source_app_user_model_id, e)
                props = None
            if props is not None:
                title, artist = props.title or "", props.artist or ""
                if not mtype:
                    mtype = _media_type(props)
            return s.source_app_user_model_id or "", title, artist, mtype
        return None

    def _mozilla_hash_names(self, app_id: str) -> dict[str, str]:
        """Hashed AUMID -> product ("Firefox", "Thunderbird", ...) from ``<Vendor>\\<Product>\\TaskBarIDs``."""
        if not (len(app_id) == 16 and all(c in "0123456789abcdefABCDEF" for c in app_id)):
            return self._hash_names
        now = time.monotonic()
        if app_id.upper() not in self._hash_names and now - self._hash_loaded_at > _HASH_REFRESH:
            self._hash_loaded_at = now
            try:
                self._hash_names = read_taskbar_ids()
            except Exception as e:
                log.debug("reading TaskBarIDs failed: %r", e)
        return self._hash_names

    # --- focused window ---------------------------------------------------------------------------------
    def _read_foreground(self, a: Activity) -> None:
        if self._user32 is None:
            self._user32 = _load_user32()
        u = self._user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        a.foreground_title = buf.value
        pid = _window_pid(u, hwnd)
        name = _process_name(pid)
        if name.lower() == "applicationframehost.exe":   # Store apps: the real app owns a child window
            child = _store_app_pid(u, hwnd, pid)
            if child:
                name = _process_name(child) or name
        a.foreground_app = name
        a.fullscreen = _covers_monitor(u, hwnd) or _d3d_fullscreen()
        if is_windows_shell(name):   # the desktop, lock screen and start menu cover the screen too
            a.fullscreen = False

    # --- microphone -------------------------------------------------------------------------------------
    def _read_mic(self, a: Activity) -> None:
        a.mic_apps = read_mic_apps()
        a.mic_in_use = bool(a.mic_apps)


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _media_type(obj: Any) -> str:
    """Media type ("music", "video" or "") from ``obj.playback_type``.

    Reading it builds a ``winrt.windows.media`` enum (from the winrt-Windows.Media package), so a missing projection
    or an odd app must only lose the type, never the session's title and artist."""
    try:
        return _MEDIA_TYPES.get(_int(obj.playback_type), "")
    except Exception as e:
        log.debug("playback_type unavailable: %r", e)
        return ""


def _window_pid(u, hwnd) -> int:
    pid = ctypes.c_uint32()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return ""


def _store_app_pid(u, hwnd, host_pid: int) -> int:
    found: list[int] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)  # type: ignore[attr-defined]

    def cb(child, _lparam):
        p = _window_pid(u, child)
        if p and p != host_pid:
            found.append(p)
            return False
        return True

    u.EnumChildWindows(ctypes.c_void_p(hwnd), proto(cb), None)
    return found[0] if found else 0


def _covers_monitor(u, hwnd) -> bool:
    rect = _RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    mon = u.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    if not mon or not u.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return False
    m = mi.rcMonitor
    return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom


def _d3d_fullscreen() -> bool:
    """Exclusive full-screen Direct3D (older games), which the window rectangle does not always show."""
    try:
        state = ctypes.c_int()
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
        return state.value == _QUNS_RUNNING_D3D_FULL_SCREEN
    except (AttributeError, OSError):
        return False


# --- registry ----------------------------------------------------------------------------------------------
def _subkeys(key) -> list[str]:
    out, i = [], 0
    while True:
        try:
            out.append(winreg.EnumKey(key, i))
        except OSError:
            return out
        i += 1


def _values(key) -> list[tuple[str, Any]]:
    out, i = [], 0
    while True:
        try:
            name, data, _ = winreg.EnumValue(key, i)
        except OSError:
            return out
        out.append((name, data))
        i += 1


def _in_use(key) -> bool:
    try:
        stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
        start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
    except OSError:
        return False
    return stop == 0 and start != 0


def read_mic_apps() -> list[str]:
    """Apps that started using the microphone and have not stopped. Can include apps that just hold it open."""
    if winreg is None:
        return []
    apps: list[str] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MIC_KEY)
    except OSError:
        return apps
    with root:
        for name in _subkeys(root):
            try:
                with winreg.OpenKey(root, name) as k:
                    if name == "NonPackaged":
                        for exe in _subkeys(k):
                            with winreg.OpenKey(k, exe) as ek:
                                if _in_use(ek):
                                    apps.append(mic_nonpackaged_name(exe))
                    elif _in_use(k):
                        apps.append(name)
            except OSError:
                continue
    return apps


def read_taskbar_ids() -> dict[str, str]:
    """{HASH: product} from ``Software\\<Vendor>\\<Product>\\TaskBarIDs`` (HKLM and HKCU)."""
    if winreg is None:
        return {}
    out: dict[str, str] = {}
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for vendor in _TASKBAR_ID_VENDORS:
            try:
                vk = winreg.OpenKey(hive, rf"Software\{vendor}")
            except OSError:
                continue
            with vk:
                for product in _subkeys(vk):
                    try:
                        with winreg.OpenKey(vk, rf"{product}\TaskBarIDs") as tk:
                            for _path, data in _values(tk):
                                if isinstance(data, str) and data:
                                    out[data.upper()] = _product_name(product)
                    except OSError:
                        continue
    return out


def _product_name(product: str) -> str:
    p = product.lower()
    if "firefox" in p or "nightly" in p:
        return "Firefox"
    return product
