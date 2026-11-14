"""The background loop: detect -> choose profile -> apply, reconnecting when the soundbar comes and goes."""

from __future__ import annotations

import logging
import threading
import time
from logging.handlers import RotatingFileHandler

import psutil

from .config import Config, config_dir
from .detect import get_detector
from .devices import Device, DeviceError, open_device
from .rules import Engine

log = logging.getLogger("soundbar_autoprofile")

CONFLICTING_APPS = ("creative.app", "creative app")


def setup_logging(verbose: bool = False, to_file: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        config_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(config_dir() / "soundbar-autoprofile.log", maxBytes=512_000,
                                            backupCount=2, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


def creative_app_running() -> bool:
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if name.startswith(CONFLICTING_APPS):
            return True
    return False


def run(cfg: Config, dry_run: bool = False, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    detector = get_detector()
    engine = Engine(cfg.rules, cfg.default_profile, cfg.hold_seconds, cfg.media_grace_seconds)
    device: Device | None = None
    warned: set[str] = set()
    last_keepalive = time.monotonic()
    last_open_error = 0.0

    log.info("using config: %s", cfg.source)
    if not dry_run and creative_app_running():
        log.warning("Creative App is running. It talks to the soundbar too and may undo profile changes; "
                    "close it (and remove it from startup) while soundbar-autoprofile runs.")

    try:
        while not stop.is_set():
            if device is None:
                try:
                    device = open_device(cfg.device, dry_run=dry_run)
                    log.info("connected to %s", device.name)
                    engine.force(None)  # re-apply the right profile after (re)connecting
                except (DeviceError, OSError) as e:
                    if time.monotonic() - last_open_error > 60:
                        log.warning("%s (retrying every 5 s)", e)
                        last_open_error = time.monotonic()
                    stop.wait(5)
                    continue

            activity = detector.read()
            decision = engine.step(activity, time.monotonic())
            if decision.switch_to:
                profile = cfg.profiles[decision.switch_to]
                log.info("profile -> %s  (%s; app=%s media=%s)", profile.name, decision.reason,
                         activity.foreground_app or "-", activity.media_app or "-")
                try:
                    for w in device.apply(profile):
                        if w not in warned:
                            log.warning(w)
                            warned.add(w)
                except (DeviceError, OSError) as e:
                    log.warning("lost the soundbar: %s", e)
                    device.close()
                    device = None
                    continue

            if cfg.keepalive_seconds and time.monotonic() - last_keepalive >= cfg.keepalive_seconds:
                last_keepalive = time.monotonic()
                try:
                    device.keepalive()
                except (DeviceError, OSError) as e:
                    log.warning("lost the soundbar: %s", e)
                    device.close()
                    device = None
                    continue

            stop.wait(cfg.poll_seconds)
    finally:
        if device is not None:
            device.close()
        detector.close()
