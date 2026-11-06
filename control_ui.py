"""ヘリGPSスーパー 外部制御UI (tkinter).

送出本体(gst_heli)と同じ OSC プロトコルで操作する制御パネル。

    UI → OSC 127.0.0.1:9001 → gst_heli.app(--osc-control)
    gst → OSC 127.0.0.1:9002 → このUI(状態表示)

画面:
    全画面の操作卓で使う想定。住所・配置・見た目を**横並び**に置き、
    スクロールせずに全項目へ届くようにしてある。
    住所/時刻/局名の3項目は**それぞれ別の列**でまとめて編集できる。
    ライト/ダークと文字サイズ(小/中/大)は右上で切り替えられる。

注意:
    **地図を放送映像に重ねる機能はありません。** 位置をPC画面で見るには
    右上の「地図」ボタン(別ウィンドウ)を使う。
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

# レイヤ(表示項目)。OSC名の接頭辞つき。
#   住所は接頭辞なし(Fontsize 等)= 送出側の旧名との後方互換のため。
LAYERS = [("addr", "住所", ""), ("clock", "時刻", "Clock"),
          ("station", "局名", "Station")]
LAYER_LABEL = {k: lab for k, lab, _p in LAYERS}
LAYER_PREFIX = {k: p for k, _lab, p in LAYERS}

CLOCK_FMT = [("分まで (12:34)", "hm"), ("秒まで (12:34:56)", "hms")]
CLOCK_DATE = [("日付なし", "off"), ("11/4", "slash"), ("11月4日", "kanji")]
ADDR_SEP = [("区切りなし", ""), ("・（中黒）", "・"), ("　（スペース）", " ")]
ADDR_OFFSHORE = [("沖", "沖"), ("沿岸", "沿岸"), ("付けない", "")]
UI_SCALES = [("小", 1.0), ("中", 1.5), ("大", 2.0)]

STALE_SEC = 3.0
FRAME_W, FRAME_H = 1920, 1080
CANVAS_W, CANVAS_H = 464, 261
SCALE = FRAME_W / CANVAS_W          # 約4.14
LINE_PITCH = 1.3                    # 縦並びの行送り(文字サイズ × この係数)

# レイヤの既定値。**3項目とも同じ位置・同じ文字サイズ・同じ色で縦並び**(左下)。
# gst_heli/renderer.py の DEFAULT_* と同じ値(あちらは送出側の既定)。
DEF_SIZE, DEF_X, DEF_TOP, DEF_PITCH = 72, 80, 727, 93


def _layer_default(i: int, **extra) -> dict:
    d = dict(on=True, size=DEF_SIZE, weight="Bold", align="left", sw=5,
             fill=[1.0, 1.0, 1.0], stroke=[0.0, 0.0, 0.0], opacity=100,
             pos=[DEF_X, DEF_TOP + DEF_PITCH * i])
    d.update(extra)
    return d


LAYER_DEFAULTS = {
    "addr": _layer_default(0),
    "clock": _layer_default(1, format="hm", date="off"),
    "station": _layer_default(2, text="日本テレビ"),
}

# 住所の見せ方。既定は「千葉・鴨川市上空」(市区町村の接尾辞は残す)。
ADDR_DEFAULTS = dict(level="muni", droppref=True, dropmuni=False, sep="・",
                     offshore="沖", suffix="上空", suffixon=True,
                     offshoredrop=False)


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
        self.L = _layers_from_saved(saved)
        self.A = _addr_from_saved(saved)
        self.cur = "addr"                 # 配置の矢印キー操作の対象
        self.show_other_fonts = bool(saved.get("font_show_other", False))
        self.theme_mode = saved.get("theme", "light")
        self.ui_scale = float(saved.get("ui_scale", 2.0))
        self.super_text = ""              # 送出側から届いた実際のスーパー
        self._presets = list(saved.get("presets", []))
        self._dragging = False
        self._drag_off = (0, 0)
        self._bboxes: dict[str, tuple] = {}
        self.map_win = None
        self._palette = getattr(root, "_palette", None)
        self._loading = False             # ウィジェットへの反映中(送信を抑止)
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
        self._pending: dict = {}
        self._themed: list = []           # テーマ切替で塗り直す素のウィジェット
        root.title("ヘリGPS スーパー制御")
        self._maximize()
        self._build()
        self._load_all_widgets()
        self._broadcast_look()
        self._poll()
        self._tick_clock()

    def _maximize(self):
        """全画面(最大化)で開く。できない環境では大きめの窓にする."""
        for fn in (lambda: self.root.state("zoomed"),
                   lambda: self.root.attributes("-zoomed", True)):
            try:
                fn()
                return
            except Exception:
                continue
        try:
            w = self.root.winfo_screenwidth() - 40
            h = self.root.winfo_screenheight() - 80
            self.root.geometry(f"{w}x{h}+20+20")
        except Exception:
            self.root.geometry("1600x1000")

    # ---------- ウィジェット生成補助 ----------
    def _pal(self, key, dflt=""):
        return (self._palette or {}).get(key, dflt)

    def _tk_label(self, parent, **kw):
        """テーマ切替で塗り直す素の tk.Label."""
        kw.setdefault("bg", self._pal("bg", "#f5f5f7"))
        kw.setdefault("fg", self._pal("ink", "#000000"))
        w = tk.Label(parent, **kw)
        self._themed.append(w)
        return w

    def _row(self, parent, label, width=12):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=1)
        if label is not None:
            ttk.Label(fr, text=label, width=width).pack(side="left")
        return fr

    def _menu(self, parent, label, items, ctrl_name, default_idx=0, kind="str",
              on_extra=None, width=14):
        fr = self._row(parent, label)
        var = tk.StringVar(value=items[default_idx][0])
        cb = ttk.Combobox(fr, textvariable=var, values=[i[0] for i in items],
                          state="readonly", width=width)
        cb.pack(side="left", fill="x", expand=True)
        lut = {lab: val for lab, val in items}

        def emit(_e=None):
            if self._loading:
                return
            v = lut[var.get()]
            self.osc.send(f"/heli/ctrl/{ctrl_name}", int(v) if kind == "int" else v)
            if on_extra:
                on_extra(v)
        cb.bind("<<ComboboxSelected>>", emit)
        return var

    def _spinbox(self, parent, var, lo, hi, cb, width=5, inc=1):
        sb = ttk.Spinbox(parent, from_=lo, to=hi, increment=inc, width=width,
                         textvariable=var, command=cb)
        sb.pack(side="left")
        sb.bind("<Return>", lambda _e: cb())
        sb.bind("<FocusOut>", lambda _e: cb())
        return sb

    # ---------- 画面構築 ----------
    def _build(self):
        self._build_header()
        self._build_applybar()        # 最下部(固定)
        self._build_status(self.root)  # その上に横一列で(固定)
        body = self._scrollable_body()
        # 上段: 住所(左) / 配置プレビュー+受信状態(右)
        top = ttk.Frame(body); top.pack(fill="x", padx=10, pady=(4, 0))
        # grid で「住所」「住所の見せ方」を等幅、「配置」は固定幅にする。
        # pack だと自然幅の大きい列が広がってしまい、隣が潰れる。
        c1 = ttk.Frame(top); c1.grid(row=0, column=0, sticky="nsew")
        c2 = ttk.Frame(top); c2.grid(row=0, column=1, sticky="nsew", padx=(14, 14))
        c3 = ttk.Frame(top); c3.grid(row=0, column=2, sticky="n")
        top.columnconfigure(0, weight=1, uniform="topcol")
        top.columnconfigure(1, weight=1, uniform="topcol")
        top.columnconfigure(2, weight=0, minsize=CANVAS_W + 30)
        self._build_addr(c1, c2)
        self._build_place(c3)
        # 下段: 見た目(3項目を横並び)
        self._build_look(body)
        self._reload_fonts(keep=False)   # フォント一覧(_font_lut)を用意
        self._redraw_canvas()

    def _build_header(self):
        bar = ttk.Frame(self.root)
        bar.pack(side="top", fill="x", padx=10, pady=(8, 2))
        ttk.Label(bar, text="ヘリGPS スーパー制御", style="H1.TLabel").pack(side="left")
        self.save_btn = ttk.Button(bar, text="既定として保存",
                                   command=self._save_settings)
        self.save_btn.pack(side="right", padx=(8, 0))
        if MapWindow is not None:
            ttk.Button(bar, text="地図",
                       command=self._open_map).pack(side="right", padx=(8, 0))
        self._scale_lut = {lab: v for lab, v in UI_SCALES}
        rev = {v: k for k, v in self._scale_lut.items()}
        self.scale_var = tk.StringVar(value=rev.get(self.ui_scale, "大"))
        cb = ttk.Combobox(bar, textvariable=self.scale_var, state="readonly",
                          values=[lab for lab, _v in UI_SCALES], width=4)
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._on_ui_scale())
        ttk.Label(bar, text="文字").pack(side="right", padx=(14, 4))
        self.dark_var = tk.BooleanVar(value=(self.theme_mode == "dark"))
        ttk.Checkbutton(bar, text="ダークモード", variable=self.dark_var,
                        command=self._on_theme).pack(side="right", padx=(14, 0))

    def _on_theme(self):
        self.theme_mode = "dark" if self.dark_var.get() else "light"
        self._retheme()

    def _on_ui_scale(self):
        self.ui_scale = self._scale_lut.get(self.scale_var.get(), 2.0)
        self._retheme()

    def _retheme(self):
        """テーマ/文字サイズを今の設定で貼り直す."""
        if ui_theme is None:
            return
        try:
            pal = ui_theme.apply_theme(self.root, self.theme_mode, self.ui_scale)
        except Exception:
            return
        self._palette = pal
        self.root._palette = pal
        bg, ink = pal["bg"], pal["ink"]
        for w in self._themed:
            try:
                w.config(bg=bg, fg=ink)
            except Exception:
                pass
        try:
            self.canvas.config(bg=pal["canvas"])
            self._sc.config(bg=bg)
        except Exception:
            pass
        self._refresh_status_style()
        if self._pv_renderer:
            try:
                self._backdrop = self._make_backdrop()
            except Exception:
                pass
        self._redraw_canvas()

    def _scrollable_body(self):
        """縦スクロール可能な内側フレーム(全画面ならほぼ不要だが保険)."""
        outer = ttk.Frame(self.root)
        outer.pack(side="top", fill="both", expand=True)
        sc = tk.Canvas(outer, highlightthickness=0, bg=self._pal("bg", "#f5f5f7"))
        self._sc = sc
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

    def _section(self, parent, title, **pack):
        lf = ttk.LabelFrame(parent, text=title)
        pack.setdefault("fill", "x")
        pack.setdefault("pady", (4, 0))
        lf.pack(**pack)
        return lf

    # ---------- 住所 ----------
    def _build_addr(self, parent, style_parent=None):
        s = self._section(parent, "住所")
        self._menu(s, "住所変換モード", GEOMODE, "Geomode", 0)
        idx = next((i for i, (_l, v) in enumerate(ADDRLEVEL)
                    if v == self.A["level"]), 1)
        self.level_var = self._menu(s, "住所の粒度", ADDRLEVEL, "Addrlevel", idx,
                                    on_extra=self._on_addr_level)
        fr = self._row(s, "ビットレート")
        self.baud_var = tk.StringVar(value=BAUD[0][0])
        cbb = ttk.Combobox(fr, textvariable=self.baud_var, state="readonly",
                           values=[b[0] for b in BAUD], width=10)
        cbb.pack(side="left")
        cbb.bind("<<ComboboxSelected>>",
                 lambda _e: self.osc.send("/heli/ctrl/Baud",
                                          {b: v for b, v in BAUD}[self.baud_var.get()]))
        ttk.Label(fr, text="音声ch").pack(side="left", padx=(12, 4))
        # 表示は1始まり(CH1..CH8)。内部/OSCは0始まりに変換して送る。
        self.audiochan = tk.IntVar(value=3)
        ttk.Spinbox(fr, from_=1, to=16, textvariable=self.audiochan, width=4,
                    command=lambda: self.osc.send("/heli/ctrl/Audiochan",
                                                  int(self.audiochan.get()) - 1)
                    ).pack(side="left")
        for label, ctrl, dflt in (("表示書式", "Textformat", "{address}{suffix}"),
                                  ("受信途絶時の表示", "Staletext", "")):
            fr = self._row(s, label)
            var = tk.StringVar(value=dflt)
            e = ttk.Entry(fr, textvariable=var, width=14)
            e.pack(side="left", fill="x", expand=True, padx=(4, 0))
            act = lambda _e=None, v=var, cn=ctrl: self.osc.send(f"/heli/ctrl/{cn}", v.get())
            e.bind("<Return>", act)
            ttk.Button(fr, text="適用", width=3, style="Compact.TButton",
                       command=act).pack(side="left", padx=(4, 0))
        self._build_addr_style(style_parent if style_parent is not None
                               else parent)

    def _build_addr_style(self, parent):
        s = self._section(parent, "住所の見せ方")
        fr = ttk.Frame(s); fr.pack(fill="x", pady=1)
        self.droppref_var = tk.BooleanVar(value=bool(self.A["droppref"]))
        ttk.Checkbutton(fr, text="「県・都・府」を省く", variable=self.droppref_var,
                        command=self._on_addr_style).pack(side="left")
        fr = ttk.Frame(s); fr.pack(fill="x", pady=1)
        self.dropmuni_var = tk.BooleanVar(value=bool(self.A["dropmuni"]))
        ttk.Checkbutton(fr, text="「市・区・町・村」を省く", variable=self.dropmuni_var,
                        command=self._on_addr_style).pack(side="left")

        fr2 = self._row(s, "区切り")
        self._sep_lut = {lab: v for lab, v in ADDR_SEP}
        rev = {v: k for k, v in self._sep_lut.items()}
        self.sep_var = tk.StringVar(value=rev.get(self.A["sep"], ADDR_SEP[0][0]))
        cb = ttk.Combobox(fr2, textvariable=self.sep_var, state="readonly",
                          values=[lab for lab, _v in ADDR_SEP], width=12)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._on_addr_style())

        fr2b = self._row(s, "海上の表記")
        self._off_lut = {lab: v for lab, v in ADDR_OFFSHORE}
        rev2 = {v: k for k, v in self._off_lut.items()}
        self.offshore_var = tk.StringVar(
            value=rev2.get(self.A["offshore"], ADDR_OFFSHORE[0][0]))
        cb2 = ttk.Combobox(fr2b, textvariable=self.offshore_var, state="readonly",
                           values=[lab for lab, _v in ADDR_OFFSHORE], width=8)
        cb2.pack(side="left")
        cb2.bind("<<ComboboxSelected>>", lambda _e: self._on_addr_style())

        fr3 = ttk.Frame(s); fr3.pack(fill="x", pady=1)
        self.suffixon_var = tk.BooleanVar(value=bool(self.A["suffixon"]))
        ttk.Checkbutton(fr3, text="末尾に付ける", variable=self.suffixon_var,
                        command=self._on_addr_style).pack(side="left")
        self.suffix_var = tk.StringVar(value=self.A["suffix"])
        e = ttk.Entry(fr3, textvariable=self.suffix_var, width=8)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda _e: self._on_addr_style())
        e.bind("<FocusOut>", lambda _e: self._on_addr_style())

        fr4 = ttk.Frame(s); fr4.pack(fill="x", pady=1)
        self.offshoredrop_var = tk.BooleanVar(value=bool(self.A["offshoredrop"]))
        ttk.Checkbutton(fr4, text="海上のときは末尾を付けない",
                        variable=self.offshoredrop_var,
                        command=self._on_addr_style).pack(side="left")

        # 見本は2行に分けて、列幅を押し広げないようにする
        self.addr_sample_lbl = ttk.Label(s, text="", style="Muted.TLabel",
                                         justify="left")
        self.addr_sample_lbl.pack(anchor="w", padx=2, pady=(4, 2))
        self._update_addr_sample()

    def _on_addr_level(self, _v=None):
        self.A["level"] = self._level_value()
        self._update_addr_sample()
        self._redraw_canvas()

    def _level_value(self) -> str:
        lut = {lab: v for lab, v in ADDRLEVEL}
        return lut.get(self.level_var.get(), "muni")

    def _on_addr_style(self):
        if self._loading:
            return
        a = self.A
        a["droppref"] = bool(self.droppref_var.get())
        a["dropmuni"] = bool(self.dropmuni_var.get())
        a["sep"] = self._sep_lut.get(self.sep_var.get(), "")
        a["offshore"] = self._off_lut.get(self.offshore_var.get(), "沖")
        a["suffix"] = self.suffix_var.get()
        a["suffixon"] = bool(self.suffixon_var.get())
        a["offshoredrop"] = bool(self.offshoredrop_var.get())
        self._stage("/heli/ctrl/Addrdroppref", 1 if a["droppref"] else 0)
        self._stage("/heli/ctrl/Addrdropmuni", 1 if a["dropmuni"] else 0)
        self._stage("/heli/ctrl/Addrsep", a["sep"])
        self._stage("/heli/ctrl/Addroffshore", a["offshore"])
        self._stage("/heli/ctrl/Addrsuffix", a["suffix"])
        self._stage("/heli/ctrl/Addrsuffixon", 1 if a["suffixon"] else 0)
        self._stage("/heli/ctrl/Addroffshoredrop", 1 if a["offshoredrop"] else 0)
        self._update_addr_sample()
        self._redraw_canvas()

    def _sample_text(self, pref="千葉県", city="鴨川市", offshore=False,
                     gun="", town="") -> str:
        """現在の設定で住所がどう出るかの見本(送出側と同じロジック)."""
        a = self.A
        suffix = a["suffix"] if a["suffixon"] else ""
        if suffix and a["offshoredrop"] and offshore:
            suffix = ""
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
        self.addr_sample_lbl.config(text=f"例）陸上: {land}\n　　 海上: {sea}")

    # ---------- 見た目(3項目を横並び) ----------
    def _build_look(self, parent):
        s = self._section(parent, "見た目（項目ごとに設定）", padx=10)
        cols = ttk.Frame(s); cols.pack(fill="x", pady=0)
        self.on_vars, self.col_frames = {}, {}
        self.w = {k: {} for k, _l, _p in LAYERS}
        for i, (key, label, _p) in enumerate(LAYERS):
            col = ttk.Frame(cols)
            col.grid(row=0, column=i, sticky="nsew",
                     padx=(0 if i == 0 else 14, 0))
            cols.columnconfigure(i, weight=1, uniform="look")
            self.col_frames[key] = col
            self._build_look_col(col, key, label)

    def _build_look_col(self, col, key, label):
        d = self.L[key]
        W = self.w[key]
        head = ttk.Frame(col); head.pack(fill="x", pady=(0, 4))
        v = tk.BooleanVar(value=bool(d["on"]))
        self.on_vars[key] = v
        ttk.Checkbutton(head, text=f"{label}を表示", variable=v,
                        command=lambda k=key: self._on_layer_toggle(k)).pack(side="left")

        # 項目固有(時刻の書式 / 局名の文字 / 住所の案内)
        if key == "clock":
            fr = self._row(col, "書式", width=8)
            self._fmt_lut = {lab: val for lab, val in CLOCK_FMT}
            rev = {v2: k2 for k2, v2 in self._fmt_lut.items()}
            self.fmt_var = tk.StringVar(
                value=rev.get(d.get("format", "hm"), CLOCK_FMT[0][0]))
            cb = ttk.Combobox(fr, textvariable=self.fmt_var, state="readonly",
                              values=[lab for lab, _v in CLOCK_FMT], width=13)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda _e: self._on_clock_format())
            ttk.Label(fr, text="日付").pack(side="left", padx=(8, 4))
            self._date_lut = {lab: val for lab, val in CLOCK_DATE}
            rev2 = {v2: k2 for k2, v2 in self._date_lut.items()}
            self.date_var = tk.StringVar(
                value=rev2.get(d.get("date", "off"), CLOCK_DATE[0][0]))
            cb2 = ttk.Combobox(fr, textvariable=self.date_var, state="readonly",
                               values=[lab for lab, _v in CLOCK_DATE], width=8)
            cb2.pack(side="left", fill="x", expand=True)
            cb2.bind("<<ComboboxSelected>>", lambda _e: self._on_clock_format())
        elif key == "station":
            fr = self._row(col, "文字", width=8)
            self.station_var = tk.StringVar(value=d.get("text", ""))
            e = ttk.Entry(fr, textvariable=self.station_var)
            e.pack(side="left", fill="x", expand=True)
            e.bind("<Return>", lambda _e: self._on_station_text())
            e.bind("<FocusOut>", lambda _e: self._on_station_text())
        else:
            ttk.Label(col, text="文字の内容は左の「住所の見せ方」で決めます",
                      style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        # フォント
        fr = self._row(col, "フォント", width=8)
        W["font"] = tk.StringVar()
        cb = ttk.Combobox(fr, textvariable=W["font"], state="readonly", width=14)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", lambda _e, k=key: self._on_font(k))
        W["font_cb"] = cb

        # サイズ・太さ
        fr = ttk.Frame(col); fr.pack(fill="x", pady=1)
        ttk.Label(fr, text="サイズ", width=8).pack(side="left")
        W["size"] = tk.IntVar(value=int(d["size"]))
        self._spinbox(fr, W["size"], 20, 400, lambda k=key: self._on_size(k), inc=2)
        ttk.Label(fr, text="太さ").pack(side="left", padx=(10, 4))
        self._weight_values = ["Light", "Regular", "Medium", "SemiBold", "Bold",
                               "ExtraBold", "Black"]
        W["weight"] = tk.StringVar(value=d.get("weight", "Bold"))
        cbw = ttk.Combobox(fr, textvariable=W["weight"], state="readonly",
                           values=self._weight_values, width=9)
        cbw.pack(side="left", fill="x", expand=True)
        cbw.bind("<<ComboboxSelected>>", lambda _e, k=key: self._on_weight(k))

        # 揃え・透過率
        fr = ttk.Frame(col); fr.pack(fill="x", pady=1)
        ttk.Label(fr, text="揃え", width=8).pack(side="left")
        self._align_lut = {"左寄せ": "left", "中央": "center", "右寄せ": "right"}
        rev3 = {v2: k2 for k2, v2 in self._align_lut.items()}
        W["align"] = tk.StringVar(value=rev3.get(d.get("align", "left"), "左寄せ"))
        cba = ttk.Combobox(fr, textvariable=W["align"], state="readonly",
                           values=list(self._align_lut), width=7)
        cba.pack(side="left")
        cba.bind("<<ComboboxSelected>>", lambda _e, k=key: self._on_align(k))
        ttk.Label(fr, text="透過%").pack(side="left", padx=(10, 4))
        W["opacity"] = tk.IntVar(value=int(d["opacity"]))
        self._spinbox(fr, W["opacity"], 0, 100,
                      lambda k=key: self._on_opacity(k), inc=5)

        # 色
        fr = ttk.Frame(col); fr.pack(fill="x", pady=1)
        ttk.Label(fr, text="文字色", width=8).pack(side="left")
        W["fill_sw"] = tk.Label(fr, text="   ", bg=_hex(d["fill"]),
                                relief="solid", width=3)
        W["fill_sw"].pack(side="left", padx=(0, 4))
        ttk.Button(fr, text="選ぶ",
                   command=lambda k=key: self._pick_fill(k)).pack(side="left")
        ttk.Label(fr, text="フチ").pack(side="left", padx=(10, 4))
        W["stroke_sw"] = tk.Label(fr, text="   ", bg=_hex(d["stroke"]),
                                  relief="solid", width=3)
        W["stroke_sw"].pack(side="left", padx=(0, 4))
        ttk.Button(fr, text="選ぶ",
                   command=lambda k=key: self._pick_stroke(k)).pack(side="left")

        # フチ太さ・位置(1行にまとめて縦を詰める)
        fr = ttk.Frame(col); fr.pack(fill="x", pady=(1, 4))
        ttk.Label(fr, text="フチ太さ", width=8).pack(side="left")
        W["sw"] = tk.IntVar(value=int(d["sw"]))
        self._spinbox(fr, W["sw"], 0, 30, lambda k=key: self._on_strokewidth(k),
                      width=4)
        ttk.Label(fr, text="X").pack(side="left", padx=(10, 4))
        W["x"] = tk.IntVar(value=int(d["pos"][0]))
        self._spinbox(fr, W["x"], -500, FRAME_W,
                      lambda k=key: self._on_pos_spin(k), width=5, inc=10)
        ttk.Label(fr, text="Y").pack(side="left", padx=(8, 4))
        W["y"] = tk.IntVar(value=int(d["pos"][1]))
        self._spinbox(fr, W["y"], -500, FRAME_H,
                      lambda k=key: self._on_pos_spin(k), width=5, inc=10)

    # ---------- 見た目のコールバック ----------
    def _on_layer_toggle(self, key):
        self.L[key]["on"] = bool(self.on_vars[key].get())
        self._stage(f"/heli/ctrl/{LAYER_PREFIX[key] or 'Super'}on",
                    1 if self.L[key]["on"] else 0)
        if self.L[key]["on"]:
            self.cur = key
        self._redraw_canvas()

    def _on_clock_format(self):
        if self._loading:
            return
        fmt = self._fmt_lut.get(self.fmt_var.get(), "hm")
        date = self._date_lut.get(self.date_var.get(), "off")
        self.L["clock"]["format"] = fmt
        self.L["clock"]["date"] = date
        self._stage("/heli/ctrl/Clockformat", fmt)
        self._stage("/heli/ctrl/Clockdate", date)
        self._redraw_canvas()

    def _on_station_text(self):
        if self._loading:
            return
        txt = self.station_var.get()
        if txt == self.L["station"].get("text"):
            return
        self.L["station"]["text"] = txt
        self._stage("/heli/ctrl/Stationtext", txt)
        self._redraw_canvas()

    def _on_font(self, key):
        if self._loading:
            return
        name = self.w[key]["font"].get()
        path, kind = self._font_lut.get(name, ("", ""))
        d = self.L[key]
        d["font"], d["font_path"] = name, path
        if path:
            self._stage(self._addr_of("Fontpath", key), path)
        self._stage(self._addr_of("Font", key), name)
        if kind == "other":
            self._flash("※ このフォントはライセンス(EULA)の確認が必要です")
        self._redraw_canvas()

    def _on_size(self, key):
        if self._loading:
            return
        v = max(10, min(400, int(self.w[key]["size"].get())))
        self.L[key]["size"] = v
        self._stage(self._addr_of("Fontsize", key), v)
        self._redraw_canvas()

    def _on_weight(self, key):
        if self._loading:
            return
        v = self.w[key]["weight"].get()
        self.L[key]["weight"] = v
        self._stage(self._addr_of("Fontweight", key), v)
        self._redraw_canvas()

    def _on_align(self, key):
        if self._loading:
            return
        v = self._align_lut.get(self.w[key]["align"].get(), "left")
        self.L[key]["align"] = v
        self._stage(self._addr_of("Alignx", key), v)
        self._redraw_canvas()

    def _on_opacity(self, key):
        if self._loading:
            return
        v = max(0, min(100, int(self.w[key]["opacity"].get())))
        self.L[key]["opacity"] = v
        self._stage(self._addr_of("Opacity", key), float(v) / 100.0)
        self._redraw_canvas()

    def _on_strokewidth(self, key):
        if self._loading:
            return
        v = max(0, min(30, int(self.w[key]["sw"].get())))
        self.L[key]["sw"] = v
        self._stage(self._addr_of("Strokewidth", key), v)
        self._redraw_canvas()

    def _on_pos_spin(self, key):
        if self._loading:
            return
        try:
            x = int(self.w[key]["x"].get()); y = int(self.w[key]["y"].get())
        except Exception:
            return
        self.L[key]["pos"] = [x, y]
        self.cur = key
        self._send_pos(key)
        self._redraw_canvas()

    def _pick_fill(self, key):
        d = self.L[key]
        rgb, hx = colorchooser.askcolor(color=_hex(d["fill"]),
                                        title=f"{LAYER_LABEL[key]}の文字色")
        if rgb is None:
            return
        d["fill"] = [c / 255 for c in rgb]
        self.w[key]["fill_sw"].config(bg=hx)
        for comp, ch in (("r", 0), ("g", 1), ("b", 2)):
            self._stage(self._addr_of(f"Fontcolor{comp}", key), float(d["fill"][ch]))
        self._redraw_canvas()

    def _pick_stroke(self, key):
        d = self.L[key]
        rgb, hx = colorchooser.askcolor(color=_hex(d["stroke"]),
                                        title=f"{LAYER_LABEL[key]}のフチ色")
        if rgb is None:
            return
        d["stroke"] = [c / 255 for c in rgb]
        self.w[key]["stroke_sw"].config(bg=hx)
        for comp, ch in (("r", 0), ("g", 1), ("b", 2)):
            self._stage(self._addr_of(f"Strokecolor{comp}", key), float(d["stroke"][ch]))
        self._redraw_canvas()

    # ---------- フォント一覧 ----------
    def _reload_fonts(self, keep=True):
        self.show_other_fonts = bool(self.show_other_var.get())
        fonts = []
        if list_system_fonts:
            try:
                fonts = list_system_fonts(include_other=self.show_other_fonts)
            except Exception:
                fonts = []
        if not fonts:
            fonts = FALLBACK_FONTS
        self._font_lut = {}
        for name, path, kind in fonts:
            label = f"{name}　［要確認］" if kind == "other" else name
            self._font_lut[label] = (path, kind)
        self._font_names = list(self._font_lut)
        for key, _l, _p in LAYERS:
            cb = self.w[key].get("font_cb")
            if cb is not None:
                cb.config(values=self._font_names)
        if keep:
            self._load_all_widgets()
            self._redraw_canvas()

    def _font_for(self, key) -> str:
        """保存値 → 同梱フォント → 一覧の先頭 の順で表示名を決める."""
        d = self.L[key]
        want = d.get("font", "")
        if want in self._font_lut:
            return want
        path = d.get("font_path", "")
        hit = next((n for n, (p, _k) in self._font_lut.items() if p == path), None)
        if hit:
            return hit
        bundled = next((n for n, (_p, k) in self._font_lut.items()
                        if k == "bundled"), None)
        return bundled or (self._font_names[0] if self._font_names else "")

    # ---------- OSC アドレス ----------
    def _addr_of(self, name: str, key: str) -> str:
        """レイヤ接頭辞を付けた /heli/ctrl/... を返す(住所は接頭辞なし)."""
        pfx = LAYER_PREFIX[key]
        return f"/heli/ctrl/{pfx}{name.lower() if pfx else name}"

    # ---------- 保留と反映 ----------
    def _stage(self, address, *args):
        self._pending[address] = args
        self._mark_dirty()

    def _mark_dirty(self):
        n = len(self._pending)
        if hasattr(self, "apply_btn"):
            if n:
                self.apply_btn.config(text=f"決定（反映）  未反映 {n} 件",
                                      state="normal")
            else:
                self.apply_btn.config(text="決定（反映）", state="disabled")

    def _apply_pending(self):
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
        a = self.A
        self.osc.send("/heli/ctrl/Addrlevel", a["level"])
        self.osc.send("/heli/ctrl/Addrdroppref", 1 if a["droppref"] else 0)
        self.osc.send("/heli/ctrl/Addrdropmuni", 1 if a["dropmuni"] else 0)
        self.osc.send("/heli/ctrl/Addrsep", a["sep"])
        self.osc.send("/heli/ctrl/Addroffshore", a["offshore"])
        self.osc.send("/heli/ctrl/Addrsuffix", a["suffix"])
        self.osc.send("/heli/ctrl/Addrsuffixon", 1 if a["suffixon"] else 0)
        self.osc.send("/heli/ctrl/Addroffshoredrop", 1 if a["offshoredrop"] else 0)

    # ---------- 設定の保存・呼出 ----------
    def _collect_settings(self) -> dict:
        return {
            "layers": {k: dict(v) for k, v in self.L.items()},
            "addr": dict(self.A),
            "font_show_other": bool(self.show_other_fonts),
            "theme": self.theme_mode,
            "ui_scale": float(self.ui_scale),
        }

    def _save_settings(self):
        full = _load_settings()
        full.update(self._collect_settings())
        ok = _write_settings(full)
        self.save_btn.config(text="保存しました" if ok else "保存失敗")
        self.root.after(1500, lambda: self.save_btn.config(text="既定として保存"))

    def _load_all_widgets(self):
        """self.L / self.A の値をウィジェットへ反映(OSCは送らない)."""
        self._loading = True
        try:
            for key, _l, _p in LAYERS:
                d, W = self.L[key], self.w[key]
                self.on_vars[key].set(bool(d["on"]))
                W["size"].set(int(d["size"]))
                W["sw"].set(int(d["sw"]))
                W["opacity"].set(int(d["opacity"]))
                W["x"].set(int(d["pos"][0]))
                W["y"].set(int(d["pos"][1]))
                wt = d.get("weight", "Bold")
                W["weight"].set(wt if wt in self._weight_values else "Bold")
                rev = {v: k for k, v in self._align_lut.items()}
                W["align"].set(rev.get(d.get("align", "left"), "左寄せ"))
                W["font"].set(self._font_for(key))
                W["fill_sw"].config(bg=_hex(d["fill"]))
                W["stroke_sw"].config(bg=_hex(d["stroke"]))
            rev = {v: k for k, v in self._fmt_lut.items()}
            self.fmt_var.set(rev.get(self.L["clock"].get("format", "hm"),
                                     CLOCK_FMT[0][0]))
            rev2 = {v: k for k, v in self._date_lut.items()}
            self.date_var.set(rev2.get(self.L["clock"].get("date", "off"),
                                       CLOCK_DATE[0][0]))
            self.station_var.set(self.L["station"].get("text", ""))
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
            self.offshoredrop_var.set(bool(a["offshoredrop"]))
        finally:
            self._loading = False
        self._update_addr_sample()
        self._update_pos_label()

    def _apply_settings(self, d: dict):
        """設定dictをUIに反映し、送出側へも即時送信(プリセット呼出用)."""
        self.L = _layers_from_saved(d)
        self.A = _addr_from_saved(d)
        self.show_other_fonts = bool(d.get("font_show_other", self.show_other_fonts))
        self.show_other_var.set(self.show_other_fonts)
        self._reload_fonts(keep=False)
        self._load_all_widgets()
        self._redraw_canvas()
        self._broadcast_look()
        self._pending.clear(); self._mark_dirty()

    def _flash(self, msg: str):
        if hasattr(self, "msg_lbl"):
            self.msg_lbl.config(text=msg)
            self.root.after(2500, lambda: self.msg_lbl.config(text=""))

    def _save_preset(self, i: int):
        full = _load_settings()
        presets = list(full.get("presets", []))
        while len(presets) <= i:
            presets.append({})
        name = self._preset_name_vars[i].get().strip() or f"番組{i + 1}"
        presets[i] = {"name": name, "settings": self._collect_settings()}
        full["presets"] = presets
        self._presets = presets
        ok = _write_settings(full)
        self._flash(f"「{name}」に保存しました" if ok else "保存失敗")

    def _recall_preset(self, i: int):
        full = _load_settings()
        presets = full.get("presets", [])
        if i < len(presets) and presets[i].get("settings"):
            self._apply_settings(presets[i]["settings"])
            nm = presets[i].get("name") or f"番組{i + 1}"
            self._flash(f"「{nm}」を呼び出しました")
        else:
            self._flash("このプリセットは未保存です")

    # ---------- 配置 ----------
    def _make_backdrop(self):
        """WYSIWYGプレビューの背景(暗色+セーフエリア目安)を作る."""
        base = self._pal("canvas", "#22262f").lstrip("#")
        r0, g0, b0 = (int(base[i:i + 2], 16) for i in (0, 2, 4))
        bg = Image.new("RGB", (CANVAS_W, CANVAS_H), (r0, g0, b0))
        d = ImageDraw.Draw(bg)
        for i in range(CANVAS_H):
            t = i / CANVAS_H
            d.line([(0, i), (CANVAS_W, i)],
                   fill=(min(255, int(r0 + 8 * t)), min(255, int(g0 + 8 * t)),
                         min(255, int(b0 + 10 * t))))
        gl = (min(255, r0 + 62), min(255, g0 + 66), min(255, b0 + 76))
        d.rectangle([CANVAS_W * 0.05, CANVAS_H * 0.05,
                     CANVAS_W * 0.95, CANVAS_H * 0.95], outline=gl)
        d.line([(0, CANVAS_H * 2 / 3), (CANVAS_W, CANVAS_H * 2 / 3)],
               fill=(min(255, r0 + 36), min(255, g0 + 40), min(255, b0 + 48)))
        return np.asarray(bg, dtype=np.uint8)

    def _build_place(self, parent):
        s = self._section(parent, "配置", pady=(4, 0))
        mode = "実フォントでプレビュー" if self._pv_renderer else "簡易表示"
        ttk.Label(s, text=f"ドラッグで移動／矢印キーで1px　［{mode}］",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        self.canvas = tk.Canvas(s, width=CANVAS_W, height=CANVAS_H,
                                bg=self._pal("canvas", "#22262f"),
                                highlightthickness=0, takefocus=1)
        self.canvas.pack()
        fr = ttk.Frame(s); fr.pack(fill="x", pady=(4, 4))
        self.pos_lbl = ttk.Label(fr, text="", style="Muted.TLabel")
        self.pos_lbl.pack(side="left")
        ttk.Button(fr, text="縦に並べ直す",
                   command=self._restack).pack(side="right")
        self.msg_lbl = ttk.Label(s, text="", style="Muted.TLabel")
        self.msg_lbl.pack(anchor="w", padx=2)

        if self._pv_renderer:
            self._img_item = self.canvas.create_image(0, 0, anchor="nw")
            self._photo = None
        else:
            self.canvas.create_rectangle(2, 2, CANVAS_W - 2, CANVAS_H - 2,
                                         outline="#aaa")
            self._txt_items = {}
            for key, _l, _p in LAYERS:
                sh = self.canvas.create_text(0, 0, anchor="nw", text="", fill="black")
                tx = self.canvas.create_text(0, 0, anchor="nw", text="", fill="white")
                self._txt_items[key] = (sh, tx)

        self._sel_box = self.canvas.create_rectangle(0, 0, 0, 0, outline="#8e8e93",
                                                     dash=(2, 3), state="hidden")
        self._ghost_box = self.canvas.create_rectangle(0, 0, 0, 0, outline="#0a84ff",
                                                       dash=(3, 2), width=2,
                                                       state="hidden")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        for key, dx, dy in (("<Up>", 0, -1), ("<Down>", 0, 1),
                            ("<Left>", -1, 0), ("<Right>", 1, 0)):
            self.root.bind(key, lambda e, dx=dx, dy=dy: self._on_arrow(e, dx, dy))

    def _on_arrow(self, e, dx, dy):
        w = self.root.focus_get()
        cls = w.winfo_class() if w is not None else ""
        if cls in ("TEntry", "Entry", "TSpinbox", "Spinbox", "TCombobox"):
            return
        step = 10 if (e.state & 0x1) else 1
        self._nudge(dx * step, dy * step)
        return "break"

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
        self._load_all_widgets()
        self._redraw_canvas()

    def _layer_text(self, key: str) -> str:
        if key == "addr":
            return self.super_text or self._sample_text()
        if key == "clock":
            return clock_text(self.L["clock"].get("format", "hm"),
                              self.L["clock"].get("date", "off"))
        return self.L["station"].get("text", "") or "(局名)"

    def _visible_layers(self) -> list[str]:
        return [k for k, _l, _p in LAYERS if self.L[k]["on"]]

    def _hit_layer(self, x, y) -> str | None:
        for key in reversed(self._visible_layers()):
            bb = self._bboxes.get(key)
            if bb and bb[0] - 4 <= x <= bb[2] + 4 and bb[1] - 4 <= y <= bb[3] + 4:
                return key
        return None

    def _press(self, e):
        self.canvas.focus_set()
        key = self._hit_layer(e.x, e.y)
        if key:
            self.cur = key
            ax, ay = (self.L[key]["pos"][0] / SCALE, self.L[key]["pos"][1] / SCALE)
            self._drag_off = (e.x - ax, e.y - ay)
            self._dragging = key
            self._redraw_canvas()
        else:
            self._place_center(e.x, e.y)

    def _drag_move(self, e):
        if not self._dragging:
            return
        ox, oy = self._drag_off
        cx = max(0, min(CANVAS_W, e.x - ox))
        cy = max(0, min(CANVAS_H, e.y - oy))
        self.L[self._dragging]["pos"] = [int(cx * SCALE), int(cy * SCALE)]
        self._sync_pos_widgets(self._dragging)
        self._redraw_canvas()
        self._send_pos(self._dragging)

    def _drag_end(self, _e=None):
        if self._dragging:
            self._dragging = False
            self._redraw_canvas()

    def _place_center(self, cxp, cyp):
        d = self.L[self.cur]
        bb = self._bboxes.get(self.cur)
        w = (bb[2] - bb[0]) if bb else 0
        h = (bb[3] - bb[1]) if bb else 0
        dx = {"left": w / 2, "center": 0, "right": -w / 2}.get(d["align"], w / 2)
        ax = max(0, min(CANVAS_W, cxp - dx))
        ay = max(0, min(CANVAS_H, cyp - h / 2))
        d["pos"] = [int(ax * SCALE), int(ay * SCALE)]
        self._sync_pos_widgets(self.cur)
        self._redraw_canvas(); self._send_pos(self.cur)

    def _nudge(self, dx, dy):
        d = self.L[self.cur]
        d["pos"] = [d["pos"][0] + dx, d["pos"][1] + dy]
        self._sync_pos_widgets(self.cur)
        self._redraw_canvas(); self._send_pos(self.cur)

    def _sync_pos_widgets(self, key):
        self._loading = True
        try:
            self.w[key]["x"].set(int(self.L[key]["pos"][0]))
            self.w[key]["y"].set(int(self.L[key]["pos"][1]))
        finally:
            self._loading = False

    def _send_pos(self, key):
        d = self.L[key]
        self._stage(self._addr_of("Posx", key), float(d["pos"][0]))
        self._stage(self._addr_of("Posy", key), float(d["pos"][1]))

    def _update_pos_label(self):
        if hasattr(self, "pos_lbl"):
            d = self.L[self.cur]
            self.pos_lbl.config(text=f"［{LAYER_LABEL[self.cur]}］"
                                     f"X: {d['pos'][0]}　Y: {d['pos'][1]} px")

    # ---------- プレビュー描画 ----------
    def _redraw_canvas(self):
        if getattr(self, "_pv_renderer", None):
            self._render_wysiwyg()
        elif hasattr(self, "_txt_items"):
            self._render_text()
        self._update_boxes()
        self._update_pos_label()

    def _pv_layer(self, key: str):
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
        try:
            lays = [self._pv_layer(k) for k in self._visible_layers()]
            telop = self._pv_renderer.render_layers(lays)
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
        sel = self._bboxes.get(self.cur) if self.L[self.cur]["on"] else None
        if self._sel_box is not None:
            if sel and self._dragging != self.cur:
                self.canvas.coords(self._sel_box, sel[0] - 3, sel[1] - 3,
                                   sel[2] + 3, sel[3] + 3)
                self.canvas.itemconfig(self._sel_box, state="normal")
                self.canvas.tag_raise(self._sel_box)
            else:
                self.canvas.itemconfig(self._sel_box, state="hidden")
        if self._ghost_box is None:
            return
        bb = self._bboxes.get(self._dragging) if isinstance(self._dragging, str) else None
        if bb:
            self.canvas.coords(self._ghost_box, bb[0] - 2, bb[1] - 2,
                               bb[2] + 2, bb[3] + 2)
            self.canvas.itemconfig(self._ghost_box, state="normal")
            self.canvas.tag_raise(self._ghost_box)
        else:
            self.canvas.itemconfig(self._ghost_box, state="hidden")

    def _tick_clock(self):
        if self.L["clock"]["on"]:
            self._redraw_canvas()
        self.root.after(1000, self._tick_clock)

    # ---------- 下段バー(プリセット + 決定) ----------
    def _build_applybar(self):
        ap = ttk.Frame(self.root)
        ap.pack(side="bottom", fill="x", padx=10, pady=(4, 8))
        # 右: 決定(いちばん押す。広く取る)
        self.apply_btn = ttk.Button(ap, text="決定（反映）", state="disabled",
                                    style="Accent.TButton",
                                    command=self._apply_pending)
        self.apply_btn.pack(side="right", fill="x", expand=True, padx=(16, 0))
        # 左: 番組プリセット
        ttk.Label(ap, text="番組プリセット").pack(side="left", padx=(0, 8))
        self._preset_name_vars = []
        for i in range(N_PRESETS):
            saved = self._presets[i] if i < len(self._presets) else {}
            var = tk.StringVar(value=(saved.get("name") or f"番組{i + 1}"))
            self._preset_name_vars.append(var)
            ttk.Entry(ap, textvariable=var, width=6).pack(side="left")
            ttk.Button(ap, text="呼出", width=3, style="Compact.TButton",
                       command=lambda i=i: self._recall_preset(i)).pack(side="left")
            ttk.Button(ap, text="保存", width=3, style="Compact.TButton",
                       command=lambda i=i: self._save_preset(i)).pack(side="left",
                                                                      padx=(0, 14))
        self.show_other_var = tk.BooleanVar(value=self.show_other_fonts)
        ttk.Checkbutton(ap, text="その他のフォントも表示（EULA要確認）",
                        variable=self.show_other_var,
                        command=self._reload_fonts).pack(side="left", padx=(8, 0))

    # ---------- 受信状態 ----------
    def _build_status(self, parent):
        """受信状態は画面下部に**横一列**で置く(縦を食わないように)."""
        st = ttk.Frame(parent)
        st.pack(side="bottom", fill="x", padx=10, pady=(0, 2))
        fam = self._pal("family", "")
        sz = self._palette.get("sz") if self._palette else None
        self.recv_lbl = tk.Label(st, text="● 未受信", fg="white",
                                 bg=self._pal("neutral", "#8e8e93"),
                                 font=(fam, sz(12) if sz else 12, "bold"),
                                 width=18)
        self.recv_lbl.pack(side="left", padx=(0, 10), ipady=2)
        self.super_lbl = self._tk_label(st, text="―",
                                        font=(fam, sz(13) if sz else 13, "bold"))
        self.super_lbl.pack(side="left", padx=(0, 16))
        self.info_lbl = self._tk_label(st, text="緯度 --  経度 --  高度 --")
        self.info_lbl.pack(side="left", padx=(0, 16))
        # DMS と測位状態は同じラベルに詰める
        self.dms_lbl = self._tk_label(st, text="DMS  緯度 --  経度 --")
        self.dms_lbl.pack(side="left")
        self.fix_lbl = self.dms_lbl
        self._fix_text = "測位 --  衛星 --"
        self._dms_text = "DMS  緯度 --  経度 --"

    def _refresh_status_style(self):
        """テーマ切替時に状態表示のフォントを貼り直す."""
        fam = self._pal("family", "")
        sz = self._palette.get("sz") if self._palette else None
        try:
            self.recv_lbl.config(font=(fam, sz(12) if sz else 12, "bold"))
            self.super_lbl.config(font=(fam, sz(18) if sz else 18, "bold"))
        except Exception:
            pass

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

    # ---------- 状態受信 ----------
    def _poll(self):
        try:
            while True:
                a, args = self.osc.inbox.get_nowait()
                self._on_status(a, args)
        except queue.Empty:
            pass
        if time.monotonic() - self._last_status > STALE_SEC:
            self.recv_lbl.config(text="● アプリ未接続/停止",
                                 bg=self._pal("neutral", "gray"))
        self.root.after(200, self._poll)

    def _on_status(self, a, args):
        self._last_status = time.monotonic()
        if a == "/heli/super" and args:
            self.super_text = args[0]
            self.super_lbl.config(text=args[0] or "(表示なし)")
            self._redraw_canvas()
        elif a == "/heli/position" and len(args) >= 3:
            lat, lon, alt = args[0], args[1], args[2]
            self.info_lbl.config(text=f"緯度 {lat:.6f}  経度 {lon:.6f}  高度 {alt:.0f}m")
            self._dms_text = (f"DMS  緯度 {deg_to_dms_str(lat)}  "
                              f"経度 {deg_to_dms_str(lon)}")
            self.dms_lbl.config(text=f"{self._dms_text}　｜　{self._fix_text}")
            if self.map_win is not None and self.map_win.alive():
                try:
                    self.map_win.update_position(lat, lon, self.super_text)
                except Exception:
                    pass
        elif a == "/heli/status" and len(args) >= 3:
            receiving = bool(args[0])
            if receiving:
                self.recv_lbl.config(text="● 受信中", bg=self._pal("ok", "#1a9d47"))
            else:
                self.recv_lbl.config(text="● GPS途絶(直近を保持)",
                                     bg=self._pal("warn", "#d23b3b"))
            fix = {0: "正常", 1: "バックアップ", 2: "使用不能"}.get(args[1], "?")
            sats = "--" if args[2] < 0 else args[2]
            self._fix_text = f"測位 {fix}  衛星 {sats}"
            self.dms_lbl.config(text=f"{self._dms_text}　｜　{self._fix_text}")


def main():
    ap = argparse.ArgumentParser(description="ヘリGPS スーパー制御UI")
    ap.add_argument("--td-host", default="127.0.0.1")
    ap.add_argument("--ctrl-port", type=int, default=9001)
    ap.add_argument("--status-port", type=int, default=9002)
    args = ap.parse_args()
    osc = OscClient(args.td_host, args.ctrl_port, args.status_port)
    root = tk.Tk()
    saved = _load_settings()
    if ui_theme is not None:
        try:
            root._palette = ui_theme.apply_theme(
                root, saved.get("theme", "light"),
                float(saved.get("ui_scale", 2.0)))
        except Exception:
            root._palette = None
    ControlUI(root, osc)
    root.protocol("WM_DELETE_WINDOW", lambda: (osc.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
