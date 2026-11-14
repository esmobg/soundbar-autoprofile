"""Start the daemon when the user logs in (no admin rights needed on any OS)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL = "io.github.esmobg.soundbar-autoprofile"


def _python(windowless: bool = False) -> str:
    exe = Path(sys.executable)
    if windowless and sys.platform == "win32":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            return str(pyw)
    return str(exe)


def _target() -> Path:
    if sys.platform == "win32":
        startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return startup / "soundbar-autoprofile.vbs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "autostart" / "soundbar-autoprofile.desktop"


def _content() -> str:
    if sys.platform == "win32":
        # a .vbs launcher starts pythonw without flashing a console window
        cmd = f'""{_python(windowless=True)}"" -m soundbar_autoprofile run --log-file'
        return f'CreateObject("WScript.Shell").Run "{cmd}", 0, False\r\n'
    if sys.platform == "darwin":
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{_python()}</string><string>-m</string><string>soundbar_autoprofile</string>
    <string>run</string><string>--log-file</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
"""
    return f"""[Desktop Entry]
Type=Application
Name=soundbar-autoprofile
Comment=Switch the soundbar profile to match what you are doing
Exec="{_python()}" -m soundbar_autoprofile run --log-file
X-GNOME-Autostart-enabled=true
NoDisplay=true
"""


def install() -> Path:
    path = _target()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_content(), encoding="utf-8")
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
