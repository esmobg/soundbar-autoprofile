# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - unreleased

First public release.

### Added

- Automatic profile switching for the **Creative Sound Blaster GS5** (`gs5 run`), with a delay before switching
  (`hold_seconds`) and a grace period after media stops (`media_grace_seconds`) to avoid flapping.
- **Sound Modes** per profile on Windows (`sound_mode:`): picks a factory or user-made Sound Mode in Creative App
  (EQ, SuperWide, Crystalizer, Bass, Smart Volume, Dialog+) through Windows UI Automation, without mouse clicks and
  while the app is minimized. Creative App is started minimized when needed. Names match the display name in any
  language, the internal name or the id. `gs5 modes` lists them.
- GS5 lighting over USB on Windows, macOS and Linux: one colour or 7 segments, brightness, on/off, and a keepalive
  for when the strip goes dark on standby (`keepalive_seconds`).
- Raw frames per profile (`frames:`) for commands you captured yourself.
- Rules in YAML, first match wins: case-insensitive regular expressions, lists, `unless:`, on the fields
  `media_playing`, `media_app`, `media_title`, `media_artist`, `media_type`, `foreground_app`, `foreground_title`,
  `fullscreen`, `mic_in_use`, `mic_apps`. Default config with music, movie, work, game and default profiles.
- Activity detection:
  - Windows: media sessions of any player or browser (with cleaned-up app names, Store apps resolved), focused app,
    full screen including exclusive full-screen games, microphone use.
  - macOS: now playing through `media-control`, `nowplaying-cli` or AppleScript (Spotify, Music), focused app,
    full screen (with `pyobjc-framework-Quartz`).
  - Linux: MPRIS players with video detection (`playerctl`), focused app and full screen on X11 (`xdotool`,
    `xprop`), Hyprland, sway and KDE Plasma (`kdotool`), microphone (`pactl`).
- System tray app (`gs5 tray`, extra `[tray]`): shows the active profile, manual profile override, pause, open
  config and log folder, start at login.
- `gs5 autostart install|uninstall|status` (no admin rights; starts the tray icon, or `gs5 run --log-file` with
  `--no-tray`).
- Release builds for Windows, macOS and Linux (PyInstaller): one file that is the tray app and the full `gs5`
  command line.
- Commands: `probe`, `detect [--watch]`, `set`, `rgb`, `run [--log-file] [--dry-run]`, `tray`,
  `modes [--select NAME]`, `config path|init|show|check`, `autostart`, and for protocol work `send`, `listen` and `decode-capture`
  (USBPcap and usbmon captures, grouped into bursts).
- Linux udev rule for access without root (`udev/70-gs5-hidraw.rules`).
- Documentation in English and Bulgarian: README, troubleshooting, FAQ, capture guide, protocol notes, phone
  support notes, contributing guide.

### Known limitations

- Sound Modes (EQ, SuperWide, effects) only on Windows: on the GS5 they are applied by Creative's PC driver, which
  does not exist on macOS and Linux. The `eq:` and `superwide:` profile keys only warn on the GS5.
- macOS and Linux are untested on real hardware; no microphone detection on macOS.
- Bluetooth control and phones are not supported (see `docs/MOBILE.md`).

[Unreleased]: https://github.com/esmobg/soundbar-autoprofile/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/esmobg/soundbar-autoprofile/releases/tag/v0.1.0
