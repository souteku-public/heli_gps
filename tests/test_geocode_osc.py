"""逆ジオコーディング・OSC出力の試験(ネットワーク不要)."""

import io
import json

import nnn_decoder.geocode as geocode
from nnn_decoder.geocode import Address, ReverseGeocoder
from nnn_decoder.modulator import make_data_field, make_frame
from nnn_decoder.osc import osc_message
from nnn_decoder.packet import NNNPacketParser


def test_muni_table_loaded():
    geo = ReverseGeocoder()
    assert geo.muni_name("12106") == ("千葉県", "千葉市美浜区")
    assert geo.muni_name("13101") == ("東京都", "千代田区")
    # 先頭ゼロ付きコードも解決できること
    assert geo.muni_name("01100") == ("北海道", "札幌市")


def test_address_text_levels():
    a = Address(pref="千葉県", city="千葉市美浜区", town="幕張西三丁目")
    assert a.text("pref") == "千葉県"
    assert a.text("muni") == "千葉県千葉市"           # 政令市の区を省く
    assert a.text("city") == "千葉県千葉市美浜区"      # 区あり
    assert a.text("town") == "千葉県千葉市美浜区幕張西三丁目"


def test_address_muni_special_ward():
    # 東京特別区は「市」を含まないのでそのまま
    a = Address(pref="東京都", city="千代田区")
    assert a.text("muni") == "東京都千代田区"
    # 政令市(区あり)
    b = Address(pref="静岡県", city="浜松市中央区")
    assert b.text("muni") == "静岡県浜松市"


def test_address_offshore_suffix():
    a = Address(pref="千葉県", city="市原市", offshore=True)
    assert a.text("muni") == "千葉県市原市沖"
    assert ("{address}上空").format(address=a.text("muni")) == "千葉県市原市沖上空"


def test_offline_offshore_nearest():
    """海上では最寄り市町村+沖になること(ネットワーク不要)."""
    geo = ReverseGeocoder(mode="offline", min_interval_s=0.0, min_move_m=0.0)
    a = geo.lookup(35.55, 140.05, force=True)   # 東京湾上
    assert a is not None
    assert a.offshore is True
    assert a.text("muni").endswith("沖")
    assert a.pref  # 都道府県が入っている


def test_lookup_with_mocked_api(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return io.BytesIO(json.dumps(
            {"results": {"muniCd": "12106", "lv01Nm": "幕張西三丁目"}}
        ).encode())

    monkeypatch.setattr(geocode.urllib.request, "urlopen", fake_urlopen)
    geo = ReverseGeocoder(min_interval_s=0.0, min_move_m=150.0, mode="online")
    a = geo.lookup(35.6624, 140.0384)
    assert a.text("city") == "千葉県千葉市美浜区"
    # 150m未満の移動では再問い合わせしない
    geo.lookup(35.6625, 140.0384)
    assert len(calls) == 1
    # 大きく動けば再問い合わせ
    geo.lookup(35.70, 140.10)
    assert len(calls) == 2


def test_lookup_network_error_keeps_last(monkeypatch):
    ok = {"flag": True}

    def fake_urlopen(req, timeout=None):
        if not ok["flag"]:
            raise OSError("network down")
        return io.BytesIO(json.dumps(
            {"results": {"muniCd": "13101", "lv01Nm": ""}}).encode())

    monkeypatch.setattr(geocode.urllib.request, "urlopen", fake_urlopen)
    geo = ReverseGeocoder(min_interval_s=0.0, min_move_m=0.0, mode="online")
    a1 = geo.lookup(35.68, 139.75)
    assert a1.city == "千代田区"
    ok["flag"] = False
    a2 = geo.lookup(36.00, 140.00)   # 通信断 → 前回値保持
    assert a2.city == "千代田区"
    assert geo.error_count == 1


def test_offline_lookup_known_points():
    """同梱境界データによるオフライン判定(ネットワーク不要)."""
    geo = ReverseGeocoder(mode="offline", min_interval_s=0.0, min_move_m=0.0)
    cases = [
        (35.6624, 140.0384, "千葉市美浜区"),   # 実収録データの開始点
        (35.681111, 139.767, "千代田区"),      # 東京駅
        (43.0621, 141.3544, "札幌市中央区"),
        (34.7108, 137.7261, "浜松市中央区"),   # 2024年再編後の新区名
        (26.2124, 127.6809, "那覇市"),
    ]
    for lat, lon, city in cases:
        a = geo.lookup(lat, lon, force=True)
        assert a is not None and a.city == city, (lat, lon, a)

    # 海上は最寄り市町村+沖(offshore=True)を返す
    a = geo.lookup(39.0, 143.5, force=True)   # 三陸沖
    assert a is not None and a.offshore is True
    assert a.text("muni").endswith("沖")


def test_offline_no_network_access(monkeypatch):
    """offlineモードではAPIに一切アクセスしないこと."""
    def boom(*a, **k):
        raise AssertionError("offlineモードでAPIが呼ばれた")
    monkeypatch.setattr(geocode.urllib.request, "urlopen", boom)
    geo = ReverseGeocoder(mode="offline", min_interval_s=0.0, min_move_m=0.0)
    a = geo.lookup(35.681111, 139.767, force=True)
    assert a.city == "千代田区"
    assert geo.error_count == 0


def test_osc_message_encoding():
    msg = osc_message("/heli/position", 35.5, 140.0, 620.0)
    # アドレスは4バイト境界にパディング
    assert msg.startswith(b"/heli/position\x00\x00")
    assert b",fff" in msg
    assert len(msg) % 4 == 0

    msg2 = osc_message("/heli/address", "千葉県千葉市美浜区")
    assert b",s\x00\x00" in msg2
    assert "千葉県千葉市美浜区".encode() in msg2
    assert len(msg2) % 4 == 0

    msg3 = osc_message("/heli/status", 0, 9, "01")
    assert b",iis" in msg3
    assert len(msg3) % 4 == 0


def test_osc_send_packet_smoke():
    """UDP送信のスモークテスト(自ホストの空きポートへ)."""
    import socket

    from nnn_decoder.osc import OscSender

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    port = rx.getsockname()[1]

    data = make_data_field(0, 2, 8, "354027", "1394510", 500)
    pkt = NNNPacketParser().feed(make_frame("01", data))[0]

    tx = OscSender("127.0.0.1", port)
    tx.send_packet(pkt, "千葉県千葉市美浜区")
    seen = set()
    for _ in range(3):
        payload = rx.recv(2048)
        seen.add(payload.split(b"\x00")[0])
    assert b"/heli/position" in seen
    assert b"/heli/address" in seen
    assert b"/heli/status" in seen
    tx.close()
    rx.close()
