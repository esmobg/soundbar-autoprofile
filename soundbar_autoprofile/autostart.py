"""Start the tray icon (or the plain daemon) when the user logs in. No admin rights needed on any OS."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

LABEL = "io.github.esmobg.soundbar-autoprofile"


def tray_available() -> bool:
    """True when the tray icon can run (pystray and Pillow are installed, or this is the packaged app)."""
    if getattr(sys, "frozen", False):
        return True
    return all(importlib.util.find_spec(m) is not None for m in ("pystray", "PIL"))


def _python(windowless: bool = False) -> str:
    exe = Path(sys.executable)
    if windowless and sys.platform == "win32":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            return str(pyw)
    return str(exe)


def command(tray: bool | None = None) -> list[str]:
    """What runs at login. ``tray=None`` picks the tray icon when it is available."""
    if tray is None:
        tray = tray_available()
    args = ["tray"] if tray else ["run", "--log-file"]
    if getattr(sys, "frozen", False):          # the packaged executable (PyInstaller) is the CLI itself
        return [sys.executable, *args]
    return [_python(windowless=True), "-m", "soundbar_autoprofile", *args]


def command_line(tray: bool | None = None) -> str:
    exe, *args = command(tray)
    return " ".join([f'"{exe}"', *args])


def _target() -> Path:
    if sys.platform == "win32":
        startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return startup / "soundbar-autoprofile.vbs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "autostart" / "soundbar-autoprofile.desktop"


def _content(tray: bool | None = None) -> str:
    argv = command(tray)
    if sys.platform == "win32":
        # a .vbs launcher starts pythonw / the windowed exe without flashing a console window
        exe, *args = argv
        cmd = " ".join([f'""{exe}""', *args])
        return f'CreateObject("WScript.Shell").Run "{cmd}", 0, False\r\n'
    if sys.platform == "darwin":
        strings = "".join(f"<string>{escape(a)}</string>" for a in argv)
        # the plain daemon is restarted whenever it exits; the tray icon only after a crash, not after Quit
        keep_alive = "<dict><key>SuccessfulExit</key><false/></dict>" if argv[-1] == "tray" else "<true/>"
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    {strings}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>{keep_alive}
</dict>
</plist>
"""
    return f"""[Desktop Entry]
Type=Application
Name=soundbar-autoprofile
Comment=Switch the soundbar profile to match what you are doing
Exec={command_line(tray)}
X-GNOME-Autostart-enabled=true
NoDisplay=true
"""


def install(tray: bool | None = None) -> Path:
    path = _target()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_content(tray), encoding="utf-8", newline="")   # line endings exactly as in _content()
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        subprocess.run(["launchctl", "load", "-w", str(path)], check=False)
    return path


def uninstall() -> Path | None:
    path = _target()
    if not path.exists():
        return None
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "unload", "-w", str(path)], capture_output=True)
    path.unlink()
    return path


def status() -> tuple[bool, Path]:
    path = _target()
    return path.exists(), path
