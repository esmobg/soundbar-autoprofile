import struct

from soundbar_autoprofile.capture import bursts, read_frames, reply_to
from soundbar_autoprofile.protocol import build_frame


def _block(btype: int, body: bytes) -> bytes:
    body += b"\0" * (-len(body) % 4)
    n = 12 + len(body)
    return struct.pack("<II", btype, n) + body + struct.pack("<I", n)


def _usbpcap(endpoint: int, data: bytes) -> bytes:
    # headerLen, irpId, status, function, info, bus, device, endpoint, transfer, dataLength
    hdr = struct.pack("<HQIHBHHBBI", 27, 1, 0, 0x09, 0, 1, 5, endpoint, 1, len(data))
    return hdr + data


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
    assert reply_to(frames, groups[0][0]).direction == "in"
    assert len(bursts(frames, keep_polling=True)) == 3  # polls 0-5 s form one burst


def test_usbmon_pcap(tmp_path):
    cmd = build_frame(0x77, [0x05])
    hdr = bytearray(64)
    hdr[10] = 0x03  # endpoint OUT
    pkt = bytes(hdr) + cmd
    pcap = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 220)
    pcap += struct.pack("<IIII", 5, 0, len(pkt), len(pkt)) + pkt
    f = tmp_path / "cap.pcap"
    f.write_bytes(pcap)
    frames = read_frames(f)
    assert [(fr.direction, fr.hex()) for fr in frames] == [("out", "05 6a 77 01 00 05")]
