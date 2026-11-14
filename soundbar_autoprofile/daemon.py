"""The background loop: detect -> choose profile -> apply, reconnecting when the soundbar comes and goes.

``run()`` can be remote-controlled from another thread (the tray icon) through a ``Controller``: a manual profile
override, pause/resume, and status callbacks.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psutil

from .config import Config, config_dir
from .detect import get_detector
from .devices import CommandError, Device, DeviceError, open_device
from .rules import Engine

log = logging.getLogger("soundbar_autoprofile")

CONFLICTING_APPS = ("creative.app", "creative app")
LOG_FILE_NAME = "soundbar-autoprofile.log"
MANUAL_REASON = "manual"
RECONNECT_BACKOFF = 2.0      # seconds to wait after losing the soundbar before reopening it
ERROR_BACKOFF = 1.0          # seconds to wait after an unexpected error in the loop


def log_file() -> Path:
    return config_dir() / LOG_FILE_NAME


def setup_logging(verbose: bool = False, to_file: bool = False) -> None:
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:      # None under pythonw.exe and windowed executables
        handlers.append(logging.StreamHandler())
    if to_file:
        config_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file(), maxBytes=512_000, backupCount=2, encoding="utf-8"))
    if not handlers:
        handlers.append(logging.NullHandler())
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


def creative_app_running() -> bool:
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if name.startswith(CONFLICTING_APPS):
            return True
    return False


@dataclass(frozen=True)
class DaemonStatus:
    """A snapshot of what the daemon is doing."""

    running: bool = False
    profile: str | None = None      # profile applied last (None before the first one)
    reason: str = ""                # why it was chosen: a rule's name, "no rule matched" or "manual"
    device: str | None = None       # name of the connected soundbar, None while not connected
    error: str | None = None        # last problem (cleared by the next successful connect / apply)
    override: str | None = None     # manual profile, None = automatic
    paused: bool = False


class Controller:
    """Thread-safe remote control for ``run()``.

    Set ``override`` (a profile name, or None for automatic) and ``paused`` from any thread; the daemon picks
    them up on its next poll, which they trigger right away. ``status`` is a ``DaemonStatus`` snapshot, and
    ``profile``, ``reason``, ``device`` and ``error`` are shortcuts to its fields.

    Callbacks run on the thread that changed the state (usually the daemon thread) and must not block:

    * ``on_change(profile_name, reason)``: after a profile was applied to the soundbar.
    * ``on_status(status)``: after any status field changed (profile, connection, error, override, pause).
    """

    def __init__(self, on_change: Callable[[str, str], None] | None = None,
                 on_status: Callable[[DaemonStatus], None] | None = None):
        self.on_change = on_change
        self.on_status = on_status
        self._lock = threading.Lock()
        self._status = DaemonStatus()
        self._wake = threading.Event()

    # ----- control (any thread)

    @property
    def override(self) -> str | None:
        return self.status.override

    @override.setter
    def override(self, profile: str | None) -> None:
        self._update(override=profile or None)
        self._wake.set()

    @property
    def paused(self) -> bool:
        return self.status.paused

    @paused.setter
    def paused(self, value: bool) -> None:
        self._update(paused=bool(value))
        self._wake.set()

    # ----- status (any thread)

    @property
    def status(self) -> DaemonStatus:
        with self._lock:
            return self._status

    @property
    def profile(self) -> str | None:
        return self.status.profile

    @property
    def reason(self) -> str:
        return self.status.reason

    @property
    def device(self) -> str | None:
        return self.status.device

    @property
    def error(self) -> str | None:
        return self.status.error

    # ----- used by run()

    def _update(self, **changes) -> None:
        with self._lock:
            new = replace(self._status, **changes)
            if new == self._status:
                return
            self._status = new
        self._call(self.on_status, new)

    def _applied(self, profile: str, reason: str) -> None:
        self._update(profile=profile, reason=reason, error=None)
        self._call(self.on_change, profile, reason)

    @staticmethod
    def _call(callback, *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            log.exception("status callback failed")

    def _wait(self, stop: threading.Event, seconds: float) -> None:
        """Sleep until ``seconds`` passed, ``stop`` is set, or the override / pause changed."""
        deadline = time.monotonic() + seconds
        while not stop.is_set():
            left = deadline - time.monotonic()
            if left <= 0:
                return
            if self._wake.wait(min(left, 0.2)):
                self._wake.clear()
                return


def run(cfg: Config, dry_run: bool = False, stop: threading.Event | None = None,
        controller: Controller | None = None) -> None:
    stop = stop or threading.Event()
    ctl = controller

    def sleep(seconds: float) -> None:
        if ctl is not None:
            ctl._wait(stop, seconds)
        else:
            stop.wait(seconds)

    def update(**changes) -> None:
        if ctl is not None:
            ctl._update(**changes)

    detector = get_detector()
    engine = Engine(cfg.rules, cfg.default_profile, cfg.hold_seconds, cfg.media_grace_seconds)
    device: Device | None = None
    applied: str | None = None          # profile on the soundbar as far as we know; None = unknown
    was_paused = False
    warned: set[str] = set()
    last_keepalive = time.monotonic()
    last_open_error = 0.0
    last_logged: dict[str, float] = {}

    def unexpected(what: str, e: Exception) -> None:
        """Log an unexpected error with its traceback (at most once a minute per kind) and show it in the status."""
        now = time.monotonic()
        if now - last_logged.get(what, float("-inf")) >= 60:
            log.error("%s failed (the daemon keeps running)", what, exc_info=e)
            last_logged[what] = now
        update(error=f"{what} failed: {e}")

    def close_device() -> None:
        nonlocal device
        if device is not None:
            try:
                device.close()
            except Exception:
                log.debug("closing the soundbar failed", exc_info=True)
        device = None

    def lost(e: Exception) -> None:
        nonlocal applied
        log.warning("lost the soundbar: %s (reconnecting)", e)
        update(device=None, error=f"lost the soundbar: {e}")
        close_device()
        applied = None
        sleep(RECONNECT_BACKOFF)            # never spin when the device fails right after opening

    def refused(what: str, e: Exception) -> None:
        msg = f"{what}: the soundbar refused a command: {e}"
        if msg not in warned:
            log.warning(msg)
            warned.add(msg)
        update(error=msg)

    log.info("using config: %s", cfg.source)
    for w in cfg.warnings:
        log.warning(w)
    if not dry_run and sys.platform == "win32" and any(p.sound_mode for p in cfg.profiles.values()):
        log.info("sound modes are switched through Creative App (%s); it is started minimized when needed. "
                 "Changing the Sound Mode by hand is overridden at the next switch.",
                 "running" if creative_app_running() else "not running yet")
    update(running=True)

    try:
        while not stop.is_set():
            if ctl is not None and ctl.paused:
                if not was_paused:
                    log.info("paused: not changing the soundbar until resumed")
                    was_paused = True
                sleep(cfg.poll_seconds)
                continue
            if was_paused:
                log.info("resumed")
                was_paused = False
                applied = None              # the soundbar may have been changed meanwhile: re-apply

            if device is None:
                try:
                    device = open_device(cfg.device, dry_run=dry_run)
                    log.info("connected to %s", device.name)
                    update(device=device.name, error=None)
                    engine.force(None)  # re-apply the right profile after (re)connecting
                    applied = None
                except (DeviceError, OSError) as e:
                    if time.monotonic() - last_open_error > 60:
                        log.warning("%s (retrying every 5 s)", e)
                        last_open_error = time.monotonic()
                    update(device=None, error=str(e))
                    sleep(5)
                    continue
                except Exception as e:      # e.g. a missing hidapi module: report it and keep retrying
                    unexpected("opening the soundbar", e)
                    update(device=None)
                    sleep(5)
                    continue

            try:
                activity = detector.read()
                decision = engine.step(activity, time.monotonic())   # keeps running under an override too
            except Exception as e:
                unexpected("reading the activity", e)
                sleep(max(cfg.poll_seconds, ERROR_BACKOFF))
                continue

            override = ctl.override if ctl is not None else None
            if override is not None and override not in cfg.profiles:
                if f"override:{override}" not in warned:
                    log.warning("unknown profile %r; switching automatically", override)
                    warned.add(f"override:{override}")
                update(error=f"unknown profile {override!r}")
                override = None
            if override is not None:
                target, reason = override, MANUAL_REASON
            else:
                # engine.current honours hold_seconds. It differs from `applied` after a switch, a (re)connect,
                # a resume, or when a manual override was just turned off (then it applies right away).
                target = engine.current
                reason = decision.reason if decision.candidate == target else "automatic"

            if target is not None and target != applied:
                profile = cfg.profiles[target]
                log.info("profile -> %s  (%s; app=%s media=%s)", profile.name, reason,
                         activity.foreground_app or "-", activity.media_app or "-")
                error: Exception | None = None
                try:
                    for w in device.apply(profile):
                        if w not in warned:
                            log.warning(w)
                            warned.add(w)
                except CommandError as e:   # connected, but one setting failed: do not reconnect or retry
                    error = e
                except (DeviceError, OSError) as e:
                    lost(e)
                    continue
                except Exception as e:      # a driver bug: report it, do not retry every poll
                    error = e
                applied = target
                if ctl is not None:
                    ctl._applied(target, reason)
                if isinstance(error, CommandError):
                    refused(f"profile {target!r}", error)
                elif error is not None:
                    unexpected(f"applying profile {target!r}", error)
            elif ctl is not None and (override is not None or ctl.reason == MANUAL_REASON) and ctl.reason != reason:
                update(reason=reason)       # manual <-> automatic on the profile already applied

            if cfg.keepalive_seconds and time.monotonic() - last_keepalive >= cfg.keepalive_seconds:
                last_keepalive = time.monotonic()
                try:
                    device.keepalive()
                except CommandError as e:
                    refused("keepalive", e)
                except (DeviceError, OSError) as e:
                    lost(e)
                    continue
                except Exception as e:
                    unexpected("keepalive", e)

            sleep(cfg.poll_seconds)
    finally:
        close_device()
        try:
            detector.close()
        except Exception:
            log.debug("closing the detector failed", exc_info=True)
        update(running=False, device=None)
