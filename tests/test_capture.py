import struct

from soundbar_autoprofile.capture import CapturedFrame, bursts, polling_frames, read_frames, reply_to
from soundbar_autoprofile.protocol import build_frame


def _block(btype: int, body: bytes) -> bytes:
    body += b"\0" * (-len(body) % 4)
    n = 12 + len(body)
    return struct.pack("<II", btype, n) + body + struct.pack("<I", n)


def _usbpcap(endpoint: int, data: bytes, transfer: int = 1, info: int | None = None, stage: int = 0) -> bytes:
    # headerLen, irpId, status, function, info, bus, device, endpoint, transfer, dataLength (+ stage for control)
    if info is None:  # OUT data rides on the submit (info 0), IN data on the completion (info 1)
        info = 1 if endpoint & 0x80 else 0
    extra = bytes([stage]) if transfer == 2 else b""
    hdr = struct.pack("<HQIHBHHBBI", 27 + len(extra), 1, 0, 0x09, info, 1, 5, endpoint, transfer, len(data))
    return hdr + extra + data


def _pcapng(packets: list[tuple[float, bytes]]) -> bytes:
    out = _block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    out += _block(1, struct.pack("<HHI", 249, 0, 65535))
    for t, pkt in packets:
        ts = int(t * 1e6)
        out += _block(6, struct.pack("<IIIII", 0, ts >> 32, ts & 0xFFFFFFFF, len(pkt), len(pkt)) + pkt)
    return out


def test_usbpcap_pcapng(tmp_path):
    poll = build_frame(0x2C, [0x01])
    cmd_a = build_frame(0x77, [0x01, 0x02])
    cmd_b = build_frame(0x77, [0x01, 0x03])
    ack = bytes.fromhex("056a020300770001").ljust(64, b"\0")
    packets = []
    for i in range(6):
        packets.append((i * 1.0, _usbpcap(0x03, poll)))
    packets += [(10.0, _usbpcap(0x03, cmd_a)), (10.02, _usbpcap(0x82, ack)),
                (20.0, _usbpcap(0x03, cmd_b)), (30.0, _usbpcap(0x03, b"\x01\x02\x03"))]
    f = tmp_path / "cap.pcapng"
    f.write_bytes(_pcapng(packets))

    frames = read_frames(f)
    assert len(frames) == 9                     # 6 polls + 2 commands + 1 ack; junk ignored
    groups = bursts(frames)
    assert [[fr.hex() for fr in g] for g in groups] == [["05 6a 77 02 00 01 02"], ["05 6a 77 02 00 01 03"]]
    assert reply_to(frames, groups[0][0]).hex() == "05 6a 02 03 00 77 00 01 00"  # ACK keeps its status byte
    assert len(bursts(frames, keep_polling=True)) == 3  # polls 0-5 s form one burst


def _usbmon(endpoint: int, data: bytes, transfer: int = 1) -> bytes:
    hdr = bytearray(64)
    hdr[9], hdr[10] = transfer, endpoint
    return bytes(hdr) + data


def _pcap(packets: list[bytes], linktype: int = 220) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype)
    for i, pkt in enumerate(packets):
        out += struct.pack("<IIII", 5 + i, 0, len(pkt), len(pkt)) + pkt
    return out


def test_usbmon_pcap(tmp_path):
    cmd = build_frame(0x77, [0x05])
    f = tmp_path / "cap.pcap"
    f.write_bytes(_pcap([_usbmon(0x03, cmd),
                         _usbmon(0x01, cmd, transfer=0),     # isochronous: never HID
                         _usbmon(0x02, cmd, transfer=3)]))   # bulk: never HID
    frames = read_frames(f)
    assert [(fr.direction, fr.hex()) for fr in frames] == [("out", "05 6a 77 01 00 05")]


def test_isochronous_audio_that_looks_like_a_frame_is_ignored(tmp_path):
    audio = bytes.fromhex("056a1102000102") + bytes(185)   # PCM samples that happen to start with 05 6a
    cmd = build_frame(0x77, [0x01])
    f = tmp_path / "cap.pcapng"
    f.write_bytes(_pcapng([(0.0, _usbpcap(0x01, audio, transfer=0)), (0.001, _usbpcap(0x02, audio, transfer=3)),
                           (0.5, _usbpcap(0x03, cmd))]))
    assert [fr.hex() for fr in read_frames(f)] == ["05 6a 77 01 00 01"]


def test_interrupt_direction_must_match_the_urb_stage(tmp_path):
    cmd = build_frame(0x77, [0x01])
    reply = build_frame(0x77, [0x02])
    f = tmp_path / "cap.pcapng"
    f.write_bytes(_pcapng([(0.0, _usbpcap(0x03, cmd, info=0)),     # OUT submit: the data
                           (0.01, _usbpcap(0x03, cmd, info=1)),    # OUT completion: echo, dropped
                           (0.02, _usbpcap(0x82, reply, info=0)),  # IN submit: empty buffer, dropped
                           (0.03, _usbpcap(0x82, reply, info=1))]))
    assert [(fr.direction, fr.hex()) for fr in read_frames(f)] == [("out", "05 6a 77 01 00 01"),
                                                                   ("in", "05 6a 77 01 00 02")]


def test_control_set_and_get_report_direction_from_info(tmp_path):
    setup = bytes.fromhex("2109050302004000")   # SET_REPORT, output report 5
    cmd = build_frame(0x77, [0x01])
    reply = build_frame(0x2C, [0x00, 0x01])
    f = tmp_path / "cap.pcapng"
    f.write_bytes(_pcapng([(0.0, _usbpcap(0x00, setup + cmd, transfer=2, info=0, stage=0)),
                           (0.05, _usbpcap(0x80, reply, transfer=2, info=1, stage=3))]))
    frames = read_frames(f)
    assert [(fr.direction, fr.hex()) for fr in frames] == [("out", "05 6a 77 01 00 01"),
                                                           ("in", "05 6a 2c 02 00 00 01")]


def test_frame_length_is_validated(tmp_path):
    empty = bytes.fromhex("056a7700000102").ljust(64, b"\0")       # declares 0 data bytes
    too_long = bytes.fromhex("056a774000").ljust(64, b"\1")        # 5 + 64 > 64
    ok = build_frame(0x77, [0x01])
    f = tmp_path / "cap.pcapng"
    f.write_bytes(_pcapng([(0.0, _usbpcap(0x03, empty)), (0.1, _usbpcap(0x03, too_long)),
                           (0.2, _usbpcap(0x03, ok))]))
    assert [fr.hex() for fr in read_frames(f)] == ["05 6a 77 01 00 01"]


def _out(t: float, data: bytes) -> CapturedFrame:
    return CapturedFrame(t, "out", data)


def test_polling_comes_from_the_idle_window():
    poll_a, poll_b = build_frame(0x2C, [0x01]), build_frame(0x2C, [0x02])
    cmd = build_frame(0x77, [0x01])
    frames = [_out(0.0, poll_a), _out(5.0, poll_b),              # idle: each seen once only
              _out(12.0, poll_a), _out(12.1, poll_b), _out(12.2, cmd),
              _out(20.0, cmd), _out(25.0, cmd), _out(30.0, cmd)]  # a setting clicked 4 times is not polling
    assert polling_frames(frames) == {poll_a, poll_b}
    groups = bursts(frames)
    assert [[fr.time for fr in g] for g in groups] == [[12.2], [20.0], [25.0], [30.0]]
    assert len(bursts(frames, keep_polling=True)) == 6


def test_polling_falls_back_to_repeat_count_without_idle_frames():
    poll, cmd = build_frame(0x2C, [0x01]), build_frame(0x77, [0x01])
    frames = [CapturedFrame(0.0, "in", poll)] + [_out(11.0 + i * 3, poll) for i in range(4)] + [_out(30.0, cmd)]
    assert polling_frames(frames) == {poll}
    assert [[fr.time for fr in g] for g in bursts(frames)] == [[30.0]]
    assert polling_frames(frames, idle_seconds=0, poll_threshold=5) == set()
