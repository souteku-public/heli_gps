"""ヘリGPSスーパー 外部制御UI (tkinter).

TouchDesigner版・GStreamer版どちらも、同じOSCプロトコルで操作できる制御パネル。

    UI → OSC 127.0.0.1:9001 → TD(osc_ctrl) / gst_heli.app(--osc-control)
    TD/gst → OSC 127.0.0.1:9002 → このUI(状態表示)

主な機能:
    - フォントは実在ファイルから選択(消える事故を防ぐ)
    - 文字色(中)とフチ色を別々に指定、フチの太さも可変
    - 配置タブでドラッグ&ドロップ位置指定(矢印キー微調整も可)
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
    from gst_heli.renderer import SuperRenderer, SuperStyle
    HAVE_WYSIWYG = True
except Exception:
    HAVE_WYSIWYG = False

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
             ("市区町村(区あり)", "city"), ("町丁目(要ネット)", "town")]
BAUD = [("1200 bps", "1200"), ("2400 bps", "2400")]
FALLBACK_FONTS = [("Yu Gothic", r"C:\Windows\Fonts\YuGothM.ttc"),
                  ("Meiryo", r"C:\Windows\Fonts\meiryo.ttc"),
                  ("MS Gothic", r"C:\Windows\Fonts\msgothic.ttc")]

STALE_SEC = 3.0
FRAME_W, FRAME_H = 1920, 1080
CANVAS_W, CANVAS_H = 512, 288
SCALE = FRAME_W / CANVAS_W          # 3.75


def _hex(rgb01):
    return "#%02x%02x%02x" % tuple(int(c * 255) for c in rgb01)


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
        # 保存済みの既定(見た目・位置)を読み込む
        saved = _load_settings()
        self.fill = tuple(saved.get("fill", (1.0, 1.0, 1.0)))
        self.stroke = tuple(saved.get("stroke", (0.0, 0.0, 0.0)))
        self.font_size = int(saved.get("font_size", 90))
        self._init_stroke_width = int(saved.get("stroke_width", 5))
        self._init_font_name = saved.get("font_name", "")
        self.align_x = saved.get("align_x", "left")     # left/center/right
        self.super_text = "(プレビュー)"
        self.pos = list(saved.get("pos", [480, 900]))   # フレーム座標(基準点, px)
        # 番組プリセット(名前付き)。[{name, settings}, ...]
        self._presets = list(saved.get("presets", []))
        # ドラッグ中の状態(ゴースト表示・つかんだ位置のオフセット)
        self._dragging = False
        self._drag_off = (0, 0)
        self._ghost_box = None
        self._telop_bbox = None          # 配置プレビュー上のテロップ矩形(当たり判定)
        self.map_win = None              # 地図ウィンドウ(開いていれば)
        self._palette = getattr(root, "_palette", None)
        # WYSIWYGプレビュー用のレンダラと背景
        self._pv_scale = CANVAS_W / FRAME_W
        if HAVE_WYSIWYG:
            try:
                self._pv_renderer = SuperRenderer(CANVAS_W, CANVAS_H, SuperStyle())
                self._backdrop = self._make_backdrop()
            except Exception:
                self._pv_renderer = None
        else:
            self._pv_renderer = None
        # 見た目・配置の変更は「決定」ボタンを押すまで送らずに溜めておく。
        # (address:args の辞書。同じ宛先は最新値で上書き)
        self._pending: dict = {}
        root.title("ヘリGPS スーパー制御")
        root.geometry("600x900")
        root.minsize(560, 520)
        self._build()
        # 保存済みフォントを選択に反映
        if self._init_font_name and self._init_font_name in self._font_lut:
            self.font_var.set(self._init_font_name)
        # 起動時に現在のUI状態(保存値があればそれ)を送出側へ流し込む。
        # 縦は上端・絶対座標に固定。横揃え(align_x)は見た目で選べる。
        self.osc.send("/heli/ctrl/Aligny", "top")
        self._broadcast_look()
        self._poll()

    # ---------- ウィジェット生成補助 ----------
    def _menu(self, parent, label, items, ctrl_name, default_idx=0, kind="str"):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        var = tk.StringVar(value=items[default_idx][0])
        cb = ttk.Combobox(fr, textvariable=var, values=[i[0] for i in items],
                          state="readonly", width=26)
        cb.pack(side="left", fill="x", expand=True)
        lut = {lab: val for lab, val in items}
        cb.bind("<<ComboboxSelected>>",
                lambda _e: self.osc.send(f"/heli/ctrl/{ctrl_name}",
                                         int(lut[var.get()]) if kind == "int" else lut[var.get()]))
        return var

    def _slider(self, parent, label, ctrl_name, lo, hi, default, on_extra=None):
        """スライダー + 数値直接入力(スピンボックス)。両者は連動。"""
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        val = tk.IntVar(value=int(default))

        def emit():
            try:
                v = int(float(val.get()))
            except Exception:
                return
            v = max(int(lo), min(int(hi), v))
            if v != val.get():
                val.set(v)
            self._stage(f"/heli/ctrl/{ctrl_name}", int(v))
            if on_extra:
                on_extra(v)

        # 数値入力(スピンボックス)。Enter/フォーカスアウト/上下ボタンで確定。
        sb = ttk.Spinbox(fr, from_=lo, to=hi, textvariable=val, width=5,
                         command=emit)
        sb.pack(side="right")
        sb.bind("<Return>", lambda _e: emit())
        sb.bind("<FocusOut>", lambda _e: emit())
        # スライダー。ドラッグで数値も追従、離した値を送る。
        ttk.Scale(fr, from_=lo, to=hi, variable=val,
                  command=lambda _v: emit()).pack(
            side="left", fill="x", expand=True, padx=4)
        return val

    # ---------- 画面構築 ----------
    def _build(self):
        # タブは廃止し、住所・見た目・配置を1画面に縦並び。
        # 下部の「決定」「受信状態」は常時見えるよう固定、それ以外はスクロール可。
        self._build_status()        # 最下部(固定)
        self._build_apply_bar()     # その上(固定)
        body = self._scrollable_body()
        self._build_addr(body)
        self._build_look(body)
        self._build_place(body)
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
        # ホイールでスクロール(配置キャンバス上では無効化して誤スクロール防止)
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
        self._menu(s, "住所の粒度", ADDRLEVEL, "Addrlevel", 1)
        self._menu(s, "ビットレート", BAUD, "Baud", 0)
        fr = ttk.Frame(s); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="GPS音声ch(1-8)", width=16).pack(side="left")
        # 表示は1始まり(CH1..CH8)。内部/OSCは0始まりに変換して送る。
        self.audiochan = tk.IntVar(value=3)
        ttk.Spinbox(fr, from_=1, to=16, textvariable=self.audiochan, width=6,
                    command=lambda: self.osc.send("/heli/ctrl/Audiochan",
                                                  int(self.audiochan.get()) - 1)).pack(side="left")
        for label, ctrl, dflt in (("表示書式", "Textformat", "{address}上空"),
                                  ("受信途絶時の表示", "Staletext", "")):
            fr = ttk.Frame(s); fr.pack(fill="x", pady=3)
            ttk.Label(fr, text=label, width=16).pack(side="left")
            var = tk.StringVar(value=dflt)
            e = ttk.Entry(fr, textvariable=var); e.pack(side="left", fill="x", expand=True)
            act = lambda _e=None, v=var, cn=ctrl: self.osc.send(f"/heli/ctrl/{cn}", v.get())
            e.bind("<Return>", act)
            ttk.Button(fr, text="適用", width=5, command=act).pack(side="left")

    def _build_look(self, parent):
        s = self._section(parent, "見た目")
        self._build_font(s)
        self.size_var = self._slider(s, "文字サイズ", "Fontsize", 20, 250, self.font_size,
                                     on_extra=self._on_size)
        self._build_align(s)
        self._build_colors(s)
        self.stroke_var = self._slider(s, "フチの太さ", "Strokewidth", 0, 20,
                                       self._init_stroke_width)

    def _build_align(self, parent):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="文字揃え", width=16).pack(side="left")
        # 基準点(ドラッグ位置)に対して、左寄せ=右へ伸びる/右寄せ=左へ伸びる
        self._align_lut = {"左寄せ": "left", "中央": "center", "右寄せ": "right"}
        rev = {v: k for k, v in self._align_lut.items()}
        self.align_var = tk.StringVar(value=rev.get(self.align_x, "左寄せ"))
        cb = ttk.Combobox(fr, textvariable=self.align_var,
                          values=list(self._align_lut), state="readonly", width=10)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>",
                lambda _e: self._on_align(self._align_lut[self.align_var.get()]))

    def _on_align(self, ax):
        self.align_x = ax
        self._stage("/heli/ctrl/Alignx", ax)
        self._redraw_canvas()

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
        ttk.Label(s, text=f"文字をつかんでドラッグ(離すと確定)。空白クリックで中央移動。"
                          f"矢印キーで微調整。［{mode}］", style="Muted.TLabel").pack(pady=4)
        self.canvas = tk.Canvas(s, width=CANVAS_W, height=CANVAS_H, bg="#22262f",
                                highlightthickness=0, takefocus=1)
        self.canvas.pack(pady=6)
        self.pos_lbl = ttk.Label(s, text="", style="Muted.TLabel")
        self.pos_lbl.pack(anchor="w", padx=2)

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
            self.txt_shadow = self.canvas.create_text(0, 0, anchor="nw", text="", fill="black")
            self.txt_item = self.canvas.create_text(0, 0, anchor="nw", text="", fill="white")

        # ドラッグ中に出すゴースト枠(最初は隠しておく)
        self._ghost_box = self.canvas.create_rectangle(0, 0, 0, 0, outline="#0a84ff",
                                                        dash=(3, 2), width=2,
                                                        state="hidden")
        # 当たり判定はテロップ矩形(self._telop_bbox)で行うキャンバス全体バインド
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

    def _build_apply_bar(self):
        # 見た目・配置(フォント/文字サイズ/色/フチ/位置)の変更は、ここを押す
        # まで送出側に反映しない。誤操作で本番のスーパーが即変わるのを防ぐ。
        ap = ttk.Frame(self.root); ap.pack(side="bottom", fill="x", padx=10, pady=(2, 4))
        self.apply_btn = ttk.Button(ap, text="決定（反映）", state="disabled",
                                    style="Accent.TButton", command=self._apply_pending)
        self.apply_btn.pack(side="left", fill="x", expand=True)
        # 現在の見た目・位置を次回起動時の既定として保存
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

    def _build_font(self, parent):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="フォント", width=16).pack(side="left")
        fonts = list_system_fonts() if list_system_fonts else []
        if not fonts:
            fonts = FALLBACK_FONTS
        self._font_lut = {name: path for name, path in fonts}
        names = list(self._font_lut.keys())
        self.font_var = tk.StringVar(value=names[0] if names else "")
        cb = ttk.Combobox(fr, textvariable=self.font_var, values=names,
                          state="readonly", width=26)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", self._on_font)

    def _build_colors(self, parent):
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=6)
        ttk.Label(fr, text="文字色(中)", width=16).pack(side="left")
        self.fill_sw = tk.Label(fr, text="   ", bg=_hex(self.fill), relief="solid", width=4)
        self.fill_sw.pack(side="left", padx=4)
        ttk.Button(fr, text="選ぶ", width=5, command=self._pick_fill).pack(side="left")
        fr2 = ttk.Frame(parent); fr2.pack(fill="x", pady=6)
        ttk.Label(fr2, text="フチ色", width=16).pack(side="left")
        self.stroke_sw = tk.Label(fr2, text="   ", bg=_hex(self.stroke), relief="solid", width=4)
        self.stroke_sw.pack(side="left", padx=4)
        ttk.Button(fr2, text="選ぶ", width=5, command=self._pick_stroke).pack(side="left")

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
        name = self.font_var.get()
        path = self._font_lut.get(name, "")
        if path:
            self.osc.send("/heli/ctrl/Fontpath", path)
        if name:
            self.osc.send("/heli/ctrl/Font", name)
        self.osc.send("/heli/ctrl/Fontsize", int(self.size_var.get()))
        self.osc.send("/heli/ctrl/Strokewidth", int(self.stroke_var.get()))
        self.osc.send("/heli/ctrl/Alignx", self.align_x)
        for comp, ch in (("r", 0), ("g", 1), ("b", 2)):
            self.osc.send(f"/heli/ctrl/Fontcolor{comp}", float(self.fill[ch]))
            self.osc.send(f"/heli/ctrl/Strokecolor{comp}", float(self.stroke[ch]))
        self.osc.send("/heli/ctrl/Posx", float(self.pos[0]))
        self.osc.send("/heli/ctrl/Posy", float(self.pos[1]))

    def _collect_settings(self) -> dict:
        return {
            "font_name": self.font_var.get(),
            "font_size": int(self.size_var.get()),
            "align_x": self.align_x,
            "fill": list(self.fill),
            "stroke": list(self.stroke),
            "stroke_width": int(self.stroke_var.get()),
            "pos": list(self.pos),
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
        name = d.get("font_name", "")
        if name and name in self._font_lut:
            self.font_var.set(name)
        self.font_size = int(d.get("font_size", self.font_size))
        self.size_var.set(self.font_size)
        self.align_x = d.get("align_x", self.align_x)
        rev = {v: k for k, v in self._align_lut.items()}
        self.align_var.set(rev.get(self.align_x, "左寄せ"))
        self.fill = tuple(d.get("fill", self.fill)); self.fill_sw.config(bg=_hex(self.fill))
        self.stroke = tuple(d.get("stroke", self.stroke))
        self.stroke_sw.config(bg=_hex(self.stroke))
        self.stroke_var.set(int(d.get("stroke_width", self.stroke_var.get())))
        self.pos = list(d.get("pos", self.pos))
        self._redraw_canvas()
        self._broadcast_look()              # 呼出は即反映(決定不要)
        self._pending.clear(); self._mark_dirty()

    def _preset_flash(self, msg: str):
        if hasattr(self, "preset_msg"):
            self.preset_msg.config(text=msg)
            self.root.after(1800, lambda: self.preset_msg.config(text=""))

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

    # ---------- コールバック ----------
    def _on_font(self, _e=None):
        name = self.font_var.get()
        path = self._font_lut.get(name, "")
        if path:
            self._stage("/heli/ctrl/Fontpath", path)   # gst: 実ファイル指定
        self._stage("/heli/ctrl/Font", name)           # TD: フォント名

    def _on_size(self, v):
        self.font_size = int(v); self._redraw_canvas()

    def _pick_fill(self):
        rgb, hx = colorchooser.askcolor(color=_hex(self.fill), title="文字色(中)")
        if rgb is None:
            return
        self.fill = tuple(c / 255 for c in rgb); self.fill_sw.config(bg=hx)
        self._stage("/heli/ctrl/Fontcolorr", float(self.fill[0]))
        self._stage("/heli/ctrl/Fontcolorg", float(self.fill[1]))
        self._stage("/heli/ctrl/Fontcolorb", float(self.fill[2]))
        self._redraw_canvas()

    def _pick_stroke(self):
        rgb, hx = colorchooser.askcolor(color=_hex(self.stroke), title="フチ色")
        if rgb is None:
            return
        self.stroke = tuple(c / 255 for c in rgb); self.stroke_sw.config(bg=hx)
        self._stage("/heli/ctrl/Strokecolorr", float(self.stroke[0]))
        self._stage("/heli/ctrl/Strokecolorg", float(self.stroke[1]))
        self._stage("/heli/ctrl/Strokecolorb", float(self.stroke[2]))
        self._redraw_canvas()

    # ---------- 配置(ドラッグ) ----------
    def _anchor_canvas(self):
        """現在の基準点(pos)のキャンバス座標."""
        return (self.pos[0] / SCALE, self.pos[1] / SCALE)

    def _telop_hit(self, x, y) -> bool:
        bb = self._telop_bbox
        return bool(bb and bb[0] - 4 <= x <= bb[2] + 4 and bb[1] - 4 <= y <= bb[3] + 4)

    def _press(self, e):
        self.canvas.focus_set()          # 以後の矢印キーは位置調整へ
        if self._telop_hit(e.x, e.y):
            # つかんだ点と基準点のズレを記録(文字が角にジャンプしないように)
            ax, ay = self._anchor_canvas()
            self._drag_off = (e.x - ax, e.y - ay)
            self._dragging = True
            self._redraw_canvas()
        else:
            # 空白クリック: そこを文字の中央にする(角ではなく中央=直感的)
            self._place_center(e.x, e.y)

    def _drag_move(self, e):
        if not self._dragging:
            return
        ox, oy = self._drag_off
        cx = max(0, min(CANVAS_W, e.x - ox))
        cy = max(0, min(CANVAS_H, e.y - oy))
        self.pos = [int(cx * SCALE), int(cy * SCALE)]
        self._redraw_canvas(); self._send_pos()

    def _drag_end(self, _e=None):
        if self._dragging:
            self._dragging = False
            self._redraw_canvas()

    def _place_center(self, cxp, cyp):
        """キャンバス座標(cxp,cyp)を文字の中央に合わせて基準点を決める."""
        bb = self._telop_bbox
        w = (bb[2] - bb[0]) if bb else 0
        h = (bb[3] - bb[1]) if bb else 0
        # アンカー(横)から中央へのオフセット: left=+w/2, center=0, right=-w/2
        dx = {"left": w / 2, "center": 0, "right": -w / 2}.get(self.align_x, w / 2)
        ax = cxp - dx
        ay = cyp - h / 2          # 縦は上端基準なので中央は +h/2
        ax = max(0, min(CANVAS_W, ax)); ay = max(0, min(CANVAS_H, ay))
        self.pos = [int(ax * SCALE), int(ay * SCALE)]
        self._redraw_canvas(); self._send_pos()

    def _nudge(self, dx, dy):
        self.pos[0] += dx; self.pos[1] += dy
        self._redraw_canvas(); self._send_pos()

    def _send_pos(self):
        self._stage("/heli/ctrl/Posx", float(self.pos[0]))
        self._stage("/heli/ctrl/Posy", float(self.pos[1]))

    def _redraw_canvas(self):
        if getattr(self, "_pv_renderer", None):
            self._render_wysiwyg()
        elif hasattr(self, "txt_item"):
            self._render_text()
        self._update_ghost()
        if hasattr(self, "pos_lbl"):
            self.pos_lbl.config(text=f"位置  X: {self.pos[0]}  Y: {self.pos[1]}  px "
                                     f"(文字をつかんで移動 / 矢印キー1px・Shiftで10px)")

    def _render_wysiwyg(self):
        """本番と同じ Pillow レンダラで配置プレビューを描く(WYSIWYG)."""
        sc = self._pv_scale
        st = self._pv_renderer.style
        st.font_path = self._font_lut.get(self.font_var.get()) or None
        st.font_size = max(6, int(round(self.font_size * sc)))
        try:
            sw = int(self.stroke_var.get())
        except Exception:
            sw = 0
        st.stroke_width = max(0, int(round(sw * sc)))
        st.color = tuple(int(c * 255) for c in self.fill)
        st.stroke_color = tuple(int(c * 255) for c in self.stroke)
        st.align_x = self.align_x
        st.align_y = "top"
        st.margin_x = int(round(self.pos[0] * sc))
        st.margin_y = int(round(self.pos[1] * sc))
        txt = self.super_text or "(プレビュー)"
        try:
            telop = self._pv_renderer.render(txt)         # H×W×4 RGBA
            a = telop[:, :, 3:4].astype(np.float32) / 255.0
            out = self._backdrop.astype(np.float32) * (1 - a) + \
                telop[:, :, :3].astype(np.float32) * a
            img = Image.fromarray(out.astype(np.uint8), "RGB")
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.itemconfig(self._img_item, image=self._photo)
            ys, xs = np.where(telop[:, :, 3] > 0)
            self._telop_bbox = (int(xs.min()), int(ys.min()),
                                int(xs.max()), int(ys.max())) if len(xs) else None
        except Exception:
            self._telop_bbox = None

    def _render_text(self):
        """フォールバック: tkのテキストで簡易表示."""
        cx, cy = self._anchor_canvas()
        csize = max(6, int(self.font_size / SCALE))
        font = ("", csize, "bold")
        txt = self.super_text or "(プレビュー)"
        anchor = {"left": "nw", "center": "n", "right": "ne"}.get(self.align_x, "nw")
        self.canvas.itemconfig(self.txt_shadow, text=txt, fill=_hex(self.stroke),
                               font=font, anchor=anchor)
        self.canvas.itemconfig(self.txt_item, text=txt, fill=_hex(self.fill),
                               font=font, anchor=anchor)
        self.canvas.coords(self.txt_item, cx, cy)
        self.canvas.coords(self.txt_shadow, cx + 1, cy + 1)
        self._telop_bbox = self.canvas.bbox(self.txt_item)

    def _update_ghost(self):
        # ドラッグ中は文字の外接枠を表示(位置合わせの目安)
        if self._ghost_box is None:
            return
        if self._dragging and self._telop_bbox:
            bb = self._telop_bbox
            self.canvas.coords(self._ghost_box, bb[0] - 2, bb[1] - 2, bb[2] + 2, bb[3] + 2)
            self.canvas.itemconfig(self._ghost_box, state="normal")
            self.canvas.tag_raise(self._ghost_box)
        else:
            self.canvas.itemconfig(self._ghost_box, state="hidden")

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
