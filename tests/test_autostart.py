"""Autostart files per platform. Paths are redirected to tmp_path; nothing is installed for real."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from soundbar_autoprofile import autostart


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Fake home / APPDATA / XDG dirs and a fake Python with a pythonw.exe next to it."""
    py = tmp_path / "venv" / "python.exe"
    py.parent.mkdir()
    py.write_text("")
    (py.parent / "pythonw.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(py))
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    calls: list[list[str]] = []
    monkeypatch.setattr(autostart.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    return tmp_path, py, calls


def use(monkeypatch, platform: str, tray: bool) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(autostart, "tray_available", lambda: tray)


def test_windows_tray(monkeypatch, env):
    tmp, py, _ = env
    use(monkeypatch, "win32", tray=True)
    pyw = str(py.parent / "pythonw.exe")
    assert autostart.command() == [pyw, "-m", "soundbar_autoprofile", "tray"]
    path = autostart.install()
    assert path == tmp / "appdata" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / \
        "soundbar-autoprofile.vbs"
    assert path.read_bytes().decode() == \
        f'CreateObject("WScript.Shell").Run """{pyw}"" -m soundbar_autoprofile tray", 0, False\r\n'
    assert autostart.status() == (True, path)
    assert autostart.uninstall() == path and not path.exists()
    assert autostart.uninstall() is None


def test_windows_without_pystray_runs_the_daemon(monkeypatch, env):
    _, py, _ = env
    use(monkeypatch, "win32", tray=False)
    content = autostart._content()
    assert f'""{py.parent / "pythonw.exe"}"" -m soundbar_autoprofile run --log-file' in content
    assert " tray" not in content


def test_explicit_no_tray_wins(monkeypatch, env):
    use(monkeypatch, "win32", tray=True)
    assert autostart.command(tray=False)[-2:] == ["run", "--log-file"]


def test_windows_packaged_exe(monkeypatch, env):
    tmp, _, _ = env
    use(monkeypatch, "win32", tray=True)
    exe = str(tmp / "soundbar-autoprofile.exe")
    monkeypatch.setattr(sys, "executable", exe)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart.command() == [exe, "tray"]
    assert autostart._content() == f'CreateObject("WScript.Shell").Run """{exe}"" tray", 0, False\r\n'


def test_macos_tray(monkeypatch, env):
    tmp, py, calls = env
    use(monkeypatch, "darwin", tray=True)
    path = autostart.install()
    assert path == tmp / "home" / "Library" / "LaunchAgents" / f"{autostart.LABEL}.plist"
    text = path.read_text(encoding="utf-8")
    assert (f"<string>{py}</string><string>-m</string><string>soundbar_autoprofile</string>"
            f"<string>tray</string>") in text
    # quitting the tray icon must not make launchd start it again
    assert "<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>" in text
    assert calls == [["launchctl", "unload", str(path)], ["launchctl", "load", "-w", str(path)]]
    autostart.uninstall()
    assert calls[-1] == ["launchctl", "unload", "-w", str(path)]


def test_macos_daemon_keeps_alive_and_escapes_paths(monkeypatch, env):
    tmp, _, _ = env
    use(monkeypatch, "darwin", tray=False)
    monkeypatch.setattr(sys, "executable", str(tmp / "R&D <py>" / "python3"))
    text = autostart._content()
    assert "<string>run</string><string>--log-file</string>" in text
    assert "<key>KeepAlive</key><true/>" in text
    assert "R&amp;D &lt;py&gt;" in text


def test_linux_tray(monkeypatch, env):
    tmp, py, calls = env
    use(monkeypatch, "linux", tray=True)
    path = autostart.install()
    assert path == tmp / "xdg" / "autostart" / "soundbar-autoprofile.desktop"
    text = path.read_text(encoding="utf-8")
    assert f'Exec="{py}" -m soundbar_autoprofile tray\n' in text
    assert text.startswith("[Desktop Entry]\n") and "\r" not in text
    assert calls == []


def test_linux_without_pystray(monkeypatch, env):
    _, py, _ = env
    use(monkeypatch, "linux", tray=False)
    assert f'Exec="{py}" -m soundbar_autoprofile run --log-file\n' in autostart._content()


def test_tray_available_checks_the_modules(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(autostart.importlib.util, "find_spec", lambda name: None)
    assert autostart.tray_available() is False
    monkeypatch.setattr(autostart.importlib.util, "find_spec", lambda name: object())
    assert autostart.tray_available() is True
