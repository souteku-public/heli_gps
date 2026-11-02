"""住所・時刻・局名の3レイヤ描画と、レイヤ別OSC制御のテスト."""

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gst_heli.app import OscControl
from gst_heli.decoder_core import HeliConfig
from gst_heli.fonts import classify_font
from gst_heli.renderer import (Layer, LayerSet, SuperRenderer, SuperStyle,
                               build_layers, clock_text)


# ---------------- フォントのライセンス区分 ----------------

@pytest.mark.parametrize("path,want", [
    (r"C:\Windows\Fonts\YuGothB.ttc", "os"),
    (r"C:\Windows\Fonts\meiryo.ttc", "os"),
    (r"C:\Windows\Fonts\BIZ-UDGothicR.ttc", "os"),
    # 市販フォントを全ユーザー向けに入れると C:\Windows\Fonts に入るが、
    # Windows同梱ではないので "other"(EULA要確認)に分類されること
    (r"C:\Windows\Fonts\A-OTF-FutoGoB101Pro-Bold.otf", "other"),
    (r"C:\Users\x\AppData\Local\Microsoft\Windows\Fonts\Foo.otf", "other"),
    ("/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf", "os"),
    (os.path.expanduser("~/.fonts/whatever.ttf"), "other"),
])
def test_classify_font(path, want):
    assert classify_font(path) == want


def test_bundled_font_is_classified_bundled():
    from gst_heli.renderer import bundled_fonts
    fonts = bundled_fonts()
    assert fonts, "同梱フォントが見つからない(fonts/ が空?)"
    for p in fonts:
        assert classify_font(p) == "bundled"


def test_list_fonts_hides_other_by_default():
    from gst_heli.fonts import list_system_fonts
    safe = list_system_fonts(include_other=False)
    assert all(k != "other" for _n, _p, k in safe)
    assert any(k == "bundled" for _n, _p, k in safe)


# ---------------- レイヤの組み立て ----------------

def test_build_layers_respects_on_flags():
    ls = LayerSet()
    assert [l.key for l in build_layers(ls, "東京都港区上空")] == ["addr"]
    ls.clock_on = True
    ls.station_on = True
    ls.station_text = "日本テレビ"
    assert [l.key for l in build_layers(ls, "東京都港区上空")] == \
        ["addr", "clock", "station"]
    # 空文字のレイヤは出さない
    ls.station_text = ""
    assert [l.key for l in build_layers(ls, "")] == ["clock"]


def test_clock_format():
    t = time.struct_time((2026, 11, 2, 12, 34, 56, 0, 306, 0))
    assert clock_text("hm", t) == "12:34"
    assert clock_text("hms", t) == "12:34:56"
    assert clock_text("bogus", t) == "12:34:56"      # 不正値は秒まで


# ---------------- 描画 ----------------

def _renderer():
    return SuperRenderer(640, 360, SuperStyle())


def test_layers_are_placed_independently():
    r = _renderer()
    a = SuperStyle(font_size=40, margin_x=20, margin_y=20, align_x="left")
    b = SuperStyle(font_size=40, margin_x=620, margin_y=300, align_x="right")
    bb_a = r.layer_bbox(Layer("addr", "あいう", a))
    bb_b = r.layer_bbox(Layer("clock", "12:34", b))
    assert bb_a[0] == 20 and bb_a[1] == 20            # 左上を基準に右下へ伸びる
    assert bb_b[2] == 620                             # 右寄せは右端が基準
    assert bb_b[1] == 300
    assert bb_a[2] < bb_b[0]                          # 重ならない


def test_opacity_scales_alpha():
    r = _renderer()
    full = r.render_layers([Layer("addr", "あ", SuperStyle(font_size=60))])
    r2 = _renderer()
    half = r2.render_layers([Layer("addr", "あ", SuperStyle(font_size=60,
                                                            opacity=128))])
    assert int(full[:, :, 3].max()) == 255
    assert int(half[:, :, 3].max()) == 128


def test_render_layers_returns_independent_arrays():
    """前フレームが後から書き換わらないこと(送出スレッドと競合するため)."""
    r = _renderer()
    f1 = r.render_layers([Layer("addr", "あ", SuperStyle(font_size=60))])
    before = f1.copy()
    r.render_layers([Layer("addr", "い", SuperStyle(font_size=60))])
    assert np.array_equal(f1, before)


def test_layer_cache_reuses_unchanged_layer():
    """時刻だけ変えたとき、住所レイヤは再ラスタライズされないこと."""
    r = _renderer()
    addr = SuperStyle(font_size=40, margin_x=20, margin_y=20)
    clock = SuperStyle(font_size=40, margin_x=20, margin_y=200)
    lays = [Layer("addr", "東京都港区上空", addr), Layer("clock", "12:34:56", clock)]
    r.render_layers(lays)
    cached_addr = r._layer_cache["addr"][1]
    lays[1] = Layer("clock", "12:34:57", clock)
    r.render_layers(lays)
    assert r._layer_cache["addr"][1] is cached_addr    # 同じ配列オブジェクト


def test_moving_a_layer_does_not_rerasterize():
    r = _renderer()
    st = SuperStyle(font_size=40, margin_x=20, margin_y=20)
    r.render_layers([Layer("addr", "あ", st)])
    cached = r._layer_cache["addr"][1]
    st.margin_x = 300                                  # 位置だけ変更
    r.render_layers([Layer("addr", "あ", st)])
    assert r._layer_cache["addr"][1] is cached


def test_render_backward_compatible():
    r = _renderer()
    f = r.render("東京都港区上空")
    assert f.shape == (360, 640, 4)
    assert int(f[:, :, 3].max()) == 255


# ---------------- OSC 制御 ----------------

def _ctrl():
    """ソケットを開かずに _apply だけ試す OscControl."""
    cfg = HeliConfig(fs=48000, baud=1200, channel=0)
    style = SuperStyle()
    ls = LayerSet(addr=style)
    c = OscControl.__new__(OscControl)
    c.cfg, c.style, c.layers, c.mstyle, c.on_change = cfg, style, ls, None, None
    c._color, c._stroke = {}, {}
    return c, cfg, ls


def test_legacy_osc_names_target_address_layer():
    """接頭辞なしの旧名は住所レイヤに効く(TouchDesigner版との後方互換)."""
    c, _cfg, ls = _ctrl()
    c._apply("Fontsize", 120)
    c._apply("Posx", 300)
    c._apply("Alignx", "center")
    c._apply("Opacity", 0.5)
    assert ls.addr.font_size == 120
    assert ls.addr.margin_x == 300
    assert ls.addr.align_x == "center"
    assert ls.addr.opacity == 127
    # 他のレイヤは無傷
    assert ls.clock.font_size == 64 and ls.station.margin_x == 80


def test_prefixed_osc_names_target_their_layer():
    c, _cfg, ls = _ctrl()
    c._apply("Clockfontsize", 70)
    c._apply("Clockposx", 1800)
    c._apply("Clockalignx", "right")
    c._apply("Clockopacity", 0.8)
    c._apply("Stationfontsize", 52)
    c._apply("Stationfontweight", "Black")
    assert (ls.clock.font_size, ls.clock.margin_x, ls.clock.align_x) == (70, 1800, "right")
    assert ls.clock.opacity == 204
    assert ls.station.font_size == 52 and ls.station.font_weight == "Black"
    assert ls.addr.font_size == 90      # 住所は変わっていない


def test_layer_colors_do_not_leak_between_layers():
    """色は成分ごとに届くので、レイヤ間で混ざらないこと."""
    c, _cfg, ls = _ctrl()
    for comp, v in (("r", 1.0), ("g", 0.0), ("b", 0.0)):
        c._apply(f"Stationfontcolor{comp}", v)
    for comp, v in (("r", 0.0), ("g", 0.0), ("b", 1.0)):
        c._apply(f"Fontcolor{comp}", v)
    assert ls.station.color == (255, 0, 0)
    assert ls.addr.color == (0, 0, 255)


def test_layer_on_off_and_clock_format():
    c, _cfg, ls = _ctrl()
    c._apply("Clockon", 1)
    c._apply("Stationon", 1)
    c._apply("Superon", 0)
    c._apply("Clockformat", "hm")
    c._apply("Stationtext", "日本テレビ")
    assert ls.clock_on and ls.station_on and not ls.addr_on
    assert ls.clock_format == "hm"
    assert ls.station_text == "日本テレビ"
    c._apply("Clockformat", "bogus")
    assert ls.clock_format == "hms"     # 不正値は秒まで


def test_address_settings_not_confused_with_layer_prefix():
    """Addrlevel 等の住所設定が、レイヤ名の解釈に吸われないこと."""
    c, cfg, ls = _ctrl()
    c._apply("Addrlevel", "citygun")
    c._apply("Textformat", "{address}付近")
    c._apply("Geomode", "auto")
    c._apply("Audiochan", 4)
    assert cfg.addr_level == "citygun"
    assert cfg.text_format == "{address}付近"
    assert cfg.geo_mode == "auto" and cfg.channel == 4
    assert ls.addr.font_size == 90      # レイヤは無傷
