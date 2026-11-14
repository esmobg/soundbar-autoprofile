import ctypes
import sys
import threading
import time
import types
from collections import deque

import pytest

from soundbar_autoprofile.devices import gs5 as gs5mod
from soundbar_autoprofile.devices.base import CommandError, DeviceError, Profile
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


# --- protocol ----------------------------------------------------------------------------------------------------
def test_frame_parse_ack_includes_status_byte():
    raw = bytes.fromhex("056a0203003a002501").ljust(64, b"\0")
    fr = Frame.parse(raw)
    assert (fr.op, fr.data) == (0x02, bytes.fromhex("3a002501"))  # declared length 3, status 01 included
    assert fr.hex() == "05 6a 02 03 00 3a 00 25 01"


# --- reply handling -----------------------------------------------------------------------------------------------
def _ack(cmd, status=0, op=0x3A):
    return bytes([0x05, 0x6A, 0x02, 0x03, 0x00, op, 0x00, cmd, status]).ljust(64, b"\0")


def test_stale_reports_are_flushed_before_a_request():
    g, t = _gs5()
    t.inbox.append(bytes.fromhex("056a3a02002600").ljust(64, b"\0"))  # stale "lighting off" reply
    assert g.lighting_is_on() is True


def test_get_only_accepts_the_reply_for_the_same_slot():
    class LateOtherSlot(FakeGS5):
        def write(self, report):
            if report[2] == 0x3A and report[5] == 0x2A:  # a late reply for another slot arrives first
                self._get(0x2A, [report[6] + 1, 0x03])
            super().write(report)

    g = GS5(LateOtherSlot(), timeout=0.05)
    assert g.slot_mode(1) == 0x04


def test_short_get_reply_raises_command_error():
    class Short(FakeGS5):
        def write(self, report):
            if report[2] == 0x3A and report[5] == 0x26:
                self.sent.append(report)
                self._reply(bytes.fromhex("056a3a010026"))
                return
            super().write(report)

    g = GS5(Short(), timeout=0.05)
    with pytest.raises(CommandError, match="short"):
        g.lighting_is_on()


def test_rejected_and_unanswered_commands_raise_command_error():
    class Picky(FakeGS5):
        def write(self, report):
            if report[2] == 0x3A and report[5] == 0x25:
                self.sent.append(report)
                self._reply(_ack(0x25, status=0x01))
                return
            if report[2] == 0x3A and report[5] == 0x27:
                self.sent.append(report)  # ignored
                return
            super().write(report)

    g = GS5(Picky(), timeout=0.02)
    with pytest.raises(CommandError, match="rejected"):
        g.lighting_on(True)
    with pytest.raises(CommandError, match="no reply"):
        g.set_brightness(50)


def test_dead_device_is_not_a_command_error():
    class Dead(FakeGS5):
        def read(self, timeout_s):
            return None

    with pytest.raises(DeviceError) as e:
        GS5(Dead(), timeout=0.01)
    assert not isinstance(e.value, CommandError)


def test_send_raw_rejects_frames_over_64_bytes():
    g, t = _gs5()
    n = len(t.sent)
    with pytest.raises(ValueError):
        g.send_raw(b"\x05" + bytes(64))
    assert len(t.sent) == n


def test_connect_accepts_an_ack_reply():
    class AckConnect(FakeGS5):
        def write(self, report):
            if report[2] == 0x2C:
                self.sent.append(report)
                self._reply(_ack(0x01, op=0x2C))
                return
            super().write(report)

    g = GS5(AckConnect(), timeout=0.05)
    assert g.connect_reply is not None and g.connect_reply[2] == 0x02


def test_open_closes_the_transport_when_the_handshake_fails(monkeypatch):
    class Dead(FakeGS5):
        closed = False

        def read(self, timeout_s):
            return None

        def close(self):
            Dead.closed = True

    monkeypatch.setattr(gs5mod, "HidTransport", lambda path: Dead())
    with pytest.raises(DeviceError):
        GS5.open(b"path", timeout=0.01)
    assert Dead.closed


# --- lighting behaviour -------------------------------------------------------------------------------------------
def test_lighting_true_without_rgb_turns_the_strip_on():
    g, t = _gs5()
    t.state[0x26] = [0]
    g.apply(Profile(name="on", lighting=True))
    assert t.state[0x26] == [1]
    assert g._lighting_wanted


def test_static_always_activates_slot_and_turns_lighting_on():
    g, t = _gs5()
    t.slot_modes[1] = 0x03  # already static, active and reporting on
    t.sent.clear()
    g.static("00ff00")
    cmds = _lighting_cmds(t)
    i = cmds.index(0x2B)
    assert 0x2D in cmds[i:] and 0x25 in cmds[i:]
    assert 0x29 not in cmds


@pytest.mark.parametrize("slot_mode", [0x04, 0x03])
def test_rgb_with_brightness_sets_brightness_once(slot_mode):
    g, t = _gs5()
    t.slot_modes[1] = slot_mode
    t.sent.clear()
    g.apply(Profile(name="x", rgb="8a2be2", brightness=50))
    assert _lighting_cmds(t).count(0x27) == 1
    assert t.state[0x28] == [128]


def test_keepalive_reasserts_lighting():
    g, t = _gs5()
    g.apply(Profile(name="x", rgb="ff0000"))
    t.sent.clear()
    g.keepalive()
    assert {0x2D, 0x25} <= set(_lighting_cmds(t))


def test_keepalive_respects_lighting_turned_off_by_the_user():
    g, t = _gs5()
    g.apply(Profile(name="x", rgb="ff0000"))
    t.state[0x26] = [0]  # turned off on the bar / in Creative App
    t.sent.clear()
    g.keepalive()
    assert 0x25 not in _lighting_cmds(t) and 0x2D not in _lighting_cmds(t)
    assert not g._lighting_wanted
    t.sent.clear()
    g.keepalive()
    assert t.sent == []


def test_public_calls_do_not_interleave_across_threads():
    class Slow(FakeGS5):
        def __init__(self):
            super().__init__()
            self.who: list[str] = []

        def write(self, report):
            time.sleep(0.002)
            super().write(report)
            self.who.append(threading.current_thread().name)

    t = Slow()
    g = GS5(t, timeout=0.05)
    t.who.clear()
    start = threading.Barrier(2)

    def run():
        start.wait()
        g.apply(Profile(name="x", lighting=True, brightness=40))

    threads = [threading.Thread(target=run, name=f"t{i}") for i in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    changes = sum(1 for a, b in zip(t.who, t.who[1:], strict=False) if a != b)
    assert len(t.who) == 4 and changes == 1


# --- hidapi backend selection -------------------------------------------------------------------------------------
def _fake_hidmod(name, open_error=None, devices=()):
    mod = types.ModuleType(name)
    mod.__file__ = f"/fake/{name}.so"
    mod.calls = []

    class Dev:
        def open_path(self, path):
            if open_error:
                raise OSError(open_error)

        def set_nonblocking(self, v):
            pass

        def close(self):
            pass

    def enumerate_(vid=0, pid=0):
        mod.calls.append((vid, pid))
        return list(devices)

    mod.device = Dev
    mod.enumerate = enumerate_
    return mod


def test_linux_prefers_the_hidraw_backend(monkeypatch):
    hid, hidraw = _fake_hidmod("hid"), _fake_hidmod("hidraw")
    monkeypatch.setitem(sys.modules, "hid", hid)
    monkeypatch.setitem(sys.modules, "hidraw", hidraw)
    monkeypatch.setattr(sys, "platform", "linux")
    assert gs5mod._hidapi() is hidraw
    monkeypatch.setitem(sys.modules, "hidraw", None)  # not importable
    assert gs5mod._hidapi() is hid
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "hidraw", hidraw)
    assert gs5mod._hidapi() is hid


def test_find_paths_uses_the_selected_backend(monkeypatch):
    devs = [{"path": b"/dev/hidraw3", "usage_page": 0xFF01, "interface_number": 0},
            {"path": b"/dev/hidraw4", "usage_page": 0x000C, "interface_number": 1}]
    monkeypatch.setitem(sys.modules, "hidraw", _fake_hidmod("hidraw", devices=devs))
    monkeypatch.setitem(sys.modules, "hid", _fake_hidmod("hid"))
    monkeypatch.setattr(sys, "platform", "linux")
    assert gs5mod.find_paths() == [b"/dev/hidraw3"]


def test_macos_turns_off_exclusive_open(monkeypatch):
    hid = _fake_hidmod("hid")
    calls = []

    class Lib:
        def hid_darwin_set_open_exclusive(self, v):
            calls.append(v)

    monkeypatch.setitem(sys.modules, "hid", hid)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ctypes, "CDLL", lambda path: Lib() if path == hid.__file__ else None)
    assert gs5mod._hidapi() is hid
    assert hid.calls == [(0, 0)] and calls == [0]

    def missing(path):
        raise OSError("no such library")

    monkeypatch.setattr(ctypes, "CDLL", missing)
    assert gs5mod._hidapi() is hid  # hidapi without the call is still usable


@pytest.mark.parametrize("platform,hint", [("linux", "udev"), ("darwin", "Input Monitoring"), ("win32", "replug")])
def test_open_error_hint_is_os_specific(monkeypatch, platform, hint):
    mod = _fake_hidmod("hid", open_error="open failed")
    monkeypatch.setitem(sys.modules, "hid", mod)
    monkeypatch.setitem(sys.modules, "hidraw", None)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(ctypes, "CDLL", lambda path: types.SimpleNamespace(hid_darwin_set_open_exclusive=int))
    with pytest.raises(DeviceError, match=hint):
        gs5mod.HidTransport(b"path")
