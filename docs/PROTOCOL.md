# Sound Blaster GS5 USB protocol

Unofficial. The framing and lighting commands were reverse-engineered by
[JRiley2025/gs5-rgb](https://github.com/JRiley2025/gs5-rgb/blob/main/PROTOCOL.md) (MIT); read that document for full
lighting details. This page summarises what soundbar-autoprofile uses and what we found out about the audio
settings.

## Device

| | |
|---|---|
| USB ID | `041e:329d` |
| Control interface | interface 0, HID vendor usage page `0xFF01`, report ID `05`, 64-byte reports |
| Same interface | report ID `02` = consumer-control keys (the bar's buttons) |
| Bluetooth | not controllable through this interface; only USB-C works |

Verified on Windows 11 with hidapi 0.15 and Creative App 1.24.5. Creative App running at the same time does not
block it.

## Framing

```
05 6a <op> <len lo> <len hi> <data ...>     zero-padded to 64 bytes
```

- Set ACK: `05 6a 02 03 00 <op> 00 <cmd> <status>` (`00` = OK)
- Get reply: `05 6a <op> <len> <cmd> <value ...>`
- Send one command, **wait for its reply**, then the next: commands written back to back are ignored.

## What Creative App sends at startup

| Frame | Meaning |
|---|---|
| `05 6a 09 01 00 00` | hello; reply contains the vendor id `1e 04` |
| `09 08` | firmware information |
| `3a 1f …`, `3a 20 …` | lighting queries (exact meaning not documented here yet) |
| `05 6a 2c 01 00 01` | sent on connect |
| `05 6a 42 …` | unknown; the reply is `05 6a 42 04 00 60 60 42`, meaning unknown |

Earlier notes also listed `05 6a 4a …` and `05 5a 6c …` as polled by the app; their meaning is unknown too.
`gs5 listen` prints everything the soundbar sends, so you can watch the replies while you use Creative App.

## Lighting (op `3a`)

| Command | Meaning |
|---|---|
| `25 <0/1>` / `26` | lighting off/on / get |
| `27 <00-ff>` / `28` | brightness / get |
| `29 <slot> <mode>` / `2a <slot>` | put a mode in slot 1-6 / get (static `03`, cycle `01`, wave `04`, aurora `08`, glowing `09`, peak `0a`, chasers `0b`) |
| `2d <slot>` / `2e` | activate slot / get active |
| `2b <slot> 01 01 <7 × ff B G R>` | static colours, segment 1 = leftmost |

## EQ, SuperWide and other audio settings: not on the USB interface

EQ, SuperWide (called "Surround" inside Creative App), Crystalizer, Bass, Smart Volume and Dialog+ are **not sent
to the soundbar**. We listened on the HID interface while changing each of them in Creative App and nothing was
sent. Creative's audio-driver plugin (`CTUSBAPO64.dll`, an audio processing object installed by Creative's driver
INF) applies them to the audio stream on the PC; Creative App only configures that plugin.

Consequences:

- There is nothing to decode over USB for these settings on Windows, and no way to apply them on macOS or Linux,
  where the soundbar plays without Creative's processing.
- soundbar-autoprofile switches them by picking a **Sound Mode** in Creative App through Windows UI Automation
  (`sound_mode:` in a profile; `soundbar_autoprofile/devices/creative_app.py`). A Sound Mode bundles all of the
  settings above. Modes can be named by display name, internal name or GUID.
- The `eq:` and `superwide:` profile keys still exist for devices that do take such commands. On the GS5 they only
  produce a warning that points to `sound_mode`.

Still worth capturing (see [CAPTURE_GUIDE.md](CAPTURE_GUIDE.md)): other soundbars, the Bluetooth link
([MOBILE.md](MOBILE.md)), and future GS5 firmware or Creative App versions in case this changes.
