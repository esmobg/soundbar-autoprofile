# Sound Blaster GS5 USB protocol

Unofficial. The framing and lighting commands were reverse-engineered by
[JRiley2025/gs5-rgb](https://github.com/JRiley2025/gs5-rgb/blob/main/PROTOCOL.md) (MIT); read that document for full
lighting details. This page summarises what soundbar-autoprofile uses and tracks what is still unknown.

## Device

| | |
|---|---|
| USB ID | `041e:329d` |
| Control interface | interface 0, HID vendor usage page `0xFF01`, report ID `05`, 64-byte reports |
| Same interface | report ID `02` = consumer-control keys (the bar's buttons) |
| Bluetooth | not controllable through this interface; only USB-C works |

Verified on Windows 11 with hidapi 0.15 (Creative App 1.x running at the same time does not block it).

## Framing

```
05 6a <op> <len lo> <len hi> <data ...>     zero-padded to 64 bytes
```

- Set ACK: `05 6a 02 03 00 <op> 00 <cmd> <status>` (`00` = OK)
- Get reply: `05 6a <op> <len> <cmd> <value ...>`
- Send one command, **wait for its reply**, then the next: commands written back to back are ignored.

| Frame | Meaning |
|---|---|
| `05 6a 09 01 00 00` | hello; reply contains the vendor id `1e 04` |
| `05 6a 2c 01 00 01` | sent by Creative App on connect |
| `05 6a 3a …` | lighting (below) |
| `05 6a 42 …`, `05 6a 4a …`, `05 5a 6c …` | polled by Creative App; **meaning unknown — probably audio settings** |

## Lighting (op `3a`) — decoded

| Command | Meaning |
|---|---|
| `25 <0/1>` / `26` | lighting off/on / get |
| `27 <00-ff>` / `28` | brightness / get |
| `29 <slot> <mode>` / `2a <slot>` | put a mode in slot 1-6 / get (static `03`, cycle `01`, wave `04`, aurora `08`, glowing `09`, peak `0a`, chasers `0b`) |
| `2d <slot>` / `2e` | activate slot / get active |
| `2b <slot> 01 01 <7 × ff B G R>` | static colours, segment 1 = leftmost |

## EQ, SuperWide, other audio settings — **not decoded yet**

Help wanted: follow [CAPTURE_GUIDE.md](CAPTURE_GUIDE.md). Results go here and into `EQ_PRESETS` / `SUPERWIDE` in
`soundbar_autoprofile/devices/gs5.py`.

| Setting | Frames | Verified on firmware |
|---|---|---|
| EQ presets | ? | |
| Custom EQ bands | ? | |
| SuperWide on/off | ? | |
