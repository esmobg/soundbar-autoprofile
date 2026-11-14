"""System tray icon: shows the active profile, lets you pick one by hand, pause, and open the config / logs.

Needs the optional ``tray`` extra (``pystray`` and ``Pillow``); both are imported lazily.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from . import config as config_mod
from .daemon import Controller, DaemonStatus, log_file, run
from .devices.base import Profile

log = logging.getLogger("soundbar_autoprofile")

APP_NAME = "soundbar-autoprofile"
GREY = (128, 128, 128)
INSTALL_HINT = "the tray icon needs pystray and Pillow: pip install \"soundbar-autoprofile[tray]\""


class TrayUnavailable(RuntimeError):
    """pystray / Pillow are not installed, or there is no tray to show an icon in."""


def _import_pil():
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:
        raise TrayUnavailable(f"{INSTALL_HINT} ({e})") from e
    return Image, ImageDraw


def _import_pystray():
    _import_pil()
    try:
        import pystray
    except ImportError as e:
        raise TrayUnavailable(f"{INSTALL_HINT} ({e})") from e
    except Exception as e:      # e.g. no X display on Linux
        raise TrayUnavailable(f"cannot show a tray icon here: {e}") from e
    return pystray


# ----- pure helpers (no pystray needed)

def profile_colour(profile: Profile | None) -> tuple[int, int, int] | None:
    """The profile's light colour as (r, g, b), the first one if it has several; None when it has none."""
    if profile is None or profile.lighting is False or not profile.rgb:
        return None
    rgb = profile.rgb[0] if isinstance(profile.rgb, list) else profile.rgb
    text = str(rgb).strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def make_icon(colour: tuple[int, int, int] | None, size: int = 64, paused: bool = False):
    """A round icon in the profile's colour (grey without one), with a pause sign when paused."""
    Image, ImageDraw = _import_pil()
    colour = colour or GREY
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    d.ellipse((pad, pad, size - 1 - pad, size - 1 - pad), fill=(*colour, 255), outline=(30, 30, 30, 255),
              width=max(1, size // 20))
    if paused:
        bar_w, bar_h = size // 8, size * 3 // 8
        top = (size - bar_h) // 2
        for x in (size // 2 - bar_w - size // 16, size // 2 + size // 16):
            d.rectangle((x, top, x + bar_w, top + bar_h), fill=(255, 255, 255, 255))
    return img


def status_text(st: DaemonStatus) -> str:
    """First menu line, e.g. "Profile: music (music app playing)"."""
    if st.paused:
        return "Paused" + (f" (profile: {st.profile})" if st.profile else "")
    if not st.running:
        return "Not running" + (f": {st.error}" if st.error else "")
    if st.device is None:
        return "Soundbar not connected"
    if st.profile is None:
        return "Profile: -"
    return f"Profile: {st.profile} ({st.reason})" if st.reason else f"Profile: {st.profile}"


def open_path(path: Path, text_file: bool = False) -> None:
    """Open a file or folder with the OS default application (a text editor for ``text_file``)."""
    if sys.platform == "win32":
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError:
            if not text_file:
                raise
            subprocess.Popen(["notepad.exe", str(path)])   # .yaml has no default app on a fresh Windows
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-t", str(path)] if text_file else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ----- single instance

class _InstanceLock:
    """Keeps a second tray icon (and a second daemon fighting the first) from starting."""

    def __init__(self) -> None:
        self._handle: Any = None

    def acquire(self) -> bool:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}-tray")
            if not handle:
                return True     # cannot tell; do not block the user
            if ctypes.get_last_error() == 183:     # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(ctypes.c_void_p(handle))
                return False
            self._handle = handle
            return True
        import fcntl

        config_mod.config_dir().mkdir(parents=True, exist_ok=True)
        f = open(config_mod.config_dir() / "tray.lock", "w")     # held open (and locked) while the tray runs
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._handle = f
        return True


# ----- the app

class TrayApp:
    def __init__(self, config_path: Path | None = None, dry_run: bool = False):
        self.config_path = config_path
        self.dry_run = dry_run
        self.cfg: config_mod.Config | None = None
        self.config_error: str | None = None
        self.controller = Controller(on_status=self._on_status)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._icon: Any = None
        self._pystray: Any = None

    # daemon thread

    def load_config(self) -> bool:
        try:
            self.cfg = config_mod.load(self.config_path)
            self.config_error = None
            return True
        except Exception as e:     # OSError, ValueError, yaml.YAMLError: show it instead of crashing
            log.error("config: %s", e)
            self.config_error = f"config error: {e}"
            return False

    def start_daemon(self) -> None:
        if self.cfg is None:
            self.controller._update(running=False, error=self.config_error)
            return
        self._stop = threading.Event()
        cfg, stop = self.cfg, self._stop

        def target() -> None:
            try:
                run(cfg, dry_run=self.dry_run, stop=stop, controller=self.controller)
            except Exception as e:
                log.exception("the daemon stopped")
                self.controller._update(running=False, error=f"stopped: {e}")

        self._thread = threading.Thread(target=target, name="soundbar-daemon", daemon=True)
        self._thread.start()

    def stop_daemon(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def reload(self) -> None:
        log.info("reloading the config")
        if not self.load_config() and self.cfg is not None:
            self.controller._update(error=self.config_error)    # keep running with the previous config
            return
        self.stop_daemon()
        if self.cfg is not None and self.controller.override not in (None, *self.cfg.profiles):
            self.controller.override = None
        self.start_daemon()
        self._refresh(rebuild_menu=True)

    # icon and menu

    def _profile(self, name: str | None) -> Profile | None:
        return self.cfg.profiles.get(name) if self.cfg is not None and name else None

    def _image(self, st: DaemonStatus):
        colour = profile_colour(self._profile(st.profile)) if st.device or self.dry_run else None
        return make_icon(colour, paused=st.paused)

    def _title(self, st: DaemonStatus) -> str:
        return f"{APP_NAME}: {status_text(st)}"[:120]     # Windows truncates tooltips at 128 characters

    def _on_status(self, st: DaemonStatus) -> None:
        self._refresh()

    def _refresh(self, rebuild_menu: bool = False) -> None:
        icon = self._icon
        if icon is None:
            return
        st = self.controller.status
        try:
            icon.icon = self._image(st)
            icon.title = self._title(st)
            if rebuild_menu:
                icon.menu = self._menu()
            icon.update_menu()
        except Exception:
            log.exception("could not update the tray icon")

    def _menu(self):
        pystray = self._pystray
        Item, Menu = pystray.MenuItem, pystray.Menu
        ctl = self.controller

        def choose(name: str | None):
            def action(icon, item) -> None:
                ctl.override = name
                log.info("manual profile: %s", name or "automatic")
            return action

        def is_override(name: str | None):
            return lambda item: ctl.override == name

        items: list[Any] = [Item(lambda item: status_text(ctl.status), None, enabled=False)]
        items.append(Item(lambda item: f"Soundbar: {ctl.device or 'not connected'}", None, enabled=False,
                          visible=lambda item: ctl.status.running))
        items.append(Item(lambda item: f"! {ctl.error}"[:100], None, enabled=False,
                          visible=lambda item: bool(ctl.error)))
        items.append(Menu.SEPARATOR)
        items.append(Item("Automatic", choose(None), checked=is_override(None), radio=True))
        for name in (self.cfg.profiles if self.cfg is not None else ()):
            items.append(Item(name, choose(name), checked=is_override(name), radio=True))
        items.append(Menu.SEPARATOR)
        items.append(Item("Pause", self._toggle_pause, checked=lambda item: ctl.paused))
        items.append(Menu.SEPARATOR)
        items.append(Item("Open config", self._open_config))
        items.append(Item("Reload config", lambda icon, item: self.reload()))
        items.append(Item("Open log folder", self._open_logs))
        items.append(Item("Start at login", self._toggle_autostart, checked=lambda item: self._autostart_on()))
        items.append(Menu.SEPARATOR)
        items.append(Item("Quit", self._quit))
        return Menu(*items)

    # menu actions

    def _toggle_pause(self, icon, item) -> None:
        self.controller.paused = not self.controller.paused

    def _open_config(self, icon, item) -> None:
        path = self.config_path or config_mod.config_path()
        try:
            if not path.exists():
                config_mod.write_default(path)
                log.info("wrote the default config to %s", path)
            open_path(path, text_file=True)
        except OSError as e:
            log.error("could not open %s: %s", path, e)
            self.controller._update(error=f"could not open the config: {e}")

    def _open_logs(self, icon, item) -> None:
        folder = log_file().parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            open_path(folder)
        except OSError as e:
            log.error("could not open %s: %s", folder, e)

    @staticmethod
    def _autostart_on() -> bool:
        from . import autostart

        try:
            return autostart.status()[0]
        except (OSError, KeyError):
            return False

    def _toggle_autostart(self, icon, item) -> None:
        from . import autostart

        try:
            if self._autostart_on():
                log.info("autostart removed: %s", autostart.uninstall())
            else:
                log.info("autostart installed: %s", autostart.install(tray=True))
        except (OSError, KeyError) as e:
            log.error("autostart: %s", e)
            self.controller._update(error=f"autostart: {e}")
        self._refresh()

    def _quit(self, icon, item) -> None:
        log.info("quit from the tray menu")
        self.stop_daemon()
        icon.visible = False
        icon.stop()

    # main

    def run(self) -> None:
        """Show the icon; blocks until Quit. Must be called on the main thread (macOS requires it)."""
        pystray = self._pystray = _import_pystray()
        self.load_config()
        st = self.controller.status
        icon = pystray.Icon(APP_NAME, self._image(st), self._title(st), self._menu())

        def setup(icon) -> None:
            icon.visible = True
            self._icon = icon
            self.start_daemon()
            self._refresh()

        try:
            icon.run(setup=setup)
        finally:
            self.stop_daemon()


def main(config_path: Path | None = None, dry_run: bool = False) -> int:
    _import_pystray()      # fail early with the install hint
    lock = _InstanceLock()
    if not lock.acquire():
        log.warning("the tray icon is already running")
        return 0
    log.info("starting the tray icon (log: %s)", log_file())
    TrayApp(config_path, dry_run=dry_run).run()
    return 0
