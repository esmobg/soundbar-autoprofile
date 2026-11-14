"""The daemon loop and its Controller, driven in a thread with a fake detector and the dry-run device."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

import pytest

from soundbar_autoprofile import config as config_mod
from soundbar_autoprofile import daemon
from soundbar_autoprofile.cli import build_parser
from soundbar_autoprofile.daemon import Controller, DaemonStatus
from soundbar_autoprofile.detect import Activity, Detector
from soundbar_autoprofile.devices import CommandError, DeviceError, DryRunDevice

CONFIG = """
poll_seconds: 0.02
hold_seconds: {hold}
media_grace_seconds: 0
keepalive_seconds: 0
default_profile: default
profiles:
  default: {{ rgb: "ffffff" }}
  music:   {{ rgb: "8a2be2" }}
  movie:   {{ rgb: ["ff5a00", "000000", "ff5a00", "000000", "ff5a00", "000000", "ff5a00"] }}
  work:    {{ lighting: false }}
rules:
  - name: music app playing
    profile: music
    when: {{ media_playing: true }}
"""


class FakeDetector(Detector):
    def __init__(self) -> None:
        self.activity = Activity()
        self.closed = False
        self.fail = 0           # raise this many times before reading again
        self.reads = 0

    def read(self) -> Activity:
        self.reads += 1
        if self.fail:
            self.fail -= 1
            raise RuntimeError("detector broke")
        return self.activity

    def close(self) -> None:
        self.closed = True


class Harness:
    def __init__(self, monkeypatch, hold: float = 0.0) -> None:
        self.cfg = config_mod.parse(CONFIG.format(hold=hold), "test")
        self.detector = FakeDetector()
        self.devices: list[DryRunDevice] = []
        self.fail_next_apply = False
        self.apply_errors: list[Exception] = []       # raised by the next apply() calls, one each
        self.keepalive_errors: list[Exception] = []
        self.keepalives = 0
        monkeypatch.setattr(daemon, "get_detector", lambda: self.detector)
        monkeypatch.setattr(daemon, "open_device", self._open)
        monkeypatch.setattr(daemon, "RECONNECT_BACKOFF", 0.05)
        monkeypatch.setattr(daemon, "ERROR_BACKOFF", 0.02)

    def _open(self, name: str, dry_run: bool = False) -> DryRunDevice:
        assert dry_run, "tests must never open the real soundbar"
        harness = self

        class Flaky(DryRunDevice):
            def apply(self, profile):
                if harness.fail_next_apply:
                    harness.fail_next_apply = False
                    raise DeviceError("unplugged")
                if harness.apply_errors:
                    raise harness.apply_errors.pop(0)
                return super().apply(profile)

            def keepalive(self):
                harness.keepalives += 1
                if harness.keepalive_errors:
                    raise harness.keepalive_errors.pop(0)

        dev = Flaky(log=lambda msg: None)
        self.devices.append(dev)
        return dev

    @property
    def applied(self) -> list[str]:
        return [p.name for d in self.devices for p in d.applied]

    @contextmanager
    def running(self, controller: Controller | None = None):
        stop = threading.Event()
        t = threading.Thread(target=daemon.run, args=(self.cfg,),
                             kwargs={"dry_run": True, "stop": stop, "controller": controller}, daemon=True)
        t.start()
        try:
            yield
        finally:
            stop.set()
            t.join(5)
            assert not t.is_alive(), "the daemon did not stop"


def wait_for(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def playing() -> Activity:
    return Activity(media_playing=True, media_app="Spotify.exe")


def test_runs_without_controller_like_the_cli(monkeypatch):
    h = Harness(monkeypatch)
    h.detector.activity = playing()
    with h.running():
        wait_for(lambda: h.applied == ["music"])
    assert h.detector.closed


def test_status_and_on_change(monkeypatch):
    h = Harness(monkeypatch)
    changes: list[tuple[str, str]] = []
    statuses: list[DaemonStatus] = []
    ctl = Controller(on_change=lambda p, r: changes.append((p, r)), on_status=statuses.append)
    h.detector.activity = playing()
    with h.running(ctl):
        wait_for(lambda: ctl.profile == "music")
        assert ctl.reason == "music app playing"
        assert ctl.device == "dry-run"
        assert ctl.error is None
        assert ctl.status.running
        assert changes == [("music", "music app playing")]

        h.detector.activity = Activity()
        wait_for(lambda: ctl.profile == "default")
        assert changes[-1] == ("default", "no rule matched")
    assert not ctl.status.running
    assert ctl.device is None
    assert statuses and statuses[-1] == ctl.status


def test_override_applies_at_once_and_bypasses_hold(monkeypatch):
    h = Harness(monkeypatch, hold=60)
    ctl = Controller()
    h.detector.activity = playing()
    with h.running(ctl):
        wait_for(lambda: h.applied == ["music"])        # the first decision is applied right away

        t0 = time.monotonic()
        ctl.override = "movie"
        wait_for(lambda: h.applied == ["music", "movie"], timeout=1)
        assert time.monotonic() - t0 < 1
        assert (ctl.profile, ctl.reason) == ("movie", "manual")

        # rules keep running under the override, but nothing is applied for them
        h.detector.activity = Activity()
        time.sleep(0.1)
        assert h.applied == ["music", "movie"]

        # back to automatic: the rules' current profile is restored at once (hold has not passed for "default")
        ctl.override = None
        wait_for(lambda: h.applied == ["music", "movie", "music"], timeout=1)
        assert ctl.profile == "music"


def test_override_to_the_profile_already_applied_does_nothing(monkeypatch):
    h = Harness(monkeypatch)
    ctl = Controller()
    h.detector.activity = playing()
    with h.running(ctl):
        wait_for(lambda: h.applied == ["music"])
        ctl.override = "music"
        wait_for(lambda: ctl.reason == "manual")
        ctl.override = None
        wait_for(lambda: ctl.reason == "music app playing")
        assert h.applied == ["music"]


def test_pause_applies_nothing_and_resume_reapplies(monkeypatch):
    h = Harness(monkeypatch)
    ctl = Controller()
    h.detector.activity = playing()
    with h.running(ctl):
        wait_for(lambda: h.applied == ["music"])
        ctl.paused = True
        assert ctl.status.paused
        time.sleep(0.05)
        ctl.override = "movie"
        h.detector.activity = Activity()
        time.sleep(0.15)
        assert h.applied == ["music"]

        ctl.paused = False
        wait_for(lambda: h.applied == ["music", "movie"], timeout=1)

        # a resume re-applies even an unchanged profile: something else may have changed the soundbar meanwhile
        ctl.paused = True
        time.sleep(0.05)
        ctl.paused = False
        wait_for(lambda: h.applied == ["music", "movie", "movie"], timeout=1)


def test_unknown_override_is_reported_and_ignored(monkeypatch):
    h = Harness(monkeypatch)
    ctl = Controller()
    h.detector.activity = playing()
    with h.running(ctl):
        wait_for(lambda: h.applied == ["music"])
        ctl.override = "nope"
        wait_for(lambda: ctl.error == "unknown profile 'nope'")
        assert h.applied == ["music"]
        ctl.override = "movie"
        wait_for(lambda: ctl.profile == "movie")
        assert ctl.error is None


def test_reconnects_and_reapplies_after_losing_the_soundbar(monkeypatch):
    h = Harness(monkeypatch)
    ctl = Controller()
    errors: list[str | None] = []
    ctl.on_status = lambda st: errors.append(st.error)
    h.detector.activity = playing()
    with h.running(ctl):
        wait_for(lambda: h.applied == ["music"])
        h.fail_next_apply = True
        ctl.override = "movie"
        wait_for(lambda: ctl.profile == "movie")
    assert len(h.devices) == 2                    # reopened after the failure
    assert "lost the soundbar: unplugged" in errors
    assert h.applied == ["music", "movie"]


def test_command_error_is_reported_without_reconnecting(monkeypatch):
    h = Harness(monkeypatch)
    ctl = Controller()
    h.detector.activity = playing()
    h.apply_errors = [CommandError("no ack for op 3a")]
    with h.running(ctl):
        wait_for(lambda: ctl.profile == "music")
        wait_for(lambda: ctl.error is not None)
        assert "refused a command" in ctl.error and "no ack for op 3a" in ctl.error
        time.sleep(0.1)
        assert len(h.devices) == 1                # no reconnect
        assert h.applied == []                    # the failing apply is not retried every poll
        assert ctl.device == "dry-run"
        h.detector.activity = Activity()
        wait_for(lambda: h.applied == ["default"])
        assert ctl.error is None                  # cleared by the next successful apply


def test_unexpected_apply_error_is_not_retried_or_fatal(monkeypatch):
    h = Harness(monkeypatch)
    ctl = Controller()
    h.detector.activity = playing()
    h.apply_errors = [ValueError("driver bug")]
    with h.running(ctl):
        wait_for(lambda: ctl.error is not None and "driver bug" in ctl.error)
        time.sleep(0.1)
        assert len(h.devices) == 1 and h.applied == []
        h.detector.activity = Activity()
        wait_for(lambda: h.applied == ["default"])


def test_lost_soundbar_backs_off_instead_of_spinning(monkeypatch):
    h = Harness(monkeypatch)
    monkeypatch.setattr(daemon, "RECONNECT_BACKOFF", 0.2)
    ctl = Controller()
    h.detector.activity = playing()
    h.apply_errors = [DeviceError("unplugged")] * 1000
    with h.running(ctl):
        time.sleep(0.5)
    assert 1 <= len(h.devices) <= 4               # without the back-off this reopens every poll (0.02 s)


def test_keepalive_errors(monkeypatch):
    h = Harness(monkeypatch)
    h.cfg.keepalive_seconds = 0.01
    ctl = Controller()
    h.detector.activity = playing()
    h.keepalive_errors = [CommandError("refused"), RuntimeError("oops")]
    with h.running(ctl):
        wait_for(lambda: h.keepalives >= 4)
    assert len(h.devices) == 1                    # neither a refused command nor a bug reconnects
    assert h.applied == ["music"]


def test_detector_exception_does_not_kill_the_loop(monkeypatch):
    h = Harness(monkeypatch)
    ctl = Controller()
    h.detector.activity = playing()
    h.detector.fail = 3
    with h.running(ctl):
        wait_for(lambda: h.applied == ["music"])
        assert h.detector.reads >= 4
        assert ctl.status.running


def test_open_exception_does_not_kill_the_loop(monkeypatch):
    h = Harness(monkeypatch)
    opened = h._open
    calls = []

    def broken_open(name, dry_run=False):
        calls.append(name)
        if len(calls) == 1:
            raise ImportError("No module named 'hid'")
        return opened(name, dry_run)

    monkeypatch.setattr(daemon, "open_device", broken_open)
    monkeypatch.setattr(daemon.Controller, "_wait", lambda self, stop, seconds: stop.wait(min(seconds, 0.02)))
    ctl = Controller()
    h.detector.activity = playing()
    with h.running(ctl):
        wait_for(lambda: h.applied == ["music"])
    assert len(calls) == 2


def test_config_warnings_are_logged(monkeypatch, caplog):
    h = Harness(monkeypatch)
    h.cfg.warnings = ["test: unknown setting 'colour' is ignored"]
    with caplog.at_level("WARNING", logger="soundbar_autoprofile"), h.running():
        wait_for(lambda: h.applied == ["default"])
    assert "unknown setting 'colour'" in caplog.text


def test_callback_errors_do_not_stop_the_daemon(monkeypatch):
    h = Harness(monkeypatch)

    def boom(*args):
        raise RuntimeError("bad callback")

    ctl = Controller(on_change=boom, on_status=boom)
    h.detector.activity = playing()
    with h.running(ctl):
        wait_for(lambda: ctl.profile == "music")
        h.detector.activity = Activity()
        wait_for(lambda: ctl.profile == "default")


def test_cli_has_tray_command():
    args = build_parser().parse_args(["tray", "--dry-run"])
    assert args.cmd == "tray" and args.dry_run
    args = build_parser().parse_args(["autostart", "install", "--no-tray"])
    assert args.no_tray


# ----- tray helpers (no icon is shown)

def test_tray_profile_colour_and_status_text():
    from soundbar_autoprofile.devices.base import Profile
    from soundbar_autoprofile.tray import profile_colour, status_text

    assert profile_colour(Profile("a", rgb="8a2be2")) == (0x8A, 0x2B, 0xE2)
    assert profile_colour(Profile("a", rgb=["#ff5a00", "000000"])) == (0xFF, 0x5A, 0x00)
    assert profile_colour(Profile("a", rgb="ff5a00", lighting=False)) is None
    assert profile_colour(Profile("a")) is None
    assert profile_colour(None) is None

    st = DaemonStatus(running=True, device="dry-run", profile="music", reason="music app playing")
    assert status_text(st) == "Profile: music (music app playing)"
    assert status_text(DaemonStatus(running=True)) == "Soundbar not connected"
    assert status_text(DaemonStatus(running=True, device="x", profile="music", paused=True)).startswith("Paused")
    assert status_text(DaemonStatus(error="config error: bad")) == "Not running: config error: bad"


def test_tray_icon_image():
    pytest.importorskip("PIL")
    from soundbar_autoprofile.tray import GREY, make_icon

    img = make_icon((0x8A, 0x2B, 0xE2), size=64)
    assert img.size == (64, 64)
    assert img.getpixel((32, 32))[:3] == (0x8A, 0x2B, 0xE2)
    assert img.getpixel((0, 0))[3] == 0                     # transparent corner: a round icon
    assert make_icon(None).getpixel((32, 10))[:3] == GREY
    assert make_icon((0, 0, 0), paused=True).getpixel((32 - 8, 32))[:3] == (255, 255, 255)


def test_tray_menu_drives_the_controller(monkeypatch, tmp_path):
    try:
        import pystray  # noqa: F401  (may fail without a display on Linux)
    except Exception:
        pytest.skip("pystray is not usable here")
    from soundbar_autoprofile import tray

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(CONFIG.format(hold=0), encoding="utf-8")
    app = tray.TrayApp(cfg_file, dry_run=True)
    app._pystray = pystray
    assert app.load_config()
    menu = app._menu()
    items = {str(i): i for i in menu.items if str(i)}
    assert {"Automatic", "default", "music", "movie", "work", "Pause", "Open config", "Quit"} <= set(items)
    assert items["Automatic"].checked and items["Automatic"].radio

    items["movie"](None)                       # clicking a profile = manual override
    assert app.controller.override == "movie"
    assert items["movie"].checked and not items["Automatic"].checked
    items["Automatic"](None)
    assert app.controller.override is None
    items["Pause"](None)
    assert app.controller.paused and items["Pause"].checked

    opened = []
    monkeypatch.setattr(tray, "open_path", lambda path, text_file=False: opened.append((path, text_file)))
    new_cfg = tmp_path / "new" / "config.yaml"
    app.config_path = new_cfg
    items["Open config"](None)
    assert new_cfg.exists() and opened == [(new_cfg, True)]   # the default config is written first

    from soundbar_autoprofile import autostart

    installed: list[bool] = []
    monkeypatch.setattr(autostart, "status", lambda: (bool(installed), tmp_path / "autostart"))
    monkeypatch.setattr(autostart, "install", lambda tray=None: installed.append(tray) or tmp_path / "autostart")
    monkeypatch.setattr(autostart, "uninstall", lambda: installed.clear() or tmp_path / "autostart")
    assert not items["Start at login"].checked
    items["Start at login"](None)
    assert installed == [True] and items["Start at login"].checked
    items["Start at login"](None)
    assert installed == [] and not items["Start at login"].checked
