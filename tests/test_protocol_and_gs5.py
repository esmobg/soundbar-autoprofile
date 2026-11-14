from collections import deque

import pytest

from soundbar_autoprofile.devices.base import DeviceError, Profile
from soundbar_autoprofile.devices.gs5 import GS5, Transport
from soundbar_autoprofile.protocol import Frame, build_frame, parse_hex


def test_build_frame_pads_to_64_bytes():
    f = build_frame(0x3A, [0x25, 0x01])
    assert len(f) == 64
    assert f[:7] == bytes.fromhex("056a3a02002501")
    assert set(f[7:]) == {0}


def test_build_frame_rejects_oversized_data():
    with pytest.raises(ValueError):
        build_frame(0x3A, bytes(60))


def test_parse_hex_accepts_spaces_and_0x():
    assert parse_hex("05 6a 0x09,01:00 00") == bytes.fromhex("056a09010000")


def test_frame_parse_roundtrip():
    fr = Frame.parse(build_frame(0x3A, [0x26]))
    assert (fr.op, fr.data) == (0x3A, b"\x26")
    assert fr.hex() == "05 6a 3a 01 00 26"


class FakeGS5(Transport):
    """Answers like the real soundbar: ACKs sets, answers gets from a small state table."""

    def __init__(self):
        self.sent: list[bytes] = []
        self.inbox: deque[bytes] = deque()
        self.state = {0x26: [1], 0x28: [0xFF], 0x2E: [1]}
        self.slot_modes = {s: 0x04 for s in range(1, 7)}

    def write(self, report: bytes) -> None:
        assert len(report) == 64
        self.sent.append(report)
        op, n = report[2], report[3] | report[4] << 8
        data = report[5 : 5 + n]
        if op == 0x09:
            self._reply(bytes.fromhex("056a091100000000000001 1e04 9d32".replace(" ", "")))
        elif op == 0x2C:
            self._reply(bytes.fromhex("056a2c0100"))
        elif op == 0x3A:
            cmd = data[0]
            if cmd in (0x26, 0x28, 0x2E):
                self._get(cmd, self.state[cmd])
            elif cmd == 0x2A:
                self._get(cmd, [data[1], self.slot_modes[data[1]]])
            else:
                if cmd == 0x29:
                    self.slot_modes[data[1]] = data[2]
                    self.state[0x28] = [0xB0]
                if cmd == 0x25:
                    self.state[0x26] = [data[1]]
                if cmd == 0x27:
                    self.state[0x28] = [data[1]]
                if cmd == 0x2D:
                    self.state[0x2E] = [data[1]]
                self._reply(bytes([0x05, 0x6A, 0x02, 0x03, 0x00, 0x3A, 0x00, cmd, 0x00]))

    def _get(self, cmd, value):
        self._reply(bytes([0x05, 0x6A, 0x3A, 1 + len(value), 0, cmd, *value]))

    def _reply(self, b: bytes) -> None:
        self.inbox.append(b.ljust(64, b"\0"))

    def read(self, timeout_s):
        return self.inbox.popleft() if self.inbox else None


def _gs5():
    t = FakeGS5()
    return GS5(t, timeout=0.05), t


def _lighting_cmds(t):
    return [r[5] for r in t.sent if r[2] == 0x3A]


def test_handshake_sends_hello_then_connect():
    g, t = _gs5()
    assert [r[2] for r in t.sent[:2]] == [0x09, 0x2C]
    assert g.hello_reply.startswith(b"\x05\x6a\x09")


def test_static_colour_switches_mode_and_sends_bgr():
    g, t = _gs5()
    g.static("ff8000")
    cmds = _lighting_cmds(t)
    assert 0x29 in cmds  # slot was "wave", switched to static
    colour = next(r for r in t.sent if r[2] == 0x3A and r[5] == 0x2B)
    assert colour[6:9] == bytes([1, 1, 1])
    assert colour[9:13] == bytes([0xFF, 0x00, 0x80, 0xFF])  # ff B G R
    # mode change reset brightness to b0; it is restored to ff
    assert t.state[0x28] == [0xFF]


def test_apply_warns_for_undecoded_settings_and_sends_raw_frames():
    g, t = _gs5()
    warnings = g.apply(Profile(name="x", eq="music", superwide=True, frames=["05 6a 2c 01 00 01"]))
    assert len(warnings) == 2
    assert t.sent[-1][:6] == bytes.fromhex("056a2c010001")


def test_lighting_off_profile():
    g, t = _gs5()
    g.apply(Profile(name="off", lighting=False))
    assert t.state[0x26] == [0]


def test_no_reply_raises():
    class Dead(FakeGS5):
        def read(self, timeout_s):
            return None

    with pytest.raises(DeviceError):
        GS5(Dead(), timeout=0.01)
