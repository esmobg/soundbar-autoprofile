# soundbar-autoprofile

**Your soundbar switches its sound profile by itself: music → Music, movie → Movie, meeting/work → Voice,
game → Game.** It starts with the Creative Sound Blaster GS5 and is built so that more soundbars can be added.

[Български](README.bg.md)

It watches what is playing (Spotify, VLC, Netflix, YouTube…), which app is in front, whether the screen is
full-screen and whether the microphone is in use. Then it picks a profile from your rules and applies it to the
soundbar over USB.

## Status

| Feature (Sound Blaster GS5) | |
|---|---|
| RGB colour / brightness per profile | ✅ works |
| EQ preset per profile | 🔬 command not decoded yet: [help by recording 15 min of USB traffic](docs/CAPTURE_GUIDE.md) |
| SuperWide on/off per profile | 🔬 same as above |
| Your own captured commands (`frames:`) | ✅ works |

| Platform | What it detects | Status |
|---|---|---|
| Windows 10/11 | media sessions (any player/browser), focused app, full-screen, microphone use | ✅ tested |
| macOS | focused app, Spotify/Music playback | ⚠️ untested on hardware |
| Linux (X11) | MPRIS players (`playerctl`), focused app (`xdotool`), microphone (`pactl`) | ⚠️ untested on hardware |
| Linux (Wayland) | MPRIS players and microphone only (Wayland hides the focused window) | ⚠️ |
| Android | planned: companion app over Bluetooth once the BLE protocol is decoded | 🗺️ |
| iOS | not possible: iOS lets no app watch other apps' playback or talk to the soundbar in the background | ❌ |

The soundbar must be connected with its **USB-C cable**: the settings cannot be changed over Bluetooth,
optical or AUX. Audio can still come in over any input.

## Install

Python 3.10 or newer, then:

```bash
pipx install git+https://github.com/esmobg/soundbar-autoprofile
```

(or `pip install git+https://github.com/esmobg/soundbar-autoprofile`)

- **Linux:** allow access to the soundbar without root, then replug it:
  `sudo cp udev/70-gs5-hidraw.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger`.
  For detection install `playerctl` and, on X11, `xdotool`.
- **macOS:** the first run may ask for permission to control Spotify/Music (Automation). That is needed to read
  what they play.

## Quick start

```bash
gs5 probe                  # is the soundbar reachable?
gs5 detect --watch         # what is detected, and which profile the rules pick (Ctrl+C to stop)
gs5 set movie              # apply one profile now
gs5 run                    # switch automatically (Ctrl+C to stop)
gs5 autostart install      # start at login (no admin rights needed)
```

**Close Creative App** (and remove it from startup) while this runs: it also sends settings to the soundbar and
can undo the changes.

## Configure

```bash
gs5 config init            # writes the default config file
gs5 config path            # where it is
gs5 config check           # validate after editing
```

```yaml
profiles:
  music:  { eq: music, rgb: "8a2be2", brightness: 70 }
  movie:  { eq: movie, superwide: true, rgb: "ff5a00", brightness: 30 }

rules:                      # top to bottom, first match wins
  - profile: work
    when: { mic_in_use: true }
  - profile: movie
    when: { media_playing: true, media_app: "vlc|netflix|plex" }
  - profile: music
    when: { media_playing: true }
```

Text conditions are case-insensitive regular expressions. A list means "any of these", and `unless:` excludes
matches. Available fields: `media_playing`, `media_app`, `media_title`, `media_artist`, `media_type`,
`foreground_app`, `foreground_title`, `fullscreen`, `mic_in_use`, `mic_apps`. `gs5 detect --watch` shows their
live values.

Switching waits `hold_seconds` (3), so a quick alt-tab does not flip the sound. Pausing or skipping a track counts
as still playing for `media_grace_seconds` (15).

Logs from `gs5 run --log-file` (used by autostart) are in the config folder.

## Help decode the EQ

Have a GS5 and Windows? [The capture guide](docs/CAPTURE_GUIDE.md) takes about 15 minutes and needs no programming.
Protocol notes: [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Add another soundbar

Implement `Device` (`soundbar_autoprofile/devices/base.py`: `apply(profile)`, `probe()`), register it in
`devices/__init__.py`, and add tests with a fake transport like `tests/test_protocol_and_gs5.py`.
`gs5 decode-capture` reads USBPcap and usbmon captures of any device.

## Development

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest && ruff check .
```

## Credits and license

MIT. The GS5 lighting protocol comes from [JRiley2025/gs5-rgb](https://github.com/JRiley2025/gs5-rgb) (MIT); see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Not affiliated with Creative Technology Ltd.
