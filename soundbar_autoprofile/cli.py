"""Command line: gs5 probe | detect | set | rgb | send | listen | run | tray | config | autostart | decode-capture."""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from . import config as config_mod
from .devices import DeviceError, open_device
from .devices.base import Profile


def _load_config(args) -> config_mod.Config:
    from pathlib import Path

    return config_mod.load(Path(args.config) if args.config else None)


def cmd_probe(args) -> int:
    from .daemon import creative_app_running

    with open_device(args.device) as dev:
        info = dev.probe()
    info["creative_app_running"] = creative_app_running()
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        for k, v in info.items():
            print(f"{k:22} {v}")
    return 0


def cmd_modes(args) -> int:
    from .devices.creative_app import CreativeApp

    app = CreativeApp()
    if args.select:
        mode = app.select(args.select)
        print(f"sound mode -> {mode.name}")
        return 0
    current = app.current()
    modes = app.sound_modes()
    if args.json:
        print(json.dumps([{**m.__dict__, "current": current is not None and m.id == current.id} for m in modes],
                         ensure_ascii=False, indent=2))
        return 0
    for kind in ("User", "Factory"):
        group = [m for m in modes if m.kind == kind]
        if group:
            print("Your sound modes:" if kind == "User" else "\nFactory sound modes:")
            for m in group:
                mark = "*" if current is not None and m.id == current.id else " "
                print(f" {mark} {m.name}")
    print("\nUse one in a profile:  sound_mode: <name>   (* = active now)")
    return 0


def cmd_detect(args) -> int:
    from .detect import get_detector
    from .rules import choose

    cfg = _load_config(args)
    det = get_detector()
    try:
        while True:
            a = det.read()
            profile, reason = choose(a, cfg.rules, cfg.default_profile)
            if args.json:
                print(json.dumps({"profile": profile, "reason": reason, "activity": a.as_dict()}))
            else:
                media = f"{a.media_app} - {a.media_title}" if a.media_playing else "nothing playing"
                print(f"[{time.strftime('%H:%M:%S')}] profile={profile:8} ({reason})")
                print(f"    app={a.foreground_app!r} fullscreen={a.fullscreen} mic={a.mic_in_use}"
                      f" media={media!r} type={a.media_type or '?'}")
            if not args.watch:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    finally:
        det.close()


def cmd_set(args) -> int:
    cfg = _load_config(args)
    if args.profile not in cfg.profiles:
        print(f"unknown profile {args.profile!r}; defined: {', '.join(cfg.profiles)}", file=sys.stderr)
        return 2
    with open_device(cfg.device, dry_run=args.dry_run) as dev:
        for w in dev.apply(cfg.profiles[args.profile]):
            print(f"warning: {w}", file=sys.stderr)
    print(f"applied profile {args.profile!r}")
    return 0


def cmd_rgb(args) -> int:
    profile = Profile(name="rgb")
    if args.off:
        profile.lighting = False
    else:
        if args.colours:
            profile.rgb = args.colours[0] if len(args.colours) == 1 else args.colours
        if args.brightness is not None:
            profile.brightness = args.brightness
    if profile.rgb is None and profile.brightness is None and profile.lighting is None:
        print("give a colour (RRGGBB, or 7 of them), --brightness N or --off", file=sys.stderr)
        return 2
    with open_device(args.device) as dev:
        dev.apply(profile)
    return 0


def cmd_send(args) -> int:
    from .protocol import parse_hex

    frame = parse_hex(" ".join(args.hex))
    with open_device(args.device) as dev:
        replies = dev.send_raw(frame, listen=args.listen)
    print(f"-> {frame.hex(' ')}")
    for r in replies:
        print(f"<- {r.rstrip(bytes(1)).hex(' ')}")
    if not replies:
        print("(no reply)")
    return 0


def cmd_listen(args) -> int:
    """Print every report the soundbar sends, without sending anything ourselves.

    On Windows, macOS and Linux every open handle receives the device's input reports, so this also shows the
    replies to Creative App's queries and the ACKs of settings changed in the app."""
    from .devices.gs5 import HidTransport, find_paths

    paths = find_paths()
    if not paths:
        raise DeviceError("no Sound Blaster GS5 found (USB-C cable connected?)")
    t = HidTransport(paths[0])
    seen: dict[bytes, int] = {}
    start = time.monotonic()
    print("listening; change settings in Creative App now (Ctrl+C to stop)")
    try:
        while args.seconds <= 0 or time.monotonic() - start < args.seconds:
            rep = t.read(0.5)
            if rep is None:
                continue
            rep = rep.rstrip(b"\0")
            seen[rep] = seen.get(rep, 0) + 1
            if args.all or seen[rep] == 1:
                print(f"{time.monotonic() - start:8.2f}s <- {rep.hex(' ')}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        t.close()
    return 0


def cmd_run(args) -> int:
    from .daemon import run, setup_logging

    setup_logging(verbose=args.verbose, to_file=args.log_file)
    cfg = _load_config(args)
    try:
        run(cfg, dry_run=args.dry_run)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_tray(args) -> int:
    from pathlib import Path

    from .daemon import setup_logging
    from .tray import TrayUnavailable
    from .tray import main as tray_main

    setup_logging(verbose=args.verbose, to_file=True)
    try:
        return tray_main(Path(args.config) if args.config else None, dry_run=args.dry_run)
    except TrayUnavailable as e:
        print(f"gs5: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


def cmd_config(args) -> int:
    if args.action == "path":
        print(config_mod.config_path())
    elif args.action == "init":
        print(f"wrote {config_mod.write_default(overwrite=args.force)}")
    elif args.action == "show":
        p = config_mod.config_path()
        print(p.read_text(encoding="utf-8") if p.exists() else config_mod.default_config_text())
    elif args.action == "check":
        cfg = _load_config(args)
        for w in cfg.warnings:
            print(f"warning: {w}")
        print(f"OK: {cfg.source}: {len(cfg.profiles)} profiles, {len(cfg.rules)} rules")
    return 0


def cmd_autostart(args) -> int:
    from . import autostart

    if args.action == "install":
        path = autostart.install(tray=False if args.no_tray else None)
        print(f"installed: {path}")
        print(f"starts: {autostart.command_line(tray=False if args.no_tray else None)}")
    elif args.action == "uninstall":
        p = autostart.uninstall()
        print(f"removed: {p}" if p else "autostart was not installed")
    else:
        on, p = autostart.status()
        print(f"{'installed' if on else 'not installed'}: {p}")
    return 0


def cmd_decode(args) -> int:
    from .capture import bursts, read_frames, reply_to

    frames = read_frames(args.file)
    if not frames:
        print("no Creative HID frames found. Was the soundbar's USB bus captured, with Creative App in use?")
        return 1
    groups = bursts(frames, gap=args.gap, keep_polling=args.all)
    print(f"{len(frames)} frames, {len(groups)} bursts of app->soundbar commands"
          f"{'' if args.all else ' (repeated polling hidden; --all shows it)'}\n")
    for i, g in enumerate(groups, 1):
        print(f"burst {i}  at {g[0].time:7.2f}s")
        for f in g:
            print(f"  -> {f.hex()}")
            if args.replies and (r := reply_to(frames, f)):
                print(f"  <- {r.hex()}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gs5", description="Switch your soundbar's profile to match what you do.")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--config", help="config file (default: see `gs5 config path`)")
    ap.add_argument("--device", default="gs5", help="device driver (default: gs5)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("modes", help="list Creative App sound modes (Windows), or switch with --select NAME")
    p.add_argument("--select", metavar="NAME", help="switch to this sound mode now")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_modes)

    p = sub.add_parser("probe", help="check the soundbar is reachable (read-only)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("detect", help="show what is detected and which profile the rules pick")
    p.add_argument("--watch", "-w", action="store_true", help="keep printing")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("set", help="apply one profile now")
    p.add_argument("profile")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("rgb", help="set the light strip: one RRGGBB colour, or 7 (left to right)")
    p.add_argument("colours", nargs="*")
    p.add_argument("--brightness", type=int)
    p.add_argument("--off", action="store_true")
    p.set_defaults(func=cmd_rgb)

    p = sub.add_parser("send", help="(advanced) send a raw hex frame and print the replies")
    p.add_argument("hex", nargs="+", help='e.g. "05 6a 09 01 00 00"')
    p.add_argument("--listen", type=float, default=0.5)
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("listen", help="(advanced) print what the soundbar sends; use while clicking Creative App")
    p.add_argument("--seconds", type=float, default=0, help="stop after N seconds (default: until Ctrl+C)")
    p.add_argument("--all", action="store_true", help="also repeat reports already shown")
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser("run", help="run in the background and switch profiles automatically")
    p.add_argument("--dry-run", action="store_true", help="only log what would be applied")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--log-file", action="store_true", help="also log to a file in the config folder")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("tray", help="like run, with a tray icon: pick a profile by hand, pause, open the config")
    p.add_argument("--dry-run", action="store_true", help="only log what would be applied")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=cmd_tray)

    p = sub.add_parser("config", help="config file: path | init | show | check")
    p.add_argument("action", choices=["path", "init", "show", "check"])
    p.add_argument("--force", action="store_true", help="init: overwrite an existing file")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("autostart", help="start automatically at login: install | uninstall | status")
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.add_argument("--no-tray", action="store_true",
                   help="install: start `run --log-file` without a tray icon (the default when pystray is missing)")
    p.set_defaults(func=cmd_autostart)

    p = sub.add_parser("decode-capture", help="list Creative HID commands in a USB capture (.pcapng)")
    p.add_argument("file")
    p.add_argument("--gap", type=float, default=1.5, help="seconds of quiet that separate two actions")
    p.add_argument("--all", action="store_true", help="also show the app's repeated polling")
    p.add_argument("--replies", action="store_true", help="show the soundbar's reply to each command")
    p.set_defaults(func=cmd_decode)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # window/track titles in any language, any console
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (DeviceError, ValueError, FileExistsError, PermissionError) as e:
        print(f"gs5: {e}", file=sys.stderr)
        return 1
