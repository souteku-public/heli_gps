"""測地系変換・NMEA出力試験."""

from nnn_decoder.geodesy import deg_to_dms_str, dms_to_deg, tokyo_to_wgs84, wgs84_to_tokyo
from nnn_decoder.modulator import make_data_field, make_frame
from nnn_decoder.nmea import packet_to_gga, packet_to_rmc
from nnn_decoder.packet import NNNPacketParser


def test_dms_parse():
    assert abs(dms_to_deg("354027") - (35 + 40 / 60 + 27 / 3600)) < 1e-12
    assert abs(dms_to_deg("1354027") - (135 + 40 / 60 + 27 / 3600)) < 1e-12


def test_dms_format():
    assert deg_to_dms_str(35.674167).startswith("35°40'")


def test_tokyo_wgs84_tokyo_area():
    # 東京駅付近: 東京測地系 35.681111, 139.770278 → WGS84はおよそ +11.5", -11.7"
    lat_w, lon_w = tokyo_to_wgs84(35.681111, 139.770278)
    assert abs((lat_w - 35.681111) * 3600 - 11.5) < 1.0
    assert abs((lon_w - 139.770278) * 3600 + 11.6) < 1.0


def test_roundtrip_conversion():
    lat_w, lon_w = tokyo_to_wgs84(35.0, 139.0)
    lat_t, lon_t = wgs84_to_tokyo(lat_w, lon_w)
    assert abs(lat_t - 35.0) < 1e-5
    assert abs(lon_t - 139.0) < 1e-5


def _sample_packet():
    data = make_data_field(0, 2, 8, "354027", "1394510", 500)
    return NNNPacketParser().feed(make_frame("01", data))[0]


def test_nmea_sentences():
    pkt = _sample_packet()
    gga = packet_to_gga(pkt)
    rmc = packet_to_rmc(pkt)
    assert gga.startswith("$GPGGA,") and gga.endswith("\r\n")
    assert rmc.startswith("$GPRMC,")
    # チェックサム検証
    for s in (gga, rmc):
        body, cs = s.strip()[1:].split("*")
        calc = 0
        for c in body:
            calc ^= ord(c)
        assert f"{calc:02X}" == cs
    assert ",N," in gga and ",E," in gga
