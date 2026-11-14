# soundbar-autoprofile

**Your soundbar switches its sound profile by itself: music → Music, movie → Movies, meeting/work → Effects Off,
game → Gaming.** It starts with the Creative Sound Blaster GS5 and is built so that more soundbars can be added.

[Български](README.bg.md)

It watches what is playing (Spotify, VLC, Netflix, YouTube…), which app is in front, whether it is full screen and
whether the microphone is in use. Then it picks a profile from your rules and applies it: the **Sound Mode** in
Creative App (EQ, SuperWide, Crystalizer, Bass, Smart Volume, Dialog+) and the **light strip** over USB.

## Status

| Feature (Sound Blaster GS5) | Windows | macOS / Linux |
|---|---|---|
| Sound Mode per profile (EQ, SuperWide, effects) | ✅ through Creative App | ❌ Creative App does not exist there |
| Your own Sound Modes made in Creative App | ✅ | ❌ |
| RGB colour / brightness per profile | ✅ | ✅ |

On the GS5, EQ, SuperWide and the other effects are not stored in the soundbar: Creative's audio driver applies
them on the PC, configured by Creative App. On macOS and Linux the soundbar plays without that processing, so only
the lighting can change. Details: [docs/PROTOCOL.md](docs/PROTOCOL.md).

| Platform | What it detects | Status |
|---|---|---|
| Windows 10/11 | media from any player or browser, focused app, full screen (also exclusive full-screen games), microphone | ✅ tested |
| macOS | media from any app with [`media-control`](https://github.com/ungive/media-control) (otherwise Spotify/Music only), focused app, full screen; no microphone | ⚠️ untested on hardware |
| Linux (X11) | MPRIS players incl. video (`playerctl`), focused app and full screen (`xdotool`, `xprop`), microphone (`pactl`) | ⚠️ untested on hardware |
| Linux (Wayland) | as X11 on Hyprland and sway; KDE via `kdotool` (no full screen); GNOME: media and microphone only | ⚠️ untested on hardware |
| Android | planned: companion app over Bluetooth, see [docs/MOBILE.md](docs/MOBILE.md) | 🗺️ |
| iOS | not possible: iOS lets no app watch other apps' playback or control the soundbar in the background | ❌ |

Connect the soundbar with its **USB-C cable**: the lighting is controlled over USB, and on Windows Creative's sound
processing is part of its USB audio driver. Nothing can be changed over Bluetooth, optical or AUX.

## Install

**Windows, easiest:** download `soundbar-autoprofile-windows-x64.exe` from
[Releases](https://github.com/esmobg/soundbar-autoprofile/releases) and run it. It shows a tray icon. The same file
also accepts every `gs5` command, for example `soundbar-autoprofile-windows-x64.exe probe`. Builds for macOS
(`…-macos-arm64.zip`) and Linux (`…-linux-x64`) are there too, still experimental.

**With Python** 3.10 or newer:

```bash
pipx install "soundbar-autoprofile[tray] @ git+https://github.com/esmobg/soundbar-autoprofile"
```

(or the same with `pip install`; leave out `[tray]` if you do not want the tray icon)

- **Windows:** install Creative App from Creative's support site and keep it installed: Sound Modes are switched
  through it.
- **Linux:** allow access to the soundbar without root, then replug it:
  `sudo cp udev/70-gs5-hidraw.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger`.
  For detection install `playerctl`, and on X11 `xdotool` and `xprop`.
- **macOS:** `brew install media-control` lets it see what browsers and other apps play, and
  `pip install pyobjc-framework-Quartz` (in the same environment) adds full-screen detection. The first run may ask
  for permission to control Spotify/Music (Automation).

## Quick start

```bash
gs5 probe                  # is the soundbar reachable?
gs5 detect --watch         # what is detected, and which profile the rules pick (Ctrl+C to stop)
gs5 set movie              # apply one profile now
gs5 tray                   # switch automatically, with a tray icon (recommended)
gs5 autostart install      # start the tray icon at login (no admin rights needed)
```

The tray menu shows the active profile and lets you pick a profile by hand (**Automatic** goes back to the rules),
**Pause**, open the config and the log folder, and turn **Start at login** on or off. Without the tray extra,
`gs5 run` does the same in a terminal and `gs5 autostart install --no-tray` starts it at login.

**Creative App:** keep it installed. It can stay minimized or in the background. If it is not running, it is
started minimized when a Sound Mode has to change (about 15 s the first time, about 2 s per switch after that).
Do not change the Sound Mode in Creative App by hand while automatic switching runs, because the next switch
overrides it. Pick a profile from the tray menu instead.

## Configure

```bash
gs5 config init            # writes the default config file
gs5 config path            # where it is
gs5 config check           # validate after editing
```

```yaml
profiles:
  music:  { sound_mode: Music,  rgb: "8a2be2", brightness: 70 }
  movie:  { sound_mode: Movies, rgb: "ff5a00", brightness: 30 }

rules:                      # top to bottom, first match wins
  - profile: work
    when: { mic_in_use: true }
  - profile: movie
    when: { media_playing: true, media_app: "vlc|netflix|plex" }
  - profile: music
    when: { media_playing: true }
```

`sound_mode` is any Sound Mode in Creative App: a factory one (Effects Off, Music, Movies, Gaming, Bass Boost,
Treble Boost, Dynamic Music, Esports, FPS, RPG and many per-game modes) or **one you made yourself**, which can
combine any EQ, SuperWide and effects. Write the name as the app shows it, in any language and any case;
`gs5 modes` lists them (`gs5 modes --select Movies` switches right away). `rgb` is one `RRGGBB` colour or 7 colours left to right, `brightness` is 0–100.

Text conditions in rules are case-insensitive regular expressions. A list means "any of these", and `unless:`
excludes matches. Available fields: `media_playing`, `media_app`, `media_title`, `media_artist`, `media_type`,
`foreground_app`, `foreground_title`, `fullscreen`, `mic_in_use`, `mic_apps`. `gs5 detect --watch` shows their
live values.

Switching waits `hold_seconds` (3), so a quick alt-tab does not flip the sound. Pausing or skipping a track counts
as still playing for `media_grace_seconds` (15).

The log, `soundbar-autoprofile.log`, is in the config folder (written by `gs5 tray` and `gs5 run --log-file`).
Problems: [Troubleshooting](docs/TROUBLESHOOTING.md). Questions: [FAQ](docs/FAQ.md).

## Add another soundbar

Implement `Device` (`soundbar_autoprofile/devices/base.py`: `apply(profile)`, `probe()`), register it in
`devices/__init__.py`, and add tests with a fake transport like `tests/test_protocol_and_gs5.py`.
`gs5 decode-capture` reads USBPcap and usbmon captures of any device. See [the capture guide](docs/CAPTURE_GUIDE.md)
and [CONTRIBUTING.md](CONTRIBUTING.md).

## Development

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,tray]"
pytest && ruff check .
```

## Credits and license

MIT. The GS5 lighting protocol comes from [JRiley2025/gs5-rgb](https://github.com/JRiley2025/gs5-rgb) (MIT); see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Not affiliated with Creative Technology Ltd.
