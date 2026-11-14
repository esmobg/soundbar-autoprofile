"""Switch Creative App "Sound Modes" (Windows) through UI Automation.

On Windows the GS5's EQ, SuperWide (Surround), Crystalizer, Bass, Smart Volume and Dialog+ are not sent to the
soundbar over USB: Creative's audio-driver plugin (CTUSBAPO) does that processing on the PC, configured by Creative
App. A Sound Mode bundles all of those settings, so the reliable way to change them is to pick a Sound Mode in
Creative App, exactly as a user would, through Windows UI Automation (no mouse clicks, works while the window is
minimized). Creative App is started minimized if it is not running.

Sound modes can be named by their display name ("Movies", "Филми и видео"), internal name ("Movie") or id (GUID);
matching ignores case.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass

from .base import DeviceError

log = logging.getLogger(__name__)

WINDOW_NAME = "Creative"
PROCESS_NAME = "creative.app.exe"
DEFAULT_EXE = r"C:\Program Files (x86)\Creative\Creative App\Creative.App.exe"
PRODUCT_NAME = "Sound Blaster GS5"


@dataclass(frozen=True)
class SoundMode:
    name: str          # display name, as shown in the app
    id: str            # GUID
    internal: str      # e.g. "Movie", "EffectsOff", or the user's name
    kind: str          # "User" or "Factory"

    def matches(self, wanted: str) -> bool:
        w = wanted.strip().casefold()
        return w in (self.name.casefold(), self.id.casefold(), self.internal.casefold())


def parse_item_name(item_name: str, texts: list[str]) -> SoundMode | None:
    """Build a SoundMode from a ProfileList item.

    The item's automation name looks like ``[Movie (00000000-...-000000000004), Factory, MF8470, C:\\...]`` and
    its text blocks are ``[<guid>, <display name>, "Onboard"]``.
    """
    inner = item_name.strip().lstrip("[").rstrip("]")
    head, _, rest = inner.partition("), ")
    internal, _, guid = head.rpartition(" (")
    kind = rest.split(",", 1)[0].strip()
    if not guid:
        return None
    display = next((t for t in texts if t and t != guid and t != "Onboard"), internal)
    return SoundMode(name=display, id=guid, internal=internal, kind=kind)


def _exe_path() -> str:
    try:
        import psutil

        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == PROCESS_NAME and p.info.get("exe"):
                return p.info["exe"]
    except Exception:
        pass
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    return os.path.join(pf86, "Creative", "Creative App", "Creative.App.exe")


class CreativeApp:
    """Drive Creative App's Sound Mode list. Windows only."""

    def __init__(self, launch: bool = True, start_timeout: float = 45.0, keep_minimized: bool = True):
        if sys.platform != "win32":
            raise DeviceError("Creative App sound modes can only be switched on Windows")
        try:
            import uiautomation  # noqa: F401
        except ImportError as e:
            raise DeviceError("switching sound modes needs the 'uiautomation' package (pip install uiautomation)") \
                from e
        self.launch = launch
        self.start_timeout = start_timeout
        self.keep_minimized = keep_minimized

    # --- window ------------------------------------------------------------------------------------------
    def _window(self, wait: float = 0.0):
        import uiautomation as auto

        w = auto.WindowControl(searchDepth=1, Name=WINDOW_NAME)
        return w if w.Exists(wait, 0.5) else None

    def _ensure_window(self):
        w = self._window()
        if w is not None:
            return w
        if not self.launch:
            raise DeviceError("Creative App is not running")
        exe = _exe_path()
        if not os.path.exists(exe):
            raise DeviceError(f"Creative App not found at {exe}; install it from creative.com")
        log.info("starting Creative App (minimized) to switch the sound mode")
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7  # SW_SHOWMINNOACTIVE
        subprocess.Popen([exe], startupinfo=si, close_fds=True)
        w = self._window(wait=self.start_timeout)
        if w is None:
            raise DeviceError("Creative App did not open its window in time")
        if self.keep_minimized:
            self._minimize(w)
        return w

    @staticmethod
    def _minimize(w) -> None:
        import uiautomation as auto

        try:
            w.GetWindowPattern().SetWindowVisualState(auto.WindowVisualState.Minimized)
        except Exception as e:
            log.debug("could not minimize Creative App: %r", e)

    def _combo(self, w, timeout: float = 20.0):
        """The Sound Mode combo box on the Device page (switches to that page if needed)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            combo = w.ComboBoxControl(AutomationId="ProfileList")
            if combo.Exists(1, 0.25):
                if self._items(combo):
                    return combo
                # WPF creates the list items only once the drop-down has been opened (e.g. after a minimized start)
                try:
                    pattern = combo.GetExpandCollapsePattern()
                    pattern.Expand()
                    time.sleep(0.4)
                    pattern.Collapse()
                except Exception as e:
                    log.debug("could not open the sound mode list: %r", e)
                if self._items(combo):
                    return combo
            device_tab = w.ListItemControl(AutomationId="Device")
            if device_tab.Exists(0, 0):
                try:
                    device_tab.GetSelectionItemPattern().Select()
                except Exception:
                    pass
            time.sleep(0.5)
        product = w.TextControl(AutomationId="FeaturePage_ProductName")
        shown = product.Name if product.Exists(0, 0) else "no device"
        raise DeviceError(f"Creative App shows no Sound Mode list (device page: {shown}); "
                          f"is the {PRODUCT_NAME} connected and selected in Creative App?")

    def _items(self, combo) -> list[tuple[object, SoundMode]]:
        import uiautomation as auto

        out = []
        for item in combo.GetChildren():
            if item.ControlTypeName != "ListItemControl":
                continue
            texts = [c.Name for c, _ in auto.WalkControl(item, maxDepth=4) if c.ControlTypeName == "TextControl"]
            mode = parse_item_name(item.Name or "", texts)
            if mode:
                out.append((item, mode))
        return out

    # --- API ---------------------------------------------------------------------------------------------
    def sound_modes(self) -> list[SoundMode]:
        w = self._ensure_window()
        return [m for _, m in self._items(self._combo(w))]

    def current(self) -> SoundMode | None:
        w = self._ensure_window()
        for item, mode in self._items(self._combo(w)):
            try:
                if item.GetSelectionItemPattern().IsSelected:
                    return mode
            except Exception:
                pass
        return None

    def select(self, wanted: str) -> SoundMode:
        w = self._ensure_window()
        combo = self._combo(w)
        items = self._items(combo)
        for item, mode in items:
            if mode.matches(wanted):
                pattern = item.GetSelectionItemPattern()
                if not pattern.IsSelected:
                    pattern.Select()
                    time.sleep(0.3)
                    if not pattern.IsSelected:
                        raise DeviceError(f"Creative App did not switch to sound mode {mode.name!r}")
                return mode
        names = ", ".join(m.name for _, m in items if m.kind == "User") or "none"
        raise DeviceError(f"no sound mode {wanted!r} in Creative App (your own modes: {names}; "
                          "`gs5 modes` lists all)")
