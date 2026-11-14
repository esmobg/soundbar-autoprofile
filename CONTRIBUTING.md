# Contributing

Thanks for helping. There are three useful ways to contribute, and only one of them needs programming:

1. **Capture commands for other soundbars.** Record what the manufacturer's app sends while you click its buttons
   ([capture guide](docs/CAPTURE_GUIDE.md), about 15 minutes, Windows) and submit the result. This is how support
   for a new model starts. (The GS5's EQ and effects are not sent over USB at all; see
   [docs/PROTOCOL.md](docs/PROTOCOL.md).) Android users can help with the Bluetooth side: [docs/MOBILE.md](docs/MOBILE.md).
2. **Test on your platform.** macOS and Linux are untested on real hardware. A bug report with the output of
   `gs5 probe` and `gs5 detect --watch` helps a lot.
3. **Code:** device drivers, detection, fixes.

Ask in an issue before starting something large, so we can agree on the approach first.

## Development setup

Python 3.10 or newer.

```bash
git clone https://github.com/esmobg/soundbar-autoprofile
cd soundbar-autoprofile
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e ".[dev,tray]"
```

Before you open a pull request:

```bash
pytest
ruff check .
gs5 config check                  # the default config still loads
```

CI runs the same on Windows, macOS and Linux with Python 3.10 and 3.13. Tests must not need a soundbar: talk to a
fake transport instead (see below).

## Code style

- `ruff` settings are in `pyproject.toml`: line length **120**, rules `E F W I B UP`. `ruff check . --fix` sorts
  imports.
- Type hints and `from __future__ import annotations` in new modules.
- Keep platform-specific imports inside the function or module that needs them, so the package imports everywhere.
- User-facing messages: short, plain English, and say what to do next.
- Never send a command to the soundbar that has not been recorded from the manufacturer's own app.

## Adding a device driver

A driver is a subclass of `Device` in `soundbar_autoprofile/devices/base.py`:

```python
class MyBar(Device):
    name = "mybar"

    def apply(self, profile: Profile) -> list[str]:
        """Send the profile's settings. Return a warning for each setting this device cannot apply."""

    def probe(self) -> dict[str, Any]:
        """Read-only information (USB id, firmware, what is decoded). Must not change any setting."""
```

Optional hooks: `keepalive()` (called every `keepalive_seconds`, for standby quirks) and `close()`. A `Profile`
carries `sound_mode`, `eq`, `superwide`, `rgb`, `brightness`, `lighting` and `frames`; a driver applies what its
device supports.

Steps:

1. Put the driver in `soundbar_autoprofile/devices/<model>.py`. Keep the transport (HID, serial, …) behind a
   small interface like `Transport` in `devices/gs5.py`, so tests can replace it.
2. Register it in `soundbar_autoprofile/devices/__init__.py`: add the name to `DRIVERS` and a branch in
   `open_device()`. Users then select it with `device: <name>` in the config or `gs5 --device <name> probe`.
3. Settings that are `None` in a profile mean "leave as it is". Settings the device does not support return a
   warning; they do not raise.
4. Add tests with a fake transport that answers like the real device, as `FakeGS5` does in
   `tests/test_protocol_and_gs5.py`: assert the exact frames sent, and test what happens when the device does
   not reply.
5. Document the protocol in `docs/` (or extend `docs/PROTOCOL.md`), with the firmware version you verified on and
   credit for anyone whose work you used. Add third-party code to `THIRD_PARTY_NOTICES.md`.
6. Update the status tables in `README.md` and `README.bg.md`.

`gs5 decode-capture` reads USBPcap (Windows) and usbmon (Linux) captures of any Creative HID device, so you can
use it to study a new model.

## Submitting decoded commands

1. Follow the [capture guide](docs/CAPTURE_GUIDE.md) and run `gs5 decode-capture <file> --replies`.
2. Try the frames yourself with `gs5 send …` or a profile's `frames:` list, and note what the soundbar did.
3. Open a [decoded command submission](https://github.com/esmobg/soundbar-autoprofile/issues/new?template=decoded_command.yml)
   with the decoder output, your `notes.txt`, the soundbar's firmware version and the Creative App version.

**Do not attach the raw `.pcapng`.** It records every device on that USB controller, including keystrokes.

If you want to turn the result into code yourself: new GS5 USB commands go into
`soundbar_autoprofile/devices/gs5.py` with a test in `tests/test_protocol_and_gs5.py` and a row in
`docs/PROTOCOL.md`; commands for another model go into its own driver (see above).

## Creative App Sound Modes (Windows)

The GS5's EQ, SuperWide and effects are applied by Creative's PC driver, not by the soundbar, so they are switched
by selecting a Sound Mode in Creative App through Windows UI Automation (`soundbar_autoprofile/devices/creative_app.py`,
tests in `tests/test_creative_app.py`). If Creative App's window layout changes in a new version, that module is
where to look. Keep it free of mouse clicks and keystrokes: only UI Automation patterns, so it works while the app
is minimized and never types into another window.

## Pull requests

- One topic per pull request. Describe what changed and how you tested it (on which OS, with or without hardware).
- Add an entry under *Unreleased* in [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.
- User-facing text that exists in both `README.md` and `README.bg.md` should change in both. If you do not speak
  Bulgarian, say so in the pull request and a maintainer will translate.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).

## Security

Please do not report security problems in public issues. See [SECURITY.md](SECURITY.md).
