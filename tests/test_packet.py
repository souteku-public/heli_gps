"""パケットパーサ単体試験."""

from nnn_decoder.modulator import make_data_field, make_frame
from nnn_decoder.packet import NNNPacketParser


def test_parse_normal_frame():
    data = make_data_field(0, 2, 8, "354027", "1394510", 500)
    frame = make_frame("01", data)
    parser = NNNPacketParser()
    pkts = parser.feed(frame)
    assert len(pkts) == 1
    assert pkts[0].fix_status == 0
    assert pkts[0].alt_m == 500
    assert parser.packets_ok == 1


def test_bcc_error_rejected():
    data = make_data_field(0, 2, 8, "354027", "1394510", 500)
    frame = bytearray(make_frame("01", data))
    frame[10] ^= 0x01  # データを1bit破壊
    parser = NNNPacketParser()
    pkts = parser.feed(bytes(frame))
    assert pkts == []
    assert parser.packets_error >= 1


def test_split_feed():
    """フレームが分割されて届いても復元できること."""
    data = make_data_field(1, None, None, "204059", "1200000", 0)
    frame = make_frame("FF", data)
    parser = NNNPacketParser()
    pkts = []
    for i in range(len(frame)):
        pkts.extend(parser.feed(frame[i : i + 1]))
    assert len(pkts) == 1
    p = pkts[0]
    assert p.fix_status == 1
    assert p.pdop is None
    assert p.satellites is None
    assert p.station_id == "FF"


def test_out_of_range_flagged():
    data = make_data_field(0, 2, 8, "554027", "1394510", 500)  # 北緯55度
    frame = make_frame("01", data)
    pkts = NNNPacketParser().feed(frame)
    assert len(pkts) == 1
    assert not pkts[0].in_range


def test_garbage_before_frame():
    data = make_data_field(0, 2, 8, "354027", "1394510", 120)
    frame = make_frame("01", data)
    parser = NNNPacketParser()
    pkts = parser.feed(b"\x55\x55\x7f\x00garbage" + frame)
    assert len(pkts) == 1
    assert pkts[0].alt_m == 120
