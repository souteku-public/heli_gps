"""ヘリGPSスーパー 外部制御UI (tkinter).

TouchDesigner版・GStreamer版どちらも、同じOSCプロトコルで操作できる制御パネル。

    UI → OSC 127.0.0.1:9001 → TD(osc_ctrl) / gst_heli.app(--osc-control)
    TD/gst → OSC 127.0.0.1:9002 → このUI(状態表示)

主な機能:
    - 住所・時刻・局名を**独立したレイヤ**として個別に設定(位置/フォント/
      サイズ/太さ/色/フチ/透過率)
    - フォントは実在ファイルから選択(消える事故を防ぐ)。既定では配布同梱の
      OFLフォントとOS同梱フォントのみを表示し、市販フォントの誤用を防ぐ
    - 配置はドラッグ&ドロップ(矢印キー微調整も可)。本番と同じ描画でプレビュー
    - 受信状態・現在のスーパー・緯度経度をライブ表示

起動:  python control_ui.py   [--td-host 192.168.0.10]
依存:  tkinter(必須)。配置のWYSIWYGプレビューには numpy/Pillow(ImageTk)、
       オフライン地図には同梱の境界データを使う。無ければ簡易表示に自動で
       フォールバックする。
"""

from __future__ import annotations

import argparse
import json
import queue
import socket
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, ttk

from nnn_decoder.osc import osc_message, osc_parse
from nnn_decoder.geodesy import deg_to_dms_str

# 見た目・位置の既定を保存するファイル(control_ui.py と同じ場所)
CONFIG_PATH = Path(__file__).with_name("ui_settings.json")


def _load_settings() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_settings(full: dict) -> bool:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


N_PRESETS = 3   # 番組プリセットの数

try:
    from gst_heli.fonts import list_system_fonts
except Exception:
    list_system_fonts = None

# 本番と同じ Pillow レンダラで配置プレビューを描く(WYSIWYG)。
# 依存(numpy/Pillow/ImageTk)が無ければ簡易テキスト表示にフォールバック。
try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageTk
    from gst_heli.renderer import Layer, SuperRenderer, SuperStyle, clock_text
    HAVE_WYSIWYG = True
except Exception:
    HAVE_WYSIWYG = False

    def clock_text(fmt="hm", date="off", now=None):     # フォールバック
        t = now or time.localtime()
        hm = time.strftime("%H:%M:%S" if fmt == "hms" else "%H:%M", t)
        if date == "slash":
            return f"{t.tm_mon}/{t.tm_mday} {hm}"
        if date == "kanji":
            return f"{t.tm_mon}月{t.tm_mday}日 {hm}"
        return hm

try:
    import ui_theme
except Exception:
    ui_theme = None

try:
    from ui_map import MapWindow
except Exception:
    MapWindow = None

GEOMODE = [("オフライン(ネット不要)", "offline"), ("自動(ネット時は町丁目)", "auto"),
           ("オンライン(地理院API)", "online")]
ADDRLEVEL = [("都道府県", "pref"), ("市町村(政令市は市まで)", "muni"),
             ("市区町村(区あり)", "city"), ("市区町村(区・郡あり)", "citygun"),
             ("町丁目(要ネット)", "town")]
BAUD = [("1200 bps", "1200"), ("2400 bps", "2400")]
# フォント列挙に失敗したときの最終手段。再配布可(OFL/IPA)を先に並べる。
FALLBACK_FONTS = [("Noto Sans JP Bold", r"C:\Windows\Fonts\NotoSansJP-Bold.otf", "os"),
                  ("Noto Sans JP", r"C:\Windows\Fonts\NotoSansJP-Regular.otf", "os"),
                  ("Noto Sans CJK JP", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "os"),
                  ("IPAGothic", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", "os"),
                  ("游ゴシック Medium", r"C:\Windows\Fonts\YuGothM.ttc", "os"),
                  ("メイリオ", r"C:\Windows\Fonts\meiryo.ttc", "os")]

# レイヤ(表示項目)の定義。OSC名の接頭辞つき。
#   住所は接頭辞なし(Fontsize 等)= TouchDesigner版との後方互換のため。
LAYERS = [("addr", "住所", ""), ("clock", "時刻", "Clock"),
          ("station", "局名", "Station")]
LAYER_LABEL = {k: lab for k, lab, _p in LAYERS}
LAYER_PREFIX = {k: p for k, _lab, p in LAYERS}
CLOCK_FMT = [("分まで (12:34)", "hm"), ("秒まで (12:34:56)", "hms")]
CLOCK_DATE = [("日付なし", "off"), ("11/4", "slash"), ("11月4日", "kanji")]
ADDR_SEP = [("区切りなし", ""), ("・（中黒）", "・"), ("　（スペース）", " ")]
ADDR_OFFSHORE = [("沖", "沖"), ("沿岸", "沿岸"), ("付けない", "")]
LINE_PITCH = 1.3          # 縦並びの行送り(文字サイズ × この係数)

STALE_SEC = 3.0
FRAME_W, FRAME_H = 1920, 1080
CANVAS_W, CANVAS_H = 512, 288
SCALE = FRAME_W / CANVAS_W          # 3.75

# レイヤの既定値。**3項目とも同じ位置・同じ文字サイズ・同じ色で縦並び**(左下)。
# そこから項目ごとに位置・サイズ・色を変えられる。
# gst_heli/renderer.py の DEFAULT_* と同じ値(あちらは送出側の既定)。
DEF_SIZE, DEF_X, DEF_TOP, DEF_PITCH = 72, 80, 727, 93


def _layer_default(i: int, **extra) -> dict:
    d = dict(on=(i == 0), size=DEF_SIZE, weight="Bold", align="left", sw=5,
             fill=[1.0, 1.0, 1.0], stroke=[0.0, 0.0, 0.0], opacity=100,
             pos=[DEF_X, DEF_TOP + DEF_PITCH * i])
    d.update(extra)
    return d


LAYER_DEFAULTS = {
    "addr": _layer_default(0),
    "clock": _layer_default(1, format="hm", date="off"),
    "station": _layer_default(2, text=""),
}

# 住所の見せ方(「千葉県鴨川市上空」/「千葉・鴨川上空」など)
ADDR_DEFAULTS = dict(level="muni", droppref=False, dropmuni=False, sep="",
                     offshore="沖", suffix="上空", suffixon=True)


def _hex(rgb01):
    return "#%02x%02x%02x" % tuple(int(c * 255) for c in rgb01)


def _default_layers() -> dict:
    return {k: dict(v) for k, v in LAYER_DEFAULTS.items()}


def _addr_from_saved(saved: dict) -> dict:
    d = dict(ADDR_DEFAULTS)
    got = saved.get("addr")
    if isinstance(got, dict):
        d.update({k: v for k, v in got.items() if k in d})
    return d


def _layers_from_saved(saved: dict) -> dict:
    """保存データからレイヤ設定を復元する(旧スキーマからの移行つき)."""
    out = _default_layers()
    got = saved.get("layers")
    if isinstance(got, dict):
        for key, d in out.items():
            if isinstance(got.get(key), dict):
                d.update(got[key])
        return out
    # 旧スキーマ(住所1レイヤぶんがトップレベルにあった)からの移行
    a = out["addr"]
    for src, dst in (("font_name", "font"), ("font_path", "font_path"),
                     ("font_size", "size"), ("font_weight", "weight"),
                     ("align_x", "align"), ("stroke_width", "sw")):
        if src in saved:
            a[dst] = saved[src]
    for k in ("fill", "stroke", "pos"):
        if k in saved:
            a[k] = list(saved[k])
    return out


class OscClient:
    def __init__(self, host, ctrl_port, status_port):
        self.addr = (host, ctrl_port)
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._rx.bind(("0.0.0.0", status_port))
        self._rx.settimeout(0.3)
        self.inbox: queue.Queue = queue.Queue()
        self._stop = False
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def send(self, address, *args):
        try:
            self._tx.sendto(osc_message(address, *args), self.addr)
        except OSError:
            pass

    def _recv_loop(self):
        while not self._stop:
            try:
                data, _ = self._rx.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            a, args = osc_parse(data)
            if a:
                self.inbox.put((a, args))

    def close(self):
        self._stop = True


class ControlUI:
    def __init__(self, root, osc):
        self.root = root
        self.osc = osc
        self._last_status = 0.0
        saved = _load_settings()
        # レイヤ設定(住所/時刻/局名)。self.cur が編集中のレイヤ。
        self.L = _layers_from_saved(saved)
        self.A = _addr_from_saved(saved)      # 住所の見せ方
        self.cur = "addr"
        self.show_other_fonts = bool(saved.get("font_show_other", False))
        self.super_text = ""      # 送出側から届いた実際のスーパー
        # 地図スーパー(選択制)。既定OFF。ONにすると放送に出る
        self.map_on = bool(saved.get("map_on", False))
        self.map_pos = list(saved.get("map_pos", [1440, 690]))
        self.map_w = int(saved.get("map_w", 420))
        self.map_span = float(saved.get("map_span", 0.30))
        self.map_trail = bool(saved.get("map_trail", True))
        # 番組プリセット(名前付き)。[{name, settings}, ...]
        self._presets = list(saved.get("presets", []))
        # ドラッグ中の状態
        self._dragging = False           # False / "map" / レイヤキー
        self._drag_off = (0, 0)
        self._bboxes: dict[str, tuple] = {}   # レイヤ -> キャンバス座標の外接矩形
        self.map_win = None              # 地図ウィンドウ(開いていれば)
        self._palette = getattr(root, "_palette", None)
        self._loading = False            # ウィジェットへの反映中(OSC送信を抑止)
        # WYSIWYGプレビュー用のレンダラと背景
        self._pv_scale = CANVAS_W / FRAME_W
        if HAVE_WYSIWYG:
            try:
                self._pv_renderer = SuperRenderer(CANVAS_W, CANVAS_H, SuperStyle())
                self._pv_styles = {k: SuperStyle() for k, _l, _p in LAYERS}
                self._backdrop = self._make_backdrop()
            except Exception:
                self._pv_renderer = None
        else:
            self._pv_renderer = None
        # 見た目・配置の変更は「決定」ボタンを押すまで送らずに溜めておく。
        self._pending: dict = {}
        root.title("ヘリGPS スーパー制御")
        root.geometry("620x960")
        root.minsize(580, 560)
        self._build()
        self._load_layer_widgets()       # 編集中レイヤの値をウィジェットへ
        # 起動時に現在のUI状態(保存値があればそれ)を送出側へ流し込む。
        self._broadcast_look()
        self._poll()
        self._tick_clock()

    # ---------- ウィジェット生成補助 ----------
    def _menu(self, parent, label, items, ctrl_name, default_idx=0, kind="str",
              on_extra=None):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        var = tk.StringVar(value=items[default_idx][0])
        cb = ttk.Combobox(fr, textvariable=var, values=[i[0] for i in items],
                          state="readonly", width=26)
        cb.pack(side="left", fill="x", expand=True)
        lut = {lab: val for lab, val in items}

        def emit(_e=None):
            v = lut[var.get()]
            self.osc.send(f"/heli/ctrl/{ctrl_name}", int(v) if kind == "int" else v)
            if on_extra:
                on_extra(v)
        cb.bind("<<ComboboxSelected>>", emit)
        return var

    def _slider(self, parent, label, lo, hi, default, on_change):
        """スライダー + 数値直接入力(スピンボックス)。両者は連動。"""
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        val = tk.IntVar(value=int(default))

        def emit(*_a):
            if self._loading:
                return
            try:
                v = int(float(val.get()))
            except Exception:
                return
            v = max(int(lo), min(int(hi), v))
            if v != val.get():
                val.set(v)
            on_change(v)

        sb = ttk.Spinbox(fr, from_=lo, to=hi, textvariable=val, width=5,
                         command=emit)
        sb.pack(side="right")
        sb.bind("<Return>", emit)
        sb.bind("<FocusOut>", emit)
        ttk.Scale(fr, from_=lo, to=hi, variable=val,
                  command=lambda _v: emit()).pack(
            side="left", fill="x", expand=True, padx=4)
        return val

    # ---------- 画面構築 ----------
    def _build(self):
        # タブは廃止し、1画面に縦並び。
        # 下部の「決定」「受信状態」は常時見えるよう固定、それ以外はスクロール可。
        self._build_status()        # 最下部(固定)
        self._build_apply_bar()     # その上(固定)
        body = self._scrollable_body()
        self._build_addr(body)
        self._build_items(body)
        self._build_look(body)
        self._build_place(body)
        self._build_map(body)
        self._build_presets(body)
        self._redraw_canvas()

    def _scrollable_body(self):
        """縦スクロール可能な内側フレームを返す(小さい画面でも全項目に届く)."""
        outer = ttk.Frame(self.root)
        outer.pack(side="top", fill="both", expand=True)
        _bg = (self._palette or {}).get("bg", "#f5f5f7")
        sc = tk.Canvas(outer, highlightthickness=0, bg=_bg)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=sc.yview)
        body = ttk.Frame(sc)
        body.bind("<Configure>", lambda _e: sc.configure(scrollregion=sc.bbox("all")))
        win = sc.create_window((0, 0), window=body, anchor="nw")
        sc.bind("<Configure>", lambda e: sc.itemconfig(win, width=e.width))
        sc.configure(yscrollcommand=vsb.set)
        sc.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _wheel(e):
            sc.yview_scroll(-1 if e.delta > 0 else 1, "units")
        sc.bind_all("<MouseWheel>", _wheel)
        return body

    def _section(self, parent, title):
        lf = ttk.LabelFrame(parent, text=title)
        lf.pack(fill="x", padx=8, pady=(6, 0))
        return lf

    def _build_addr(self, parent):
        s = self._section(parent, "住所")
        self._menu(s, "住所変換モード", GEOMODE, "Geomode", 0)
        idx = next((i for i, (_l, v) in enumerate(ADDRLEVEL)
                    if v == self.A["level"]), 1)
        self.level_var = self._menu(s, "住所の粒度", ADDRLEVEL, "Addrlevel", idx,
                                    on_extra=self._on_addr_level)
        self._menu(s, "ビットレート", BAUD, "Baud", 0)
        fr = ttk.Frame(s); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="GPS音声ch(1-8)", width=16).pack(side="left")
        # 表示は1始まり(CH1..CH8)。内部/OSCは0始まりに変換して送る。
        self.audiochan = tk.IntVar(value=3)
        ttk.Spinbox(fr, from_=1, to=16, textvariable=self.audiochan, width=6,
                    command=lambda: self.osc.send("/heli/ctrl/Audiochan",
                                                  int(self.audiochan.get()) - 1)).pack(side="left")
        for label, ctrl, dflt in (("表示書式", "Textformat", "{address}{suffix}"),
                                  ("受信途絶時の表示", "Staletext", "")):
            fr = ttk.Frame(s); fr.pack(fill="x", pady=3)
            ttk.Label(fr, text=label, width=16).pack(side="left")
            var = tk.StringVar(value=dflt)
            e = ttk.Entry(fr, textvariable=var); e.pack(side="left", fill="x", expand=True)
            act = lambda _e=None, v=var, cn=ctrl: self.osc.send(f"/heli/ctrl/{cn}", v.get())
            e.bind("<Return>", act)
            ttk.Button(fr, text="適用", width=5, command=act).pack(side="left")
        self._build_addr_style(s)

    # ---------- 住所の見せ方 ----------
    def _build_addr_style(self, parent):
        s = ttk.LabelFrame(parent, text="住所の見せ方")
        s.pack(fill="x", padx=6, pady=(6, 4))

        fr = ttk.Frame(s); fr.pack(fill="x", pady=3)
        self.droppref_var = tk.BooleanVar(value=bool(self.A["droppref"]))
        ttk.Checkbutton(fr, text="「県・都・府」を省く", variable=self.droppref_var,
                        command=self._on_addr_style).pack(side="left", padx=(0, 14))
        self.dropmuni_var = tk.BooleanVar(value=bool(self.A["dropmuni"]))
        ttk.Checkbutton(fr, text="「市・区・町・村」を省く", variable=self.dropmuni_var,
                        command=self._on_addr_style).pack(side="left")

        fr2 = ttk.Frame(s); fr2.pack(fill="x", pady=3)
        ttk.Label(fr2, text="区切り", width=16).pack(side="left")
        self._sep_lut = {lab: v for lab, v in ADDR_SEP}
        rev = {v: k for k, v in self._sep_lut.items()}
        self.sep_var = tk.StringVar(value=rev.get(self.A["sep"], ADDR_SEP[0][0]))
        cb = ttk.Combobox(fr2, textvariable=self.sep_var,
                          values=[lab for lab, _v in ADDR_SEP],
                          state="readonly", width=16)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._on_addr_style())
        ttk.Label(fr2, text="海上の表記").pack(side="left", padx=(14, 4))
        self._off_lut = {lab: v for lab, v in ADDR_OFFSHORE}
        rev2 = {v: k for k, v in self._off_lut.items()}
        self.offshore_var = tk.StringVar(
            value=rev2.get(self.A["offshore"], ADDR_OFFSHORE[0][0]))
        cb2 = ttk.Combobox(fr2, textvariable=self.offshore_var,
                           values=[lab for lab, _v in ADDR_OFFSHORE],
                           state="readonly", width=8)
        cb2.pack(side="left")
        cb2.bind("<<ComboboxSelected>>", lambda _e: self._on_addr_style())

        fr3 = ttk.Frame(s); fr3.pack(fill="x", pady=3)
        self.suffixon_var = tk.BooleanVar(value=bool(self.A["suffixon"]))
        ttk.Checkbutton(fr3, text="末尾に付ける", variable=self.suffixon_var,
                        command=self._on_addr_style).pack(side="left")
        self.suffix_var = tk.StringVar(value=self.A["suffix"])
        e = ttk.Entry(fr3, textvariable=self.suffix_var, width=10)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda _e: self._on_addr_style())
        e.bind("<FocusOut>", lambda _e: self._on_addr_style())
        ttk.Label(fr3, text="（「上空」など。チェックを外すと付きません）",
                  style="Muted.TLabel").pack(side="left")

        self.addr_sample_lbl = ttk.Label(s, text="", style="Muted.TLabel")
        self.addr_sample_lbl.pack(anchor="w", padx=4, pady=(4, 4))
        self._update_addr_sample()

    def _on_addr_level(self, _v=None):
        self.A["level"] = self._level_value()
        self._update_addr_sample()
        self._redraw_canvas()

    def _level_value(self) -> str:
        lut = {lab: v for lab, v in ADDRLEVEL}
        return lut.get(self.level_var.get(), "muni")

    def _on_addr_style(self):
        a = self.A
        a["droppref"] = bool(self.droppref_var.get())
        a["dropmuni"] = bool(self.dropmuni_var.get())
        a["sep"] = self._sep_lut.get(self.sep_var.get(), "")
        a["offshore"] = self._off_lut.get(self.offshore_var.get(), "沖")
        a["suffix"] = self.suffix_var.get()
        a["suffixon"] = bool(self.suffixon_var.get())
        self._stage("/heli/ctrl/Addrdroppref", 1 if a["droppref"] else 0)
        self._stage("/heli/ctrl/Addrdropmuni", 1 if a["dropmuni"] else 0)
        self._stage("/heli/ctrl/Addrsep", a["sep"])
        self._stage("/heli/ctrl/Addroffshore", a["offshore"])
        self._stage("/heli/ctrl/Addrsuffix", a["suffix"])
        self._stage("/heli/ctrl/Addrsuffixon", 1 if a["suffixon"] else 0)
        self._update_addr_sample()
        self._redraw_canvas()

    def _sample_text(self, pref="千葉県", city="鴨川市", offshore=False,
                     gun="", town="") -> str:
        """現在の設定で住所がどう出るかの見本(送出側と同じロジック)."""
        a = self.A
        suffix = a["suffix"] if a["suffixon"] else ""
        try:
            from nnn_decoder.geocode import Address
            body = Address(pref=pref, city=city, gun=gun, town=town,
                           offshore=offshore).text(
                a["level"], a["offshore"],
                drop_pref_suffix=a["droppref"],
                drop_muni_suffix=a["dropmuni"], sep=a["sep"])
        except Exception:
            body = f"{pref}{a['sep']}{city}"
        return body + suffix

    def _update_addr_sample(self):
        if not hasattr(self, "addr_sample_lbl"):
            return
        land = self._sample_text()
        sea = self._sample_text("茨城県", "鹿嶋市", offshore=True)
        self.addr_sample_lbl.config(text=f"例）陸上: {land}　／　海上: {sea}")

    # ---------- 表示項目(レイヤのON/OFFと固有設定) ----------
    def _build_items(self, parent):
        s = self._section(parent, "表示項目")
        fr = ttk.Frame(s); fr.pack(fill="x", pady=4)
        self.on_vars = {}
        for key, label, _p in LAYERS:
            v = tk.BooleanVar(value=bool(self.L[key]["on"]))
            self.on_vars[key] = v
            ttk.Checkbutton(fr, text=label, variable=v,
                            command=lambda k=key: self._on_layer_toggle(k)).pack(
                side="left", padx=(0, 16))

        # 時刻の書式(粒度と日付)
        fr2 = ttk.Frame(s); fr2.pack(fill="x", pady=3)
        ttk.Label(fr2, text="時刻の表示", width=16).pack(side="left")
        self._fmt_lut = {lab: val for lab, val in CLOCK_FMT}
        rev = {v: k for k, v in self._fmt_lut.items()}
        self.fmt_var = tk.StringVar(
            value=rev.get(self.L["clock"].get("format", "hm"), CLOCK_FMT[0][0]))
        cb = ttk.Combobox(fr2, textvariable=self.fmt_var,
                          values=[lab for lab, _v in CLOCK_FMT],
                          state="readonly", width=18)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._on_clock_format())
        ttk.Label(fr2, text="日付").pack(side="left", padx=(14, 4))
        self._date_lut = {lab: val for lab, val in CLOCK_DATE}
        rev2 = {v: k for k, v in self._date_lut.items()}
        self.date_var = tk.StringVar(
            value=rev2.get(self.L["clock"].get("date", "off"), CLOCK_DATE[0][0]))
        cb2 = ttk.Combobox(fr2, textvariable=self.date_var,
                           values=[lab for lab, _v in CLOCK_DATE],
                           state="readonly", width=10)
        cb2.pack(side="left")
        cb2.bind("<<ComboboxSelected>>", lambda _e: self._on_clock_format())

        # 局名の文字列
        fr3 = ttk.Frame(s); fr3.pack(fill="x", pady=3)
        ttk.Label(fr3, text="局名の文字", width=16).pack(side="left")
        self.station_var = tk.StringVar(value=self.L["station"].get("text", ""))
        e = ttk.Entry(fr3, textvariable=self.station_var)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _e: self._on_station_text())
        e.bind("<FocusOut>", lambda _e: self._on_station_text())
        ttk.Button(fr3, text="適用", width=5,
                   command=self._on_station_text).pack(side="left")

        ttk.Label(s, text="※ 時刻は送出PCの時計です。放送に出す場合はPCをNTP同期して"
                          "ください(NNNパケットに時刻は含まれません)。",
                  style="Muted.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", padx=2, pady=(2, 4))

    def _on_layer_toggle(self, key):
        self.L[key]["on"] = bool(self.on_vars[key].get())
        self._stage(f"/heli/ctrl/{LAYER_PREFIX[key] or 'Super'}on",
                    1 if self.L[key]["on"] else 0)
        if self.L[key]["on"]:
            self._select_layer(key)
        self._redraw_canvas()

    def _on_clock_format(self):
        fmt = self._fmt_lut.get(self.fmt_var.get(), "hm")
        date = self._date_lut.get(self.date_var.get(), "off")
        self.L["clock"]["format"] = fmt
        self.L["clock"]["date"] = date
        self._stage("/heli/ctrl/Clockformat", fmt)
        self._stage("/heli/ctrl/Clockdate", date)
        self._redraw_canvas()

    def _on_station_text(self):
        txt = self.station_var.get()
        if txt == self.L["station"].get("text"):
            return
        self.L["station"]["text"] = txt
        self._stage("/heli/ctrl/Stationtext", txt)
        self._redraw_canvas()

    # ---------- 見た目(編集中レイヤぶん) ----------
    def _build_look(self, parent):
        s = self._section(parent, "見た目")
        # どのレイヤを編集するか
        fr = ttk.Frame(s); fr.pack(fill="x", pady=(2, 6))
        ttk.Label(fr, text="編集する項目", width=16).pack(side="left")
        self.cur_var = tk.StringVar(value=self.cur)
        for key, label, _p in LAYERS:
            ttk.Radiobutton(fr, text=label, value=key, variable=self.cur_var,
                            command=lambda k=key: self._select_layer(k)).pack(
                side="left", padx=(0, 12))

        self._build_font(s)
        self.size_var = self._slider(s, "文字サイズ", 20, 250,
                                     self.L[self.cur]["size"], self._on_size)
        self._build_weight(s)
        self._build_align(s)
        self._build_colors(s)
        self.stroke_var = self._slider(s, "フチの太さ", 0, 20,
                                       self.L[self.cur]["sw"], self._on_strokewidth)
        self.opacity_var = self._slider(s, "透過率(%)", 0, 100,
                                        self.L[self.cur]["opacity"], self._on_opacity)
        ttk.Label(s, text="※ 100%=不透明。Fill/Key出しでは、この値がそのまま"
                          "キー信号になります。", style="Muted.TLabel",
                  wraplength=560, justify="left").pack(anchor="w", padx=2, pady=(0, 4))

    def _select_layer(self, key):
        """編集対象のレイヤを切り替え、ウィジェットへ値を流し込む."""
        self.cur = key
        self.cur_var.set(key)
        self._load_layer_widgets()
        self._redraw_canvas()

    def _load_layer_widgets(self):
        """self.L[self.cur] の値をウィジェットへ反映(OSCは送らない)."""
        d = self.L[self.cur]
        self._loading = True
        try:
            self.size_var.set(int(d["size"]))
            self.stroke_var.set(int(d["sw"]))
            self.opacity_var.set(int(d["opacity"]))
            w = d.get("weight", "Bold")
            if w in self._weight_values:
                self.weight_var.set(w)
            rev = {v: k for k, v in self._align_lut.items()}
            self.align_var.set(rev.get(d.get("align", "left"), "左寄せ"))
            name = d.get("font", "")
            if name and name in self._font_lut:
                self.font_var.set(name)
            elif self._font_names:
                # 保存時と一覧が変わっている場合はパスで探す
                path = d.get("font_path", "")
                hit = next((n for n, (p, _k) in self._font_lut.items() if p == path),
                           None)
                self.font_var.set(hit or self._font_names[0])
            self.fill_sw.config(bg=_hex(d["fill"]))
            self.stroke_sw.config(bg=_hex(d["stroke"]))
        finally:
            self._loading = False
        self._update_look_title()

    def _update_look_title(self):
        if hasattr(self, "pos_lbl"):
            d = self.L[self.cur]
            self.pos_lbl.config(
                text=f"［{LAYER_LABEL[self.cur]}］位置  X: {d['pos'][0]}  "
                     f"Y: {d['pos'][1]}  px"
                     f"（つかんで移動 / 矢印キー1px・Shiftで10px）")

    def _build_weight(self, parent):
        """可変フォント(同梱 Noto Sans JP VF)の太さ。非可変フォントでは無効."""
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="文字の太さ", width=16).pack(side="left")
        self._weight_values = ["Light", "Regular", "Medium", "SemiBold", "Bold",
                               "ExtraBold", "Black"]
        w = self.L[self.cur].get("weight", "Bold")
        self.weight_var = tk.StringVar(
            value=w if w in self._weight_values else "Bold")
        cb = ttk.Combobox(fr, textvariable=self.weight_var,
                          values=self._weight_values, state="readonly", width=12)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._on_weight())

    def _on_weight(self):
        if self._loading:
            return
        self.L[self.cur]["weight"] = self.weight_var.get()
        self._stage(self._addr_of("Fontweight"), self.weight_var.get())
        self._redraw_canvas()

    def _build_align(self, parent):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="文字揃え", width=16).pack(side="left")
        # 基準点(ドラッグ位置)に対して、左寄せ=右へ伸びる/右寄せ=左へ伸びる
        self._align_lut = {"左寄せ": "left", "中央": "center", "右寄せ": "right"}
        rev = {v: k for k, v in self._align_lut.items()}
        self.align_var = tk.StringVar(
            value=rev.get(self.L[self.cur].get("align", "left"), "左寄せ"))
        cb = ttk.Combobox(fr, textvariable=self.align_var,
                          values=list(self._align_lut), state="readonly", width=10)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._on_align())

    def _on_align(self):
        if self._loading:
            return
        ax = self._align_lut[self.align_var.get()]
        self.L[self.cur]["align"] = ax
        self._stage(self._addr_of("Alignx"), ax)
        self._redraw_canvas()

    def _build_font(self, parent):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="フォント", width=16).pack(side="left")
        self.font_var = tk.StringVar()
        self.font_cb = ttk.Combobox(fr, textvariable=self.font_var,
                                    state="readonly", width=26)
        self.font_cb.pack(side="left", fill="x", expand=True)
        self.font_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_font())
        # 市販フォント等(後入れフォント)は既定で隠す。放送での誤用を防ぐため。
        fr2 = ttk.Frame(parent); fr2.pack(fill="x", pady=(0, 2))
        ttk.Label(fr2, text="", width=16).pack(side="left")
        self.show_other_var = tk.BooleanVar(value=self.show_other_fonts)
        ttk.Checkbutton(fr2, text="その他のフォントも表示（EULA要確認）",
                        variable=self.show_other_var,
                        command=self._reload_fonts).pack(side="left")
        self._reload_fonts(keep=False)

    def _reload_fonts(self, keep=True):
        """フォント一覧を作り直す(「その他も表示」の切替時にも呼ばれる)."""
        self.show_other_fonts = bool(self.show_other_var.get())
        fonts = []
        if list_system_fonts:
            try:
                fonts = list_system_fonts(include_other=self.show_other_fonts)
            except Exception:
                fonts = []
        if not fonts:
            fonts = FALLBACK_FONTS
        # 後入れフォントは一覧でも分かるように印を付ける
        self._font_lut = {}
        for name, path, kind in fonts:
            label = f"{name}　［要確認］" if kind == "other" else name
            self._font_lut[label] = (path, kind)
        self._font_names = list(self._font_lut)
        prev = self.font_var.get() if keep else ""
        self.font_cb.config(values=self._font_names)
        if prev in self._font_lut:
            self.font_var.set(prev)
        else:
            # 保存値 → 同梱フォント → 一覧の先頭 の順で選ぶ
            want = self.L[self.cur].get("font", "")
            if want in self._font_lut:
                self.font_var.set(want)
            else:
                bundled = next((n for n, (_p, k) in self._font_lut.items()
                                if k == "bundled"), None)
                self.font_var.set(bundled or (self._font_names[0]
                                              if self._font_names else ""))
        if keep:
            self._redraw_canvas()

    def _on_font(self):
        if self._loading:
            return
        name = self.font_var.get()
        path, kind = self._font_lut.get(name, ("", ""))
        d = self.L[self.cur]
        d["font"], d["font_path"] = name, path
        if path:
            self._stage(self._addr_of("Fontpath"), path)   # gst: 実ファイル指定
        self._stage(self._addr_of("Font"), name)           # TD: フォント名
        if kind == "other":
            self._preset_flash("※ このフォントはライセンス(EULA)の確認が必要です")
        self._redraw_canvas()

    def _build_colors(self, parent):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=6)
        ttk.Label(fr, text="文字色(中)", width=16).pack(side="left")
        self.fill_sw = tk.Label(fr, text="   ", bg=_hex(self.L[self.cur]["fill"]),
                                relief="solid", width=4)
        self.fill_sw.pack(side="left", padx=4)
        ttk.Button(fr, text="選ぶ", width=5, command=self._pick_fill).pack(side="left")
        fr2 = ttk.Frame(parent); fr2.pack(fill="x", pady=6)
        ttk.Label(fr2, text="フチ色", width=16).pack(side="left")
        self.stroke_sw = tk.Label(fr2, text="   ", bg=_hex(self.L[self.cur]["stroke"]),
                                  relief="solid", width=4)
        self.stroke_sw.pack(side="left", padx=4)
        ttk.Button(fr2, text="選ぶ", width=5, command=self._pick_stroke).pack(side="left")

    # ---------- OSC アドレス生成 ----------
    def _addr_of(self, name: str, key: str | None = None) -> str:
        """レイヤ接頭辞を付けた /heli/ctrl/... を返す(住所は接頭辞なし)."""
        pfx = LAYER_PREFIX[key or self.cur]
        return f"/heli/ctrl/{pfx}{name.lower() if pfx else name}"

    # ---------- 変更の一時保留と「決定」での反映 ----------
    def _stage(self, address, *args):
        """見た目・配置の変更を溜める(決定ボタンで一括反映)."""
        self._pending[address] = args
        self._mark_dirty()

    def _mark_dirty(self):
        n = len(self._pending)
        if hasattr(self, "apply_btn"):
            if n:
                self.apply_btn.config(text=f"決定（反映）  未反映 {n} 件", state="normal")
            else:
                self.apply_btn.config(text="決定（反映）", state="disabled")

    def _apply_pending(self):
        """溜めた見た目・配置の変更をまとめて送信(反映)."""
        for address, args in self._pending.items():
            self.osc.send(address, *args)
        self._pending.clear()
        self._mark_dirty()

    def _broadcast_look(self):
        """現在の見た目・位置を送出側へ即時送信(起動時の同期用)."""
        for key, _label, pfx in LAYERS:
            d = self.L[key]
            a = lambda n, k=key: self._addr_of(n, k)
            self.osc.send(f"/heli/ctrl/{pfx or 'Super'}on", 1 if d["on"] else 0)
            if d.get("font_path"):
                self.osc.send(a("Fontpath"), d["font_path"])
            if d.get("font"):
                self.osc.send(a("Font"), d["font"])
            self.osc.send(a("Fontsize"), int(d["size"]))
            self.osc.send(a("Strokewidth"), int(d["sw"]))
            self.osc.send(a("Alignx"), d["align"])
            self.osc.send(a("Aligny"), "top")
            self.osc.send(a("Fontweight"), d.get("weight", "Bold"))
            self.osc.send(a("Opacity"), float(d["opacity"]) / 100.0)
            for comp, ch in (("r", 0), ("g", 1), ("b", 2)):
                self.osc.send(a(f"Fontcolor{comp}"), float(d["fill"][ch]))
                self.osc.send(a(f"Strokecolor{comp}"), float(d["stroke"][ch]))
            self.osc.send(a("Posx"), float(d["pos"][0]))
            self.osc.send(a("Posy"), float(d["pos"][1]))
        self.osc.send("/heli/ctrl/Clockformat", self.L["clock"].get("format", "hm"))
        self.osc.send("/heli/ctrl/Clockdate", self.L["clock"].get("date", "off"))
        self.osc.send("/heli/ctrl/Stationtext", self.L["station"].get("text", ""))
        # 住所の見せ方
        a = self.A
        self.osc.send("/heli/ctrl/Addrlevel", a["level"])
        self.osc.send("/heli/ctrl/Addrdroppref", 1 if a["droppref"] else 0)
        self.osc.send("/heli/ctrl/Addrdropmuni", 1 if a["dropmuni"] else 0)
        self.osc.send("/heli/ctrl/Addrsep", a["sep"])
        self.osc.send("/heli/ctrl/Addroffshore", a["offshore"])
        self.osc.send("/heli/ctrl/Addrsuffix", a["suffix"])
        self.osc.send("/heli/ctrl/Addrsuffixon", 1 if a["suffixon"] else 0)
        # 地図スーパー(選択制)
        self.osc.send("/heli/ctrl/Mapon", 1 if self.map_on else 0)
        self.osc.send("/heli/ctrl/Maptrail", 1 if self.map_trail else 0)
        self.osc.send("/heli/ctrl/Mapw", int(self.map_w))
        self.osc.send("/heli/ctrl/Maph", int(self._map_h()))
        self.osc.send("/heli/ctrl/Mapspan", float(self.map_span))
        self.osc.send("/heli/ctrl/Mapx", float(self.map_pos[0]))
        self.osc.send("/heli/ctrl/Mapy", float(self.map_pos[1]))

    # ---------- 設定の保存・呼出 ----------
    def _collect_settings(self) -> dict:
        return {
            "layers": {k: dict(v) for k, v in self.L.items()},
            "addr": dict(self.A),
            "font_show_other": bool(self.show_other_fonts),
            "map_on": bool(self.map_on),
            "map_pos": list(self.map_pos),
            "map_w": int(self.map_w_var.get()),
            "map_span": max(0.05, min(1.2, int(self.map_span_var.get()) / 100.0)),
            "map_trail": bool(self.map_trail),
        }

    def _save_settings(self):
        """現在の見た目・位置を次回起動時の既定として保存(プリセットは保持)."""
        full = _load_settings()
        full.update(self._collect_settings())     # トップレベル=起動時の既定
        ok = _write_settings(full)
        self.save_btn.config(text="保存しました" if ok else "保存失敗")
        self.root.after(1500, lambda: self.save_btn.config(text="既定として保存"))

    def _apply_settings(self, d: dict):
        """設定dictをUIに反映し、送出側へも即時送信(プリセット呼出用)."""
        self.L = _layers_from_saved(d)
        self.A = _addr_from_saved(d)
        self.show_other_fonts = bool(d.get("font_show_other", self.show_other_fonts))
        self.show_other_var.set(self.show_other_fonts)
        self._reload_fonts(keep=False)
        for key, _l, _p in LAYERS:
            self.on_vars[key].set(bool(self.L[key]["on"]))
        rev = {v: k for k, v in self._fmt_lut.items()}
        self.fmt_var.set(rev.get(self.L["clock"].get("format", "hm"),
                                 CLOCK_FMT[0][0]))
        rev2 = {v: k for k, v in self._date_lut.items()}
        self.date_var.set(rev2.get(self.L["clock"].get("date", "off"),
                                   CLOCK_DATE[0][0]))
        self.station_var.set(self.L["station"].get("text", ""))
        # 住所の見せ方
        a = self.A
        lv = {v: k for k, v in {lab: v for lab, v in ADDRLEVEL}.items()}
        self.level_var.set(lv.get(a["level"], ADDRLEVEL[1][0]))
        self.droppref_var.set(bool(a["droppref"]))
        self.dropmuni_var.set(bool(a["dropmuni"]))
        self.sep_var.set({v: k for k, v in self._sep_lut.items()}.get(
            a["sep"], ADDR_SEP[0][0]))
        self.offshore_var.set({v: k for k, v in self._off_lut.items()}.get(
            a["offshore"], ADDR_OFFSHORE[0][0]))
        self.suffix_var.set(a["suffix"])
        self.suffixon_var.set(bool(a["suffixon"]))
        self._update_addr_sample()
        # 地図スーパー
        self.map_on = bool(d.get("map_on", self.map_on))
        self.map_on_var.set(self.map_on)
        self.map_trail = bool(d.get("map_trail", self.map_trail))
        self.map_trail_var.set(self.map_trail)
        self.map_pos = list(d.get("map_pos", self.map_pos))
        self.map_w = int(d.get("map_w", self.map_w))
        self.map_w_var.set(self.map_w)
        self.map_span = float(d.get("map_span", self.map_span))
        self.map_span_var.set(int(round(self.map_span * 100)))
        self._load_layer_widgets()
        self._redraw_canvas()
        self._broadcast_look()              # 呼出は即反映(決定不要)
        self._pending.clear(); self._mark_dirty()

    def _build_presets(self, parent):
        s = self._section(parent, "番組プリセット(名前を付けて保存/呼出)")
        self._preset_name_vars = []
        for i in range(N_PRESETS):
            fr = ttk.Frame(s); fr.pack(fill="x", pady=2)
            saved = self._presets[i] if i < len(self._presets) else {}
            var = tk.StringVar(value=(saved.get("name") or f"番組{i + 1}"))
            self._preset_name_vars.append(var)
            ttk.Entry(fr, textvariable=var, width=18).pack(side="left", padx=(0, 4))
            ttk.Button(fr, text="呼出", width=6,
                       command=lambda i=i: self._recall_preset(i)).pack(side="left")
            ttk.Button(fr, text="保存", width=6,
                       command=lambda i=i: self._save_preset(i)).pack(side="left", padx=4)
        self.preset_msg = ttk.Label(s, text="", foreground="#0a0")
        self.preset_msg.pack(anchor="w", padx=2, pady=(2, 4))

    def _preset_flash(self, msg: str):
        if hasattr(self, "preset_msg"):
            self.preset_msg.config(text=msg)
            self.root.after(2500, lambda: self.preset_msg.config(text=""))

    def _save_preset(self, i: int):
        """現在の見た目・位置を i 番目の番組プリセットに保存."""
        full = _load_settings()
        presets = list(full.get("presets", []))
        while len(presets) <= i:
            presets.append({})
        name = self._preset_name_vars[i].get().strip() or f"番組{i + 1}"
        presets[i] = {"name": name, "settings": self._collect_settings()}
        full["presets"] = presets
        self._presets = presets
        ok = _write_settings(full)
        self._preset_flash(f"「{name}」に保存しました" if ok else "保存失敗")

    def _recall_preset(self, i: int):
        """i 番目の番組プリセットを呼び出して反映."""
        full = _load_settings()
        presets = full.get("presets", [])
        if i < len(presets) and presets[i].get("settings"):
            self._apply_settings(presets[i]["settings"])
            nm = presets[i].get("name") or f"番組{i + 1}"
            self._preset_flash(f"「{nm}」を呼び出しました")
        else:
            self._preset_flash("このプリセットは未保存です")

    # ---------- 配置 ----------
    def _make_backdrop(self):
        """WYSIWYGプレビューの背景(暗色+セーフエリア目安)を作る."""
        bg = Image.new("RGB", (CANVAS_W, CANVAS_H), (34, 38, 52))
        d = ImageDraw.Draw(bg)
        for i in range(CANVAS_H):            # ゆるいグラデーション
            t = i / CANVAS_H
            d.line([(0, i), (CANVAS_W, i)],
                   fill=(int(34 + 8 * t), int(38 + 8 * t), int(52 + 10 * t)))
        d.rectangle([CANVAS_W * 0.05, CANVAS_H * 0.05,
                     CANVAS_W * 0.95, CANVAS_H * 0.95], outline=(96, 104, 128))
        d.line([(0, CANVAS_H * 2 / 3), (CANVAS_W, CANVAS_H * 2 / 3)],
               fill=(70, 78, 100))
        return np.asarray(bg, dtype=np.uint8)

    def _build_place(self, parent):
        s = self._section(parent, "配置")
        mode = "実フォントでプレビュー表示" if self._pv_renderer else "簡易表示"
        ttk.Label(s, text=f"文字をつかんでドラッグ(離すと確定)。つかむと編集対象も"
                          f"切り替わります。矢印キーで微調整。［{mode}］",
                  style="Muted.TLabel", wraplength=560,
                  justify="left").pack(pady=4)
        self.canvas = tk.Canvas(s, width=CANVAS_W, height=CANVAS_H, bg="#22262f",
                                highlightthickness=0, takefocus=1)
        self.canvas.pack(pady=6)
        self.pos_lbl = ttk.Label(s, text="", style="Muted.TLabel")
        self.pos_lbl.pack(anchor="w", padx=2)
        fr = ttk.Frame(s); fr.pack(fill="x", pady=(4, 6))
        ttk.Button(fr, text="表示中の項目を縦に並べ直す",
                   command=self._restack).pack(side="left")
        ttk.Label(fr, text="（編集中の項目の位置・揃えを基準に、上から順に重ならず並べます）",
                  style="Muted.TLabel").pack(side="left", padx=6)

        if self._pv_renderer:
            # WYSIWYG: 1枚の画像アイテムに本番同等の描画を貼る
            self._img_item = self.canvas.create_image(0, 0, anchor="nw")
            self._photo = None
        else:
            # フォールバック: tkのテキストで簡易表示
            self.canvas.create_rectangle(2, 2, CANVAS_W - 2, CANVAS_H - 2, outline="#aaa")
            self.canvas.create_rectangle(CANVAS_W * 0.05, CANVAS_H * 0.05,
                                         CANVAS_W * 0.95, CANVAS_H * 0.95,
                                         outline="#556", dash=(3, 3))
            self._txt_items = {}
            for key, _l, _p in LAYERS:
                sh = self.canvas.create_text(0, 0, anchor="nw", text="", fill="black")
                tx = self.canvas.create_text(0, 0, anchor="nw", text="", fill="white")
                self._txt_items[key] = (sh, tx)

        # 地図スーパーの枠(ONのとき表示・ドラッグで位置決め)
        self._map_box = self.canvas.create_rectangle(0, 0, 0, 0, outline="#64d2ff",
                                                     width=2, state="hidden")
        self._map_lbl = self.canvas.create_text(0, 0, text="地図", anchor="nw",
                                                fill="#64d2ff", state="hidden")
        # 編集中レイヤの枠(常時表示) と ドラッグ中のゴースト枠
        self._sel_box = self.canvas.create_rectangle(0, 0, 0, 0, outline="#8e8e93",
                                                     dash=(2, 3), state="hidden")
        self._ghost_box = self.canvas.create_rectangle(0, 0, 0, 0, outline="#0a84ff",
                                                       dash=(3, 2), width=2,
                                                       state="hidden")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        # 矢印キーで1px(Shiftで10px)微調整。テキスト入力中は邪魔しない。
        for key, dx, dy in (("<Up>", 0, -1), ("<Down>", 0, 1),
                            ("<Left>", -1, 0), ("<Right>", 1, 0)):
            self.root.bind(key, lambda e, dx=dx, dy=dy: self._on_arrow(e, dx, dy))

    def _on_arrow(self, e, dx, dy):
        # Entry/Spinbox/Combobox にフォーカスがあるときは、その操作を優先
        w = self.root.focus_get()
        cls = w.winfo_class() if w is not None else ""
        if cls in ("TEntry", "Entry", "TSpinbox", "Spinbox", "TCombobox"):
            return
        step = 10 if (e.state & 0x1) else 1        # Shiftで10px
        self._nudge(dx * step, dy * step)
        return "break"

    def _build_map(self, parent):
        s = self._section(parent, "地図スーパー(選択制・既定OFF)")
        ttk.Label(s, text="★ Fill/Key・バーンインで ON にすると地図が放送に出ます。"
                          "現状の運用では OFF のままにしてください。"
                          "位置の確認は下の「地図」ボタン（PC画面のみ）でできます。",
                  style="Muted.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", pady=(2, 6))

        fr = ttk.Frame(s); fr.pack(fill="x", pady=3)
        self.map_on_var = tk.BooleanVar(value=self.map_on)
        ttk.Checkbutton(fr, text="地図スーパーを出す", variable=self.map_on_var,
                        command=self._on_map_toggle).pack(side="left")
        self.map_trail_var = tk.BooleanVar(value=self.map_trail)
        ttk.Checkbutton(fr, text="軌跡を描く", variable=self.map_trail_var,
                        command=self._on_map_trail).pack(side="left", padx=14)

        # 大きさ(幅)。高さは 4:3 で連動
        self.map_w_var = self._slider(s, "地図の大きさ(幅px)", 200, 800,
                                      self.map_w, self._on_map_size)
        # 表示範囲(経度スパン)。整数スライダーの値/100 を度として送る
        fr2 = ttk.Frame(s); fr2.pack(fill="x", pady=3)
        ttk.Label(fr2, text="表示範囲(広さ)", width=16).pack(side="left")
        self.map_span_var = tk.IntVar(value=int(round(self.map_span * 100)))

        def emit_span(*_a):
            if self._loading:
                return
            try:
                v = max(5, min(120, int(self.map_span_var.get())))
            except Exception:
                return
            if v != self.map_span_var.get():
                self.map_span_var.set(v)
            self.map_span = v / 100.0
            self._stage("/heli/ctrl/Mapspan", float(self.map_span))
            self._redraw_canvas()
        sb = ttk.Spinbox(fr2, from_=5, to=120, textvariable=self.map_span_var,
                         width=5, command=emit_span)
        sb.pack(side="right")
        sb.bind("<Return>", emit_span)
        sb.bind("<FocusOut>", emit_span)
        ttk.Scale(fr2, from_=5, to=120, variable=self.map_span_var,
                  command=lambda _v: emit_span()).pack(side="left", fill="x",
                                                       expand=True, padx=4)
        ttk.Label(s, text="※ 数字が小さいほど拡大(0.05〜1.2度)。位置は「配置」の枠を"
                          "ドラッグして決めます。", style="Muted.TLabel").pack(anchor="w")

    def _on_map_toggle(self):
        self.map_on = bool(self.map_on_var.get())
        self._stage("/heli/ctrl/Mapon", 1 if self.map_on else 0)
        self._redraw_canvas()

    def _on_map_trail(self):
        self.map_trail = bool(self.map_trail_var.get())
        self._stage("/heli/ctrl/Maptrail", 1 if self.map_trail else 0)

    def _on_map_size(self, v):
        self.map_w = int(v)
        self._stage("/heli/ctrl/Mapw", int(self.map_w))
        self._stage("/heli/ctrl/Maph", int(round(self.map_w * 0.75)))
        self._redraw_canvas()

    def _map_h(self) -> int:
        return int(round(self.map_w * 0.75))

    def _send_map_pos(self):
        self._stage("/heli/ctrl/Mapx", float(self.map_pos[0]))
        self._stage("/heli/ctrl/Mapy", float(self.map_pos[1]))

    def _map_box_canvas(self):
        """地図枠のキャンバス座標 (x0, y0, x1, y1)."""
        x0 = self.map_pos[0] / SCALE
        y0 = self.map_pos[1] / SCALE
        return (x0, y0, x0 + self.map_w / SCALE, y0 + self._map_h() / SCALE)

    def _build_apply_bar(self):
        # 見た目・配置の変更は、ここを押すまで送出側に反映しない。
        # 誤操作で本番のスーパーが即変わるのを防ぐ。
        ap = ttk.Frame(self.root); ap.pack(side="bottom", fill="x", padx=10, pady=(2, 4))
        self.apply_btn = ttk.Button(ap, text="決定（反映）", state="disabled",
                                    style="Accent.TButton", command=self._apply_pending)
        self.apply_btn.pack(side="left", fill="x", expand=True)
        self.save_btn = ttk.Button(ap, text="既定として保存", width=14,
                                   command=self._save_settings)
        self.save_btn.pack(side="right")
        if MapWindow is not None:
            ttk.Button(ap, text="地図", width=6,
                       command=self._open_map).pack(side="right", padx=(0, 6))

    def _open_map(self):
        if MapWindow is None:
            return
        if self.map_win is not None and self.map_win.alive():
            try:
                self.map_win.top.lift()
            except Exception:
                pass
            return
        try:
            self.map_win = MapWindow(self.root, self._palette)
        except Exception:
            self.map_win = None

    def _build_status(self):
        pal = self._palette or {}
        bg = pal.get("bg", "#f5f5f7"); ink = pal.get("ink", "#1d1d1f")
        muted = pal.get("muted", "#6e6e73"); fam = pal.get("family", "")
        st = ttk.LabelFrame(self.root, text="受信状態")
        st.pack(side="bottom", fill="x", padx=10, pady=8)
        self.recv_lbl = tk.Label(st, text="● 未受信", fg="white",
                                 bg=pal.get("neutral", "#8e8e93"),
                                 font=(fam, 12, "bold")); self.recv_lbl.pack(fill="x", padx=6, pady=4)
        self.super_lbl = tk.Label(st, text="―", font=(fam, 18, "bold"),
                                  bg=bg, fg=ink); self.super_lbl.pack(pady=2)
        # 10進度とDMS(度分秒)を2行で表示
        self.info_lbl = tk.Label(st, text="緯度 --  経度 --  高度 --", justify="left",
                                 bg=bg, fg=ink); self.info_lbl.pack(anchor="w", padx=6)
        self.dms_lbl = tk.Label(st, text="DMS  緯度 --  経度 --", justify="left",
                                bg=bg, fg=muted); self.dms_lbl.pack(anchor="w", padx=6)
        self.fix_lbl = tk.Label(st, text="測位 --  衛星 --", bg=bg,
                                fg=muted); self.fix_lbl.pack(pady=2)

    # ---------- 見た目のコールバック ----------
    def _on_size(self, v):
        self.L[self.cur]["size"] = int(v)
        self._stage(self._addr_of("Fontsize"), int(v))
        self._redraw_canvas()

    def _on_strokewidth(self, v):
        self.L[self.cur]["sw"] = int(v)
        self._stage(self._addr_of("Strokewidth"), int(v))
        self._redraw_canvas()

    def _on_opacity(self, v):
        self.L[self.cur]["opacity"] = int(v)
        self._stage(self._addr_of("Opacity"), float(v) / 100.0)
        self._redraw_canvas()

    def _pick_fill(self):
        d = self.L[self.cur]
        rgb, hx = colorchooser.askcolor(color=_hex(d["fill"]),
                                        title=f"{LAYER_LABEL[self.cur]}の文字色(中)")
        if rgb is None:
            return
        d["fill"] = [c / 255 for c in rgb]; self.fill_sw.config(bg=hx)
        for comp, ch in (("r", 0), ("g", 1), ("b", 2)):
            self._stage(self._addr_of(f"Fontcolor{comp}"), float(d["fill"][ch]))
        self._redraw_canvas()

    def _pick_stroke(self):
        d = self.L[self.cur]
        rgb, hx = colorchooser.askcolor(color=_hex(d["stroke"]),
                                        title=f"{LAYER_LABEL[self.cur]}のフチ色")
        if rgb is None:
            return
        d["stroke"] = [c / 255 for c in rgb]; self.stroke_sw.config(bg=hx)
        for comp, ch in (("r", 0), ("g", 1), ("b", 2)):
            self._stage(self._addr_of(f"Strokecolor{comp}"), float(d["stroke"][ch]))
        self._redraw_canvas()

    # ---------- 配置(ドラッグ) ----------
    def _layer_text(self, key: str) -> str:
        if key == "addr":
            # まだ受信していないときは、現在の「住所の見せ方」の見本を出す。
            # 設定を変えた結果がそのまま配置プレビューで確認できる。
            return self.super_text or self._sample_text()
        if key == "clock":
            return clock_text(self.L["clock"].get("format", "hm"),
                              self.L["clock"].get("date", "off"))
        return self.L["station"].get("text", "") or "(局名)"

    def _visible_layers(self) -> list[str]:
        return [k for k, _l, _p in LAYERS if self.L[k]["on"]]

    def _hit_layer(self, x, y) -> str | None:
        """(x,y) にあるレイヤ。重なりは上のレイヤ(後に描くもの)を優先."""
        for key in reversed(self._visible_layers()):
            bb = self._bboxes.get(key)
            if bb and bb[0] - 4 <= x <= bb[2] + 4 and bb[1] - 4 <= y <= bb[3] + 4:
                return key
        return None

    def _map_hit(self, x, y) -> bool:
        if not self.map_on:
            return False
        x0, y0, x1, y1 = self._map_box_canvas()
        return x0 - 3 <= x <= x1 + 3 and y0 - 3 <= y <= y1 + 3

    def _press(self, e):
        self.canvas.focus_set()          # 以後の矢印キーは位置調整へ
        if self._map_hit(e.x, e.y):
            x0, y0, _x1, _y1 = self._map_box_canvas()
            self._drag_off = (e.x - x0, e.y - y0)
            self._dragging = "map"
            self._redraw_canvas()
            return
        key = self._hit_layer(e.x, e.y)
        if key:
            if key != self.cur:
                self._select_layer(key)  # つかんだ項目を編集対象にする
            ax, ay = (self.L[key]["pos"][0] / SCALE, self.L[key]["pos"][1] / SCALE)
            self._drag_off = (e.x - ax, e.y - ay)
            self._dragging = key
            self._redraw_canvas()
        else:
            # 空白クリック: そこを編集中レイヤの中央にする(角ではなく中央=直感的)
            self._place_center(e.x, e.y)

    def _drag_move(self, e):
        if not self._dragging:
            return
        ox, oy = self._drag_off
        cx = max(0, min(CANVAS_W, e.x - ox))
        cy = max(0, min(CANVAS_H, e.y - oy))
        if self._dragging == "map":
            self.map_pos = [int(cx * SCALE), int(cy * SCALE)]
            self._redraw_canvas(); self._send_map_pos()
        else:
            self.L[self._dragging]["pos"] = [int(cx * SCALE), int(cy * SCALE)]
            self._redraw_canvas(); self._send_pos(self._dragging)

    def _drag_end(self, _e=None):
        if self._dragging:
            self._dragging = False
            self._redraw_canvas()

    def _place_center(self, cxp, cyp):
        """キャンバス座標(cxp,cyp)を編集中レイヤの中央に合わせて基準点を決める."""
        d = self.L[self.cur]
        bb = self._bboxes.get(self.cur)
        w = (bb[2] - bb[0]) if bb else 0
        h = (bb[3] - bb[1]) if bb else 0
        # アンカー(横)から中央へのオフセット: left=+w/2, center=0, right=-w/2
        dx = {"left": w / 2, "center": 0, "right": -w / 2}.get(d["align"], w / 2)
        ax = max(0, min(CANVAS_W, cxp - dx))
        ay = max(0, min(CANVAS_H, cyp - h / 2))   # 縦は上端基準
        d["pos"] = [int(ax * SCALE), int(ay * SCALE)]
        self._redraw_canvas(); self._send_pos(self.cur)

    def _restack(self):
        """表示中の項目を縦に並べ直す(文字サイズが違っても重ならない)."""
        keys = self._visible_layers()
        if not keys:
            return
        head = self.L[self.cur] if self.cur in keys else self.L[keys[0]]
        x, y, align = head["pos"][0], head["pos"][1], head["align"]
        for k in keys:
            d = self.L[k]
            d["pos"] = [int(x), int(y)]
            d["align"] = align
            self._stage(self._addr_of("Alignx", k), align)
            self._send_pos(k)
            y += d["size"] * LINE_PITCH
        self._load_layer_widgets()
        self._redraw_canvas()

    def _nudge(self, dx, dy):
        d = self.L[self.cur]
        d["pos"] = [d["pos"][0] + dx, d["pos"][1] + dy]
        self._redraw_canvas(); self._send_pos(self.cur)

    def _send_pos(self, key):
        d = self.L[key]
        self._stage(self._addr_of("Posx", key), float(d["pos"][0]))
        self._stage(self._addr_of("Posy", key), float(d["pos"][1]))

    # ---------- プレビュー描画 ----------
    def _redraw_canvas(self):
        if getattr(self, "_pv_renderer", None):
            self._render_wysiwyg()
        elif hasattr(self, "_txt_items"):
            self._render_text()
        self._update_boxes()
        self._update_look_title()

    def _pv_layer(self, key: str):
        """プレビュー用に、本番の見た目をキャンバス縮尺へ落としたレイヤを作る."""
        sc = self._pv_scale
        d = self.L[key]
        st = self._pv_styles[key]
        st.font_path = self._font_lut.get(d.get("font", ""), (None, ""))[0] \
            or d.get("font_path") or None
        st.font_size = max(6, int(round(d["size"] * sc)))
        st.font_weight = d.get("weight", "Bold")
        st.stroke_width = max(0, int(round(d["sw"] * sc)))
        st.color = tuple(int(c * 255) for c in d["fill"])
        st.stroke_color = tuple(int(c * 255) for c in d["stroke"])
        st.opacity = int(max(0, min(100, d["opacity"])) * 255 / 100)
        st.align_x = d["align"]
        st.align_y = "top"
        st.margin_x = int(round(d["pos"][0] * sc))
        st.margin_y = int(round(d["pos"][1] * sc))
        return Layer(key, self._layer_text(key), st)

    def _render_wysiwyg(self):
        """本番と同じ Pillow レンダラで配置プレビューを描く(WYSIWYG)."""
        try:
            lays = [self._pv_layer(k) for k in self._visible_layers()]
            telop = self._pv_renderer.render_layers(lays)   # H×W×4 RGBA
            a = telop[:, :, 3:4].astype(np.float32) / 255.0
            out = self._backdrop.astype(np.float32) * (1 - a) + \
                telop[:, :, :3].astype(np.float32) * a
            img = Image.fromarray(out.astype(np.uint8), "RGB")
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.itemconfig(self._img_item, image=self._photo)
            self._bboxes = {}
            for lay in lays:
                bb = self._pv_renderer.layer_bbox(lay)
                if bb:
                    self._bboxes[lay.key] = bb
        except Exception:
            self._bboxes = {}

    def _render_text(self):
        """フォールバック: tkのテキストで簡易表示."""
        self._bboxes = {}
        for key, _l, _p in LAYERS:
            sh, tx = self._txt_items[key]
            if not self.L[key]["on"]:
                self.canvas.itemconfig(sh, text=""); self.canvas.itemconfig(tx, text="")
                continue
            d = self.L[key]
            cx, cy = d["pos"][0] / SCALE, d["pos"][1] / SCALE
            csize = max(6, int(d["size"] / SCALE))
            font = ("", csize, "bold")
            txt = self._layer_text(key)
            anchor = {"left": "nw", "center": "n", "right": "ne"}.get(d["align"], "nw")
            self.canvas.itemconfig(sh, text=txt, fill=_hex(d["stroke"]),
                                   font=font, anchor=anchor)
            self.canvas.itemconfig(tx, text=txt, fill=_hex(d["fill"]),
                                   font=font, anchor=anchor)
            self.canvas.coords(tx, cx, cy)
            self.canvas.coords(sh, cx + 1, cy + 1)
            bb = self.canvas.bbox(tx)
            if bb:
                self._bboxes[key] = bb

    def _update_boxes(self):
        # 地図枠(ONのとき常時表示。ドラッグで位置決め)
        if getattr(self, "_map_box", None) is not None:
            if self.map_on:
                x0, y0, x1, y1 = self._map_box_canvas()
                self.canvas.coords(self._map_box, x0, y0, x1, y1)
                self.canvas.coords(self._map_lbl, x0 + 3, y0 + 2)
                self.canvas.itemconfig(self._map_box, state="normal")
                self.canvas.itemconfig(self._map_lbl, state="normal")
                self.canvas.tag_raise(self._map_box)
                self.canvas.tag_raise(self._map_lbl)
            else:
                self.canvas.itemconfig(self._map_box, state="hidden")
                self.canvas.itemconfig(self._map_lbl, state="hidden")
        # 編集中レイヤの枠(どれを操作しているか分かるように)
        sel = self._bboxes.get(self.cur) if self.L[self.cur]["on"] else None
        if self._sel_box is not None:
            if sel and self._dragging != self.cur:
                self.canvas.coords(self._sel_box, sel[0] - 3, sel[1] - 3,
                                   sel[2] + 3, sel[3] + 3)
                self.canvas.itemconfig(self._sel_box, state="normal")
                self.canvas.tag_raise(self._sel_box)
            else:
                self.canvas.itemconfig(self._sel_box, state="hidden")
        # ドラッグ中は外接枠を強調(位置合わせの目安)
        if self._ghost_box is None:
            return
        bb = self._bboxes.get(self._dragging) if isinstance(self._dragging, str) else None
        if bb:
            self.canvas.coords(self._ghost_box, bb[0] - 2, bb[1] - 2, bb[2] + 2, bb[3] + 2)
            self.canvas.itemconfig(self._ghost_box, state="normal")
            self.canvas.tag_raise(self._ghost_box)
        else:
            self.canvas.itemconfig(self._ghost_box, state="hidden")

    def _tick_clock(self):
        """時刻レイヤがONのとき、プレビューの時計を進める."""
        if self.L["clock"]["on"]:
            self._redraw_canvas()
        self.root.after(1000, self._tick_clock)

    # ---------- 状態受信 ----------
    def _poll(self):
        try:
            while True:
                a, args = self.osc.inbox.get_nowait()
                self._on_status(a, args)
        except queue.Empty:
            pass
        # メッセージが途切れた=送出アプリが停止/未接続(GPS途絶とは区別)
        pal = self._palette or {}
        if time.monotonic() - self._last_status > STALE_SEC:
            self.recv_lbl.config(text="● アプリ未接続/停止", bg=pal.get("neutral", "gray"))
        self.root.after(200, self._poll)

    def _on_status(self, a, args):
        self._last_status = time.monotonic()   # アプリからの通信あり
        pal = self._palette or {}
        if a == "/heli/super" and args:
            self.super_text = args[0]
            self.super_lbl.config(text=args[0] or "(表示なし)")
            self._redraw_canvas()
        elif a == "/heli/position" and len(args) >= 3:
            lat, lon, alt = args[0], args[1], args[2]
            self.info_lbl.config(text=f"緯度 {lat:.6f}  経度 {lon:.6f}  高度 {alt:.0f}m")
            self.dms_lbl.config(text=f"DMS  緯度 {deg_to_dms_str(lat)}  "
                                     f"経度 {deg_to_dms_str(lon)}")
            # 地図ウィンドウが開いていれば位置を反映
            if self.map_win is not None and self.map_win.alive():
                try:
                    self.map_win.update_position(lat, lon, self.super_text)
                except Exception:
                    pass
        elif a == "/heli/status" and len(args) >= 3:
            # 新形式: (受信中1/0, 測位, 衛星)。受信可否で色分け。
            receiving = bool(args[0])
            if receiving:
                self.recv_lbl.config(text="● 受信中", bg=pal.get("ok", "#1a9d47"))
            else:
                self.recv_lbl.config(text="● GPS途絶(直近を保持)", bg=pal.get("warn", "#d23b3b"))
            fix = {0: "正常", 1: "バックアップ", 2: "使用不能"}.get(args[1], "?")
            sats = "--" if args[2] < 0 else args[2]
            self.fix_lbl.config(text=f"測位 {fix}  衛星 {sats}")


def main():
    ap = argparse.ArgumentParser(description="ヘリGPS スーパー制御UI")
    ap.add_argument("--td-host", default="127.0.0.1")
    ap.add_argument("--ctrl-port", type=int, default=9001)
    ap.add_argument("--status-port", type=int, default=9002)
    args = ap.parse_args()
    osc = OscClient(args.td_host, args.ctrl_port, args.status_port)
    root = tk.Tk()
    if ui_theme is not None:
        try:
            root._palette = ui_theme.apply_theme(root)
        except Exception:
            root._palette = None
    ControlUI(root, osc)
    root.protocol("WM_DELETE_WINDOW", lambda: (osc.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
