"""テロップ(スーパー)描画 — Pillowで1080 RGBA画像を生成.

背景は透過(アルファ0)。この画像のRGBがFill、アルファがKeyになる。

住所・時刻・局名を**独立したレイヤ**として重ねられる。レイヤごとに
位置・フォント・サイズ・太さ・色・フチ・**透過率**を設定できる。

性能: レイヤは外接矩形ぶんの小さな画像としてキャッシュし、変化した
レイヤだけ描き直して合成する。秒表示の時刻が毎秒変わっても、住所と
局名は再描画されない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# 配布同梱フォント置き場(リポジトリ直下 fonts/)。ここが最優先。
# SIL OFL / IPAライセンス等、再配布可のフォントのみ置くこと(fonts/README.md 参照)。
_BUNDLED_FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

# 再配布可(OFL/IPA)のフォント。放送・配布のライセンス面で安全なため優先する。
_OFL_CANDIDATES = [
    r"C:\Windows\Fonts\NotoSansJP-Bold.otf",
    r"C:\Windows\Fonts\NotoSansJP-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]

# 環境依存フォント(EULA要確認)。OFL系が見つからないときのみ使う。
_SYSTEM_CANDIDATES = [
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\BIZ-UDPGothicR.ttc",
]

# レイヤの種類。描画順(下→上)もこの順。
LAYER_KEYS = ("addr", "clock", "station")
LAYER_LABELS = {"addr": "住所", "clock": "時刻", "station": "局名"}

# 時刻の表示書式。UI/OSC では "hm"(分まで) / "hms"(秒まで) で指定する。
CLOCK_FORMATS = {"hm": "%H:%M", "hms": "%H:%M:%S"}
# 日付の付け方。"off"=付けない / "slash"=11/4 / "kanji"=11月4日
CLOCK_DATES = ("off", "slash", "kanji")

# レイヤを縦に並べるときの既定値(1行の送り = 文字サイズ × この係数)
LINE_PITCH = 1.3


def bundled_fonts() -> list[str]:
    """fonts/ に置かれた同梱フォント(あれば)を返す."""
    try:
        return sorted(str(p) for p in _BUNDLED_FONT_DIR.iterdir()
                      if p.suffix.lower() in (".ttf", ".otf", ".ttc", ".otc"))
    except Exception:
        return []


def font_candidates() -> list[str]:
    """探索順: 同梱fonts/ → OFL/IPA → 環境依存フォント."""
    return bundled_fonts() + _OFL_CANDIDATES + _SYSTEM_CANDIDATES


# 既定のスーパー位置(左下に縦並び)。1080の下端セーフエリア内に3行収まる値。
DEFAULT_SIZE = 72
DEFAULT_X = 80
DEFAULT_PITCH = int(DEFAULT_SIZE * LINE_PITCH)      # 93
DEFAULT_TOP = 1080 - 95 - DEFAULT_SIZE - DEFAULT_PITCH * 2      # 727


@dataclass
class SuperStyle:
    """1レイヤぶんの見た目設定(既定値は住所レイヤの既定と同じ)."""
    font_path: Optional[str] = None      # 明示指定(なければ候補から自動)
    font_size: int = DEFAULT_SIZE
    # 可変フォントのウェイト名(Thin/Light/Regular/Medium/SemiBold/Bold/Black 等)。
    # 同梱の Noto Sans JP VF は可変なのでここで太さを決める。非可変なら無視。
    font_weight: str = "Bold"
    color: tuple[int, int, int] = (255, 255, 255)
    # 水平: 基準点 margin_x に対して文字の left/center/right を合わせる。
    #   left  … 基準点=文字の左端(右へ伸びる)
    #   right … 基準点=文字の右端(左へ伸びる)
    #   center… 基準点=文字の中央
    align_x: str = "left"
    align_y: str = "top"                 # top/center/bottom(margin_y基準)
    margin_x: int = DEFAULT_X            # 水平の基準位置(px)
    margin_y: int = DEFAULT_TOP
    # フチ取り(視認性向上。放送テロップの定番)
    stroke_width: int = 4
    stroke_color: tuple[int, int, int] = (0, 0, 0)
    # 座布団(半透明の帯)。alpha=0で無効
    box_alpha: int = 0
    box_color: tuple[int, int, int] = (0, 0, 0)
    box_pad: int = 24
    # 透過率 0(透明)〜255(不透明)。Fill&Key ではこれがそのまま Key 信号になるため、
    # スイッチャー側でも意図どおり半透明で抜ける。
    opacity: int = 255


@dataclass
class LayerSet:
    """住所・時刻・局名の3レイヤぶんの設定.

    既定は**3項目とも同じ位置・同じ文字サイズ・同じ色で縦並び**(左下)。
    そこから項目ごとに位置・サイズ・色を変えられる。
    """
    addr: SuperStyle = field(default_factory=SuperStyle)
    clock: SuperStyle = field(
        default_factory=lambda: SuperStyle(margin_y=DEFAULT_TOP + DEFAULT_PITCH))
    station: SuperStyle = field(
        default_factory=lambda: SuperStyle(margin_y=DEFAULT_TOP + DEFAULT_PITCH * 2))
    addr_on: bool = True
    # 時刻・局名は**既定OFF**。明示的にONにしたときだけ放送に出る。
    clock_on: bool = False
    station_on: bool = False
    clock_format: str = "hm"             # "hm"(分まで) / "hms"(秒まで)
    clock_date: str = "off"              # "off" / "slash"(11/4) / "kanji"(11月4日)
    station_text: str = ""

    def style(self, key: str) -> SuperStyle:
        return getattr(self, key)

    def is_on(self, key: str) -> bool:
        return bool(getattr(self, key + "_on"))


@dataclass
class Layer:
    """描画する1レイヤ(文字列 + 見た目)."""
    key: str
    text: str
    style: SuperStyle


def clock_text(fmt: str = "hm", date: str = "off", now=None) -> str:
    """現在時刻の表示文字列.

    fmt  … "hm"(分まで) / "hms"(秒まで)
    date … "off"(日付なし) / "slash"(11/4) / "kanji"(11月4日)

    時刻は送出PCのローカル時計から取る。NNNフォーマットのパケットには
    時刻フィールドが無いため(DATA 20byte = 測位状態4+緯度6+経度7+高度3)。
    放送に出す場合は**PCをNTP同期しておくこと**(README_SETUP.md 参照)。
    """
    import time as _time
    t = now if now is not None else _time.localtime()
    hm = _time.strftime(CLOCK_FORMATS.get(fmt, CLOCK_FORMATS["hm"]), t)
    if date == "slash":
        return f"{t.tm_mon}/{t.tm_mday} {hm}"
    if date == "kanji":
        return f"{t.tm_mon}月{t.tm_mday}日 {hm}"
    return hm


def build_layers(ls: LayerSet, addr_text: str) -> list["Layer"]:
    """LayerSet と住所文字列から、描画するレイヤ列(下→上)を作る."""
    out: list[Layer] = []
    if ls.addr_on and addr_text:
        out.append(Layer("addr", addr_text, ls.addr))
    if ls.clock_on:
        out.append(Layer("clock", clock_text(ls.clock_format, ls.clock_date),
                         ls.clock))
    if ls.station_on and ls.station_text:
        out.append(Layer("station", ls.station_text, ls.station))
    return out


def stack_vertically(styles, keys, *, x: int = None, top: int = None,
                     align: str = None, pitch: float = LINE_PITCH) -> None:
    """指定したレイヤを同じ基準位置で縦に並べ直す(その場で書き換え).

    styles … {レイヤ名: SuperStyle}
    keys   … 並べる順(上から)
    x/top/align … 未指定なら先頭レイヤの現在値を使う
    文字サイズが違っても重ならないよう、各行の送りはそのレイヤの
    文字サイズに比例させる。
    """
    keys = [k for k in keys if k in styles]
    if not keys:
        return
    head = styles[keys[0]]
    x = head.margin_x if x is None else x
    y = head.margin_y if top is None else top
    align = head.align_x if align is None else align
    for k in keys:
        st = styles[k]
        st.margin_x, st.margin_y = int(x), int(y)
        st.align_x, st.align_y = align, "top"
        y += st.font_size * pitch


def _raster_sig(text: str, st: SuperStyle):
    """ラスタライズ結果が変わる要素だけのシグネチャ(位置・揃えは含めない)."""
    return (text, st.font_path, st.font_size, st.font_weight, tuple(st.color),
            st.stroke_width, tuple(st.stroke_color), st.box_alpha,
            tuple(st.box_color), st.box_pad, st.opacity)


def _blit(dst: np.ndarray, src: np.ndarray, ox: int, oy: int) -> None:
    """src を dst の (ox, oy) へアルファ合成(ストレートアルファ)."""
    sh, sw = src.shape[:2]
    dh, dw = dst.shape[:2]
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(dw, ox + sw), min(dh, oy + sh)
    if x0 >= x1 or y0 >= y1:
        return
    s = src[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    d = dst[y0:y1, x0:x1]
    sa = s[:, :, 3:4].astype(np.float32) / 255.0
    da = d[:, :, 3:4].astype(np.float32) / 255.0
    oa = sa + da * (1.0 - sa)
    rgb = (s[:, :, :3].astype(np.float32) * sa
           + d[:, :, :3].astype(np.float32) * da * (1.0 - sa))
    np.divide(rgb, np.maximum(oa, 1e-6), out=rgb)
    d[:, :, :3] = rgb.clip(0, 255).astype(np.uint8)
    d[:, :, 3:4] = (oa * 255.0).clip(0, 255).astype(np.uint8)


class SuperRenderer:
    """スーパー描画器.

    render(text)          … 住所1レイヤだけ(従来互換)
    render_layers(layers) … 複数レイヤを重ねて RGBA(H,W,4) を返す
    """

    def __init__(self, width: int = 1920, height: int = 1080,
                 style: SuperStyle | None = None):
        self.width = width
        self.height = height
        self.style = style or SuperStyle()
        self._font_cache: dict[tuple, ImageFont.FreeTypeFont] = {}
        # レイヤごとの描画結果キャッシュ: key -> (sig, 画像, 文字幅, 文字高, pad)
        self._layer_cache: dict[str, tuple] = {}
        self._measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    @staticmethod
    def _needs_cjk(text: str) -> bool:
        # ラテン/数字/記号(<0x2E7F)以外(かな・漢字など)を含むか
        return any(ord(c) > 0x2E7F for c in text)

    def _resolve_font_path(self, text: str = "",
                           st: SuperStyle | None = None) -> Optional[str]:
        """描画するtextに応じて実際に使うフォントパスを決める.

        ユーザ指定フォントに日本語字形が無く、textが日本語を含む場合は、
        テロップが消えないよう日本語対応の候補フォントへ自動フォールバックする。
        """
        import os
        from .fonts import font_has_japanese

        st = st or self.style
        user = (st.font_path if st.font_path and os.path.exists(st.font_path)
                else None)
        need_jp = self._needs_cjk(text)
        # ユーザ指定でOK(日本語不要 or 日本語字形あり)ならそれを使う
        if user and (not need_jp or font_has_japanese(user)):
            return user
        # 日本語が要るのに指定フォントが非対応 → 日本語対応の候補を探す
        if need_jp:
            for p in font_candidates():
                if os.path.exists(p) and font_has_japanese(p):
                    return p
        # それでも無ければ: ユーザ指定 → 存在する最初の候補
        if user:
            return user
        for p in font_candidates():
            if os.path.exists(p):
                return p
        return None

    def _font(self, text: str = "",
              st: SuperStyle | None = None) -> ImageFont.FreeTypeFont:
        st = st or self.style
        path = self._resolve_font_path(text, st)
        weight = st.font_weight or ""
        key = (path or "<default>", st.font_size, weight)
        if key in self._font_cache:
            return self._font_cache[key]
        font = None
        # 指定パス → 候補パス の順で、実際に読めるものを採用(消える事故を防ぐ)
        for p in ([path] if path else []) + font_candidates():
            if not p:
                continue
            try:
                import os
                if os.path.exists(p):
                    font = ImageFont.truetype(p, st.font_size)
                    break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        # 可変フォント(Noto Sans JP VF等)ならウェイトを適用。
        # テロップは既定Boldで太らせる(Regularだと放送で細く見える)。
        if weight:
            try:
                font.set_variation_by_name(weight)
            except Exception:
                pass          # 可変フォントでない/その名前が無い場合は無視
        self._font_cache[key] = font
        return font

    # ---------- レイヤ描画 ----------
    def _layer_image(self, lay: Layer):
        """レイヤを外接矩形ぶんの小画像に描く(キャッシュ付き).

        戻り値 (画像ndarray, 文字幅, 文字高, 余白pad)。
        位置・揃えは含めないので、移動しても再ラスタライズしない。
        """
        st = lay.style
        sig = _raster_sig(lay.text, st)
        ent = self._layer_cache.get(lay.key)
        if ent is not None and ent[0] == sig:
            return ent[1:]

        font = self._font(lay.text, st)
        bbox = self._measure.textbbox((0, 0), lay.text, font=font,
                                      stroke_width=st.stroke_width)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = (st.box_pad if st.box_alpha > 0 else 0) + 2
        img = Image.new("RGBA", (max(1, tw + pad * 2), max(1, th + pad * 2)),
                        (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # 文字のインク左上が (pad, pad) に来るように原点をずらす
        tx, ty = pad - bbox[0], pad - bbox[1]
        a = max(0, min(255, int(st.opacity)))
        if st.box_alpha > 0:
            ba = max(0, min(255, st.box_alpha * a // 255))
            d.rectangle([pad - st.box_pad, pad - st.box_pad,
                         pad + tw + st.box_pad, pad + th + st.box_pad],
                        fill=(*st.box_color, ba))
        d.text((tx, ty), lay.text, font=font, fill=(*st.color, a),
               stroke_width=st.stroke_width, stroke_fill=(*st.stroke_color, a))
        arr = np.asarray(img)
        self._layer_cache[lay.key] = (sig, arr, tw, th, pad)
        return arr, tw, th, pad

    def layer_origin(self, st: SuperStyle, tw: int, th: int) -> tuple[int, int]:
        """揃え設定から、文字インク左上のフレーム座標を返す."""
        if st.align_x == "right":
            x = st.margin_x - tw
        elif st.align_x == "center":
            x = st.margin_x - tw // 2
        else:
            x = st.margin_x
        if st.align_y == "top":
            y = st.margin_y
        elif st.align_y == "center":
            y = (self.height - th) // 2
        else:
            y = self.height - th - st.margin_y
        return int(x), int(y)

    def layer_bbox(self, lay: Layer) -> tuple[int, int, int, int] | None:
        """レイヤのフレーム座標での外接矩形 (x0, y0, x1, y1)."""
        if not lay.text:
            return None
        try:
            _arr, tw, th, _pad = self._layer_image(lay)
        except Exception:
            return None
        x, y = self.layer_origin(lay.style, tw, th)
        return (x, y, x + tw, y + th)

    def render_layers(self, layers: list[Layer]) -> np.ndarray:
        """レイヤ列を重ねて RGBA(H,W,4) uint8 を返す(背景は透過).

        毎回新しい配列を返す。送出スレッドが前のフレームを読んでいる間に
        書き換わらないようにするため(バッファの使い回しは不可)。
        """
        out = np.zeros((self.height, self.width, 4), np.uint8)
        for lay in layers:
            if not lay.text:
                continue
            try:
                arr, tw, th, pad = self._layer_image(lay)
            except Exception:
                continue
            x, y = self.layer_origin(lay.style, tw, th)
            _blit(out, arr, x - pad, y - pad)
        return out

    def render(self, text: str) -> np.ndarray:
        """住所1レイヤだけ描画する従来互換API."""
        return self.render_layers([Layer("addr", text, self.style)])
