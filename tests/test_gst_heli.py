"""GStreamer版アプリの中核(描画・復調→文字列)の試験.

GStreamer本体(gi)には依存しない部分だけを検証する。
"""

import numpy as np

from gst_heli.decoder_core import HeliConfig, HeliDecoder
from gst_heli.renderer import SuperRenderer, SuperStyle
from nnn_decoder.modulator import encode_position_to_audio


def test_renderer_shape_and_alpha():
    r = SuperRenderer(1920, 1080, SuperStyle(font_size=80))
    rgba = r.render("千葉県千葉市上空")
    assert rgba.shape == (1080, 1920, 4)
    assert rgba.dtype == np.uint8
    assert rgba[:, :, 3].max() == 255      # 文字部分は不透明
    assert rgba[0, 0, 3] == 0              # 隅は透過(=Key)

    # 空文字は完全透過
    empty = r.render("")
    assert empty[:, :, 3].max() == 0


def test_decoder_core_end_to_end():
    fs = 48000
    cfg = HeliConfig(fs=fs, baud=1200, channel=0, geo_mode="offline",
                     addr_level="muni", text_format="{address}上空")
    dec = HeliDecoder(cfg)
    try:
        audio = encode_position_to_audio(
            fs, baud=1200, lat_dms="354027", lon_dms="1394510", alt_m=500)
        for i in range(0, len(audio), 800):
            dec.feed(audio[i:i + 800])
        # 少し待って住所解決(オフラインなので即時のはず)
        import time
        for _ in range(20):
            if dec.status()["address"]:
                break
            time.sleep(0.05)
        st = dec.status()
        assert st["receiving"] is True
        assert st["lat"] is not None
        text = dec.current_text()
        assert text.endswith("上空")
        # 都道府県のいずれかの接尾辞を含む(この座標はWGS84で東京都千代田区)
        assert any(suf in text for suf in ("都", "道", "府", "県"))
    finally:
        dec.close()


def test_decoder_core_format_altitude():
    fs = 48000
    cfg = HeliConfig(fs=fs, channel=0, text_format="{address} 高度{alt}m")
    dec = HeliDecoder(cfg)
    try:
        audio = encode_position_to_audio(fs, lat_dms="354027", lon_dms="1394510", alt_m=620)
        for i in range(0, len(audio), 800):
            dec.feed(audio[i:i + 800])
        import time
        time.sleep(0.3)
        assert "高度620m" in dec.current_text()
    finally:
        dec.close()
