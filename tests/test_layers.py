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
    t = time.struct_time((2026, 11, 4, 12, 34, 56, 0, 308, 0))
    assert clock_text("hm", "off", t) == "12:34"
    assert clock_text("hms", "off", t) == "12:34:56"
    assert clock_text("bogus", "off", t) == "12:34"      # 不正値は分まで


def test_clock_date():
    t = time.struct_time((2026, 11, 4, 12, 34, 56, 0, 308, 0))
    assert clock_text("hm", "slash", t) == "11/4 12:34"
    assert clock_text("hm", "kanji", t) == "11月4日 12:34"
    assert clock_text("hms", "slash", t) == "11/4 12:34:56"
    assert clock_text("hm", "bogus", t) == "12:34"       # 不正値は日付なし


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
    base = dict(font_size=60, margin_x=20, margin_y=20)
    full = r.render_layers([Layer("addr", "あ", SuperStyle(**base))])
    r2 = _renderer()
    half = r2.render_layers([Layer("addr", "あ", SuperStyle(opacity=128, **base))])
    assert int(full[:, :, 3].max()) == 255
    assert int(half[:, :, 3].max()) == 128


def test_render_layers_returns_independent_arrays():
    """前フレームが後から書き換わらないこと(送出スレッドと競合するため)."""
    r = _renderer()
    st = SuperStyle(font_size=60, margin_x=20, margin_y=20)
    f1 = r.render_layers([Layer("addr", "あ", st)])
    before = f1.copy()
    r.render_layers([Layer("addr", "い", st)])
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
    r = SuperRenderer(640, 360, SuperStyle(font_size=40, margin_x=20, margin_y=20))
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
    assert ls.clock.font_size == 72 and ls.clock.margin_x == 80


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
    assert ls.addr.font_size == 72      # 住所は変わっていない


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
    assert ls.clock_format == "hm"      # 不正値は分まで
    c._apply("Clockdate", "slash")
    assert ls.clock_date == "slash"
    c._apply("Clockdate", "bogus")
    assert ls.clock_date == "off"


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
    assert ls.addr.font_size == 72      # レイヤは無傷


# ---------------- 住所の見せ方 ----------------

def _addr(pref, city, **kw):
    from nnn_decoder.geocode import Address
    return Address(pref=pref, city=city, **kw)


@pytest.mark.parametrize("pref,want", [
    ("千葉県", "千葉"), ("東京都", "東京"), ("大阪府", "大阪"),
    ("京都府", "京都"), ("神奈川県", "神奈川"), ("鹿児島県", "鹿児島"),
    ("北海道", "北海道"),            # 「北海」にしてはいけない
])
def test_strip_pref_suffix(pref, want):
    from nnn_decoder.geocode import Address
    assert Address.strip_pref_suffix(pref) == want


@pytest.mark.parametrize("name,want", [
    ("鴨川市", "鴨川"), ("千代田区", "千代田"), ("大町町", "大町"),
    ("市川市", "市川"),              # 先頭の「市」は残す
    ("四日市市", "四日市"), ("野々市市", "野々市"),
    ("東村", "東村"),                # 2文字以下になるなら外さない
])
def test_strip_muni_suffix(name, want):
    from nnn_decoder.geocode import Address
    assert Address.strip_muni_suffix(name) == want


def test_address_short_style():
    a = _addr("千葉県", "鴨川市")
    assert a.text("muni") == "千葉県鴨川市"
    assert a.text("muni", drop_pref_suffix=True, drop_muni_suffix=True,
                  sep="・") == "千葉・鴨川"


def test_address_short_style_offshore():
    a = _addr("茨城県", "鹿嶋市", offshore=True)
    assert a.text("muni", "沖", drop_pref_suffix=True,
                  drop_muni_suffix=True, sep="・") == "茨城・鹿嶋沖"
    assert a.text("muni", "沿岸", drop_pref_suffix=True,
                  drop_muni_suffix=True, sep="・") == "茨城・鹿嶋沿岸"
    assert a.text("muni", "", drop_pref_suffix=True,
                  drop_muni_suffix=True, sep="・") == "茨城・鹿嶋"


def test_address_short_style_designated_city():
    a = _addr("神奈川県", "横浜市緑区")
    assert a.text("muni") == "神奈川県横浜市"
    assert a.text("muni", drop_pref_suffix=True, drop_muni_suffix=True,
                  sep="・") == "神奈川・横浜"
    # city レベルは区まで出す。接尾辞は末尾の1文字だけ外す
    assert a.text("city", drop_pref_suffix=True, drop_muni_suffix=True,
                  sep="・") == "神奈川・横浜市緑"


def test_address_short_style_gun():
    a = _addr("北海道", "当別町", gun="石狩郡")
    assert a.text("citygun", drop_pref_suffix=True, drop_muni_suffix=True,
                  sep="・") == "北海道・石狩郡当別"


def test_decoder_text_format_and_suffix():
    from types import SimpleNamespace
    from gst_heli.decoder_core import HeliConfig, HeliDecoder
    cfg = HeliConfig(fs=48000, baud=1200, channel=0)
    d = HeliDecoder.__new__(HeliDecoder)
    d.cfg = cfg
    d._geo = SimpleNamespace(current=_addr("千葉県", "鴨川市"))
    pkt = SimpleNamespace(alt_m=300.0, lat_wgs84=35.1, lon_wgs84=140.1,
                          satellites=8)
    assert d._format(pkt) == "千葉県鴨川市上空"
    cfg.addr_suffix_on = False
    assert d._format(pkt) == "千葉県鴨川市"
    cfg.addr_suffix_on = True
    cfg.drop_pref_suffix = cfg.drop_muni_suffix = True
    cfg.addr_sep = "・"
    assert d._format(pkt) == "千葉・鴨川上空"
    cfg.addr_suffix = "付近"
    assert d._format(pkt) == "千葉・鴨川付近"
    # 旧形式の書式文字列でも落ちないこと(後方互換)
    cfg.text_format = "{address}上空"
    assert d._format(pkt) == "千葉・鴨川上空"


def test_address_osc_controls():
    c, cfg, _ls = _ctrl()
    c._apply("Addrdroppref", 1)
    c._apply("Addrdropmuni", 1)
    c._apply("Addrsep", "・")
    c._apply("Addroffshore", "沿岸")
    c._apply("Addrsuffix", "上空")
    c._apply("Addrsuffixon", 0)
    assert cfg.drop_pref_suffix and cfg.drop_muni_suffix
    assert cfg.addr_sep == "・" and cfg.offshore_suffix == "沿岸"
    assert cfg.addr_suffix == "上空" and cfg.addr_suffix_on is False


# ---------------- 縦並べ直し ----------------

def test_stack_vertically_no_overlap():
    from gst_heli.renderer import LAYER_KEYS, stack_vertically
    ls = LayerSet()
    ls.addr.font_size = 96          # サイズがバラバラでも重ならないこと
    ls.clock.font_size = 48
    ls.station.margin_x = 999       # 位置がずれていても揃うこと
    styles = {k: ls.style(k) for k in LAYER_KEYS}
    stack_vertically(styles, LAYER_KEYS, x=80, top=600, align="left")
    ys = [styles[k].margin_y for k in LAYER_KEYS]
    assert ys == [600, 600 + int(96 * 1.3), 600 + int(96 * 1.3) + int(48 * 1.3)] \
        or ys[0] == 600 and ys[1] > ys[0] and ys[2] > ys[1]
    assert all(styles[k].margin_x == 80 for k in LAYER_KEYS)
    assert all(styles[k].align_x == "left" for k in LAYER_KEYS)


def test_stack_vertically_keeps_lines_apart_when_rendered():
    """実際に描いたときに行が重ならないこと."""
    from gst_heli.renderer import LAYER_KEYS, stack_vertically
    ls = LayerSet()
    styles = {k: ls.style(k) for k in LAYER_KEYS}
    stack_vertically(styles, LAYER_KEYS, x=20, top=20, align="left")
    r = SuperRenderer(1920, 1080, SuperStyle())
    boxes = [r.layer_bbox(Layer(k, "千葉・鴨川上空", styles[k]))
             for k in LAYER_KEYS]
    for a, b in zip(boxes, boxes[1:]):
        assert a[3] < b[1], f"行が重なっている: {a} と {b}"


# ---------------- localhost ポートの確保 ----------------

def test_tcpserver_falls_back_when_port_is_taken():
    """希望ポートが他プロセスに使われていたら、空きポートへ自動で移ること.

    Windows の SO_REUSEADDR は「他プロセスが待ち受け中のポートにも重ねて
    bind できる」挙動のため、以前はここで bind だけ成功し、gst 側が
    『接続が拒否されました』になっていた。
    """
    import socket
    from gst_heli.gst_subprocess import _TcpServer

    squat = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    squat.bind(("127.0.0.1", 0))
    squat.listen(1)
    taken = squat.getsockname()[1]
    srv = None
    try:
        srv = _TcpServer(taken, lambda c, s: None, label="test")
        assert srv.port != taken, "使用中のポートを掴んでしまっている"
        # 移った先に本当に接続できること
        c = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
        c.close()
    finally:
        if srv:
            srv.close()
        squat.close()


def test_tcpserver_uses_requested_port_when_free():
    import socket
    from gst_heli.gst_subprocess import _TcpServer

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free = probe.getsockname()[1]
    probe.close()
    srv = _TcpServer(free, lambda c, s: None, label="test")
    try:
        assert srv.port == free
    finally:
        srv.close()


def test_audio_only_pipeline_has_no_output():
    """切り分けモードは SDI 出力要素を一切含まないこと(REF不要・安全)."""
    from gst_heli.gst_subprocess import GstSubprocessBridge
    b = GstSubprocessBridge(lambda: None, lambda a, n: None, audio_only=True,
                            vmode="1080i5994", gst_bin="gst-launch-1.0")
    cmd = " ".join(b._build_cmd())
    assert "decklinkvideosink" not in cmd
    assert "decklinkaudiosink" not in cmd
    assert "autovideosink" not in cmd
    assert "decklinkvideosrc" in cmd and "decklinkaudiosrc" in cmd
    assert "mode=1080i5994" in cmd


# ---------------- インターレース映像と compositor ----------------

def _burnin_cmd(**kw):
    from gst_heli.gst_subprocess import GstSubprocessBridge
    b = GstSubprocessBridge(lambda: None, lambda a, n: None, out_mode="burnin",
                            vmode="1080i5994", gst_bin="gst-launch-1.0", **kw)
    return " ".join(b._build_cmd())


def test_burnin_keeps_1080i_and_matches_both_compositor_inputs():
    """既定: 入力は 1080i のまま。テロップ側を interleaved に揃える.

    compositor は 2 入力のインターレース指定が食い違うと交渉に失敗する
    (not-negotiated)。画質を落とさないため、入力を変換するのではなく
    テロップ側を合わせる。
    """
    cmd = _burnin_cmd()
    src = cmd[cmd.index("decklinkvideosrc"):cmd.index("comp.sink_0")]
    telop = cmd[cmd.index("tcpclientsrc"):cmd.index("comp.sink_1")]
    assert "deinterlace" not in src, "既定で入力を変換してはいけない(画質が落ちる)"
    assert "interlaced=true" in telop, "テロップ側が入力とそろっていない"
    assert "interlace-mode=interleaved" in cmd, "出力が 1080i になっていない"


def test_burnin_deinterlace_option_matches_both_inputs_too():
    """--deinterlace のときは両方 progressive でそろえること."""
    cmd = _burnin_cmd(deinterlace=True)
    src = cmd[cmd.index("decklinkvideosrc"):cmd.index("comp.sink_0")]
    telop = cmd[cmd.index("tcpclientsrc"):cmd.index("comp.sink_1")]
    assert "deinterlace" in src
    assert "interlaced=true" not in telop, "入力は progressive なのにテロップが i"


def test_preview_deinterlaces_for_pc_display():
    """プレビューはPC画面で見るのでデインターレースする(両入力 progressive)."""
    from gst_heli.gst_subprocess import GstSubprocessBridge
    b = GstSubprocessBridge(lambda: None, lambda a, n: None, preview=True,
                            vmode="1080i5994", gst_bin="gst-launch-1.0",
                            deinterlace=True)      # preview.py と同じ指定
    cmd = " ".join(b._build_cmd())
    src = cmd[cmd.index("decklinkvideosrc"):cmd.index("comp.sink_0")]
    telop = cmd[cmd.index("tcpclientsrc"):cmd.index("comp.sink_1")]
    assert "deinterlace" in src
    assert "interlaced=true" not in telop


def test_bridge_default_does_not_touch_the_picture():
    """コンストラクタ既定は「画に手を加えない」であること.

    ここが True だと、既定に頼った呼び出し側と明示指定した側で食い違い、
    compositor の交渉が失敗する(実際にこの不具合が起きた)。
    """
    import inspect
    from gst_heli.gst_subprocess import GstSubprocessBridge
    sig = inspect.signature(GstSubprocessBridge.__init__)
    assert sig.parameters["deinterlace"].default is False


def test_preview_module_asks_for_deinterlace_explicitly():
    """preview.py が既定任せにせず明示的に指定していること."""
    import pathlib as _p
    src = _p.Path(__file__).resolve().parent.parent / "gst_heli" / "preview.py"
    assert "deinterlace=True" in src.read_text(encoding="utf-8")


@pytest.mark.parametrize("deinterlace", [False, True])
def test_burnin_pipeline_actually_negotiates(tmp_path, deinterlace):
    """生成したパイプラインを実際に gst-launch で流し、交渉が通ることを確かめる.

    DeckLink 部分だけ videotestsrc / fakesink に差し替える。
    GStreamer が無い環境では skip。
    """
    import re
    import shutil
    import subprocess
    if not shutil.which("gst-launch-1.0"):
        pytest.skip("GStreamer が無い環境")

    telop = tmp_path / "telop.bgra"
    telop.write_bytes(bytes(1920 * 1080 * 4) * 3)

    line = _burnin_cmd(deinterlace=deinterlace)
    line = re.sub(r"decklinkvideosrc [^!]*!",
                  'videotestsrc num-buffers=3 ! "video/x-raw,format=UYVY,'
                  'width=1920,height=1080,framerate=30000/1001,'
                  'interlace-mode=interleaved" !', line)
    line = re.sub(r"tcpclientsrc [^!]*!", f"filesrc location={telop} !", line)
    line = re.sub(r"decklinkvideosink.*?keyer-mode=off", "fakesink", line)
    line = re.sub(r"decklinkaudiosrc [^!]*!",
                  'audiotestsrc num-buffers=10 ! '
                  '"audio/x-raw,rate=48000,channels=8" !', line)
    line = re.sub(r"tcpclientsink \S+ \S+ \S+", "fakesink", line)
    line = re.sub(r"decklinkaudiosink \S+ \S+", "fakesink", line)

    r = subprocess.run(line, shell=True, capture_output=True, text=True,
                       timeout=120)
    out = r.stdout + r.stderr
    assert "not-negotiated" not in out, out[-800:]
    assert "ERROR" not in out, out[-800:]
