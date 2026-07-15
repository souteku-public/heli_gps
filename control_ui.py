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
依存:  標準ライブラリのみ(tkinter, socket)
"""

from __future__ import annotations

import argparse
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import colorchooser, ttk

from nnn_decoder.osc import osc_message, osc_parse

try:
    from gst_heli.fonts import list_system_fonts
except Exception:
    list_system_fonts = None

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
        self.fill = (1.0, 1.0, 1.0)
        self.stroke = (0.0, 0.0, 0.0)
        self.font_size = 90
        self.super_text = "(プレビュー)"
        self.pos = [480, 900]        # フレーム座標(左上, px)
        root.title("ヘリGPS スーパー制御")
        root.geometry("560x820")
        self._build()
        # 初期値を送信(align=左上・絶対座標方式に固定)
        self.osc.send("/heli/ctrl/Alignx", "left")
        self.osc.send("/heli/ctrl/Aligny", "top")
        self._send_pos()
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
        fr = ttk.Frame(parent); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        val = tk.DoubleVar(value=default)
        vlab = ttk.Label(fr, text=f"{default:g}", width=5); vlab.pack(side="right")

        def on_move(_v):
            v = val.get(); vlab.config(text=f"{v:.0f}")
            self.osc.send(f"/heli/ctrl/{ctrl_name}", int(v))
            if on_extra:
                on_extra(v)
        ttk.Scale(fr, from_=lo, to=hi, variable=val, command=on_move).pack(
            side="left", fill="x", expand=True, padx=4)
        return val

    # ---------- 画面構築 ----------
    def _build(self):
        nb = ttk.Notebook(self.root); nb.pack(fill="both", expand=True, padx=6, pady=6)

        # === 住所 ===
        t1 = ttk.Frame(nb); nb.add(t1, text="住所")
        self._menu(t1, "住所変換モード", GEOMODE, "Geomode", 0)
        self._menu(t1, "住所の粒度", ADDRLEVEL, "Addrlevel", 1)
        self._menu(t1, "ビットレート", BAUD, "Baud", 0)
        fr = ttk.Frame(t1); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="GPS音声ch(0始)", width=16).pack(side="left")
        self.audiochan = tk.IntVar(value=2)
        ttk.Spinbox(fr, from_=0, to=15, textvariable=self.audiochan, width=6,
                    command=lambda: self.osc.send("/heli/ctrl/Audiochan",
                                                  int(self.audiochan.get()))).pack(side="left")
        for label, ctrl, dflt in (("表示書式", "Textformat", "{address}上空"),
                                  ("受信途絶時の表示", "Staletext", "")):
            fr = ttk.Frame(t1); fr.pack(fill="x", pady=3)
            ttk.Label(fr, text=label, width=16).pack(side="left")
            var = tk.StringVar(value=dflt)
            e = ttk.Entry(fr, textvariable=var); e.pack(side="left", fill="x", expand=True)
            act = lambda _e=None, v=var, cn=ctrl: self.osc.send(f"/heli/ctrl/{cn}", v.get())
            e.bind("<Return>", act)
            ttk.Button(fr, text="適用", width=5, command=act).pack(side="left")

        # === 見た目 ===
        t2 = ttk.Frame(nb); nb.add(t2, text="見た目")
        self._build_font(t2)
        self.size_var = self._slider(t2, "文字サイズ", "Fontsize", 20, 250, self.font_size,
                                     on_extra=self._on_size)
        self._build_colors(t2)
        self.stroke_var = self._slider(t2, "フチの太さ", "Strokewidth", 0, 20, 5)

        # === 配置(ドラッグ) ===
        t3 = ttk.Frame(nb); nb.add(t3, text="配置")
        ttk.Label(t3, text="文字をドラッグして位置を決めてください(矢印キーで微調整)").pack(pady=4)
        self.canvas = tk.Canvas(t3, width=CANVAS_W, height=CANVAS_H, bg="#334",
                                highlightthickness=1, highlightbackground="#888")
        self.canvas.pack(pady=6)
        self.canvas.create_rectangle(2, 2, CANVAS_W - 2, CANVAS_H - 2, outline="#aaa")
        # セーフエリア目安
        self.canvas.create_rectangle(CANVAS_W * 0.05, CANVAS_H * 0.05,
                                     CANVAS_W * 0.95, CANVAS_H * 0.95,
                                     outline="#556", dash=(3, 3))
        self.txt_shadow = self.canvas.create_text(0, 0, anchor="nw", text="", fill="black")
        self.txt_item = self.canvas.create_text(0, 0, anchor="nw", text="", fill="white")
        self.canvas.tag_bind(self.txt_item, "<ButtonPress-1>", self._drag_start)
        self.canvas.tag_bind(self.txt_item, "<B1-Motion>", self._drag_move)
        self.canvas.bind("<Button-1>", self._canvas_click)  # 空白クリックでそこへ移動
        for key, dx, dy in (("<Up>", 0, -1), ("<Down>", 0, 1),
                            ("<Left>", -1, 0), ("<Right>", 1, 0)):
            self.root.bind(key, lambda e, dx=dx, dy=dy:
                           self._nudge(dx * (10 if e.state & 1 else 1),
                                       dy * (10 if e.state & 1 else 1)))
        self._redraw_canvas()

        # === 状態表示 ===
        st = ttk.LabelFrame(self.root, text="受信状態"); st.pack(fill="x", padx=6, pady=6)
        self.recv_lbl = tk.Label(st, text="● 未受信", fg="white", bg="gray",
                                 font=("", 12, "bold")); self.recv_lbl.pack(fill="x", padx=6, pady=4)
        self.super_lbl = tk.Label(st, text="―", font=("", 18, "bold")); self.super_lbl.pack(pady=2)
        self.info_lbl = tk.Label(st, text="緯度 --  経度 --  高度 --"); self.info_lbl.pack()
        self.fix_lbl = tk.Label(st, text="測位 --  衛星 --"); self.fix_lbl.pack(pady=2)

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
        self.fill_sw = tk.Label(fr, text="   ", bg="#ffffff", relief="solid", width=4)
        self.fill_sw.pack(side="left", padx=4)
        ttk.Button(fr, text="選ぶ", width=5, command=self._pick_fill).pack(side="left")
        fr2 = ttk.Frame(parent); fr2.pack(fill="x", pady=6)
        ttk.Label(fr2, text="フチ色", width=16).pack(side="left")
        self.stroke_sw = tk.Label(fr2, text="   ", bg="#000000", relief="solid", width=4)
        self.stroke_sw.pack(side="left", padx=4)
        ttk.Button(fr2, text="選ぶ", width=5, command=self._pick_stroke).pack(side="left")

    # ---------- コールバック ----------
    def _on_font(self, _e=None):
        name = self.font_var.get()
        path = self._font_lut.get(name, "")
        if path:
            self.osc.send("/heli/ctrl/Fontpath", path)   # gst: 実ファイル指定
        self.osc.send("/heli/ctrl/Font", name)           # TD: フォント名

    def _on_size(self, v):
        self.font_size = int(v); self._redraw_canvas()

    def _pick_fill(self):
        rgb, hx = colorchooser.askcolor(color=_hex(self.fill), title="文字色(中)")
        if rgb is None:
            return
        self.fill = tuple(c / 255 for c in rgb); self.fill_sw.config(bg=hx)
        self.osc.send("/heli/ctrl/Fontcolorr", float(self.fill[0]))
        self.osc.send("/heli/ctrl/Fontcolorg", float(self.fill[1]))
        self.osc.send("/heli/ctrl/Fontcolorb", float(self.fill[2]))
        self._redraw_canvas()

    def _pick_stroke(self):
        rgb, hx = colorchooser.askcolor(color=_hex(self.stroke), title="フチ色")
        if rgb is None:
            return
        self.stroke = tuple(c / 255 for c in rgb); self.stroke_sw.config(bg=hx)
        self.osc.send("/heli/ctrl/Strokecolorr", float(self.stroke[0]))
        self.osc.send("/heli/ctrl/Strokecolorg", float(self.stroke[1]))
        self.osc.send("/heli/ctrl/Strokecolorb", float(self.stroke[2]))
        self._redraw_canvas()

    # ---------- 配置(ドラッグ) ----------
    def _drag_start(self, e):
        self._drag_off = (e.x, e.y)

    def _drag_move(self, e):
        cx = max(0, min(CANVAS_W, e.x)); cy = max(0, min(CANVAS_H, e.y))
        self.pos = [int(cx * SCALE), int(cy * SCALE)]
        self._redraw_canvas(); self._send_pos()

    def _canvas_click(self, e):
        # テキスト以外をクリックしたらそこを左上に移動
        self.pos = [int(e.x * SCALE), int(e.y * SCALE)]
        self._redraw_canvas(); self._send_pos()

    def _nudge(self, dx, dy):
        self.pos[0] += dx; self.pos[1] += dy
        self._redraw_canvas(); self._send_pos()

    def _send_pos(self):
        self.osc.send("/heli/ctrl/Posx", float(self.pos[0]))
        self.osc.send("/heli/ctrl/Posy", float(self.pos[1]))

    def _redraw_canvas(self):
        cx, cy = self.pos[0] / SCALE, self.pos[1] / SCALE
        csize = max(6, int(self.font_size / SCALE))
        font = ("", csize, "bold")
        txt = self.super_text or "(プレビュー)"
        self.canvas.itemconfig(self.txt_item, text=txt, fill=_hex(self.fill), font=font)
        self.canvas.itemconfig(self.txt_shadow, text=txt, fill=_hex(self.stroke), font=font)
        self.canvas.coords(self.txt_item, cx, cy)
        self.canvas.coords(self.txt_shadow, cx + 1, cy + 1)

    # ---------- 状態受信 ----------
    def _poll(self):
        try:
            while True:
                a, args = self.osc.inbox.get_nowait()
                self._on_status(a, args)
        except queue.Empty:
            pass
        if time.monotonic() - self._last_status > STALE_SEC:
            self.recv_lbl.config(text="● GPS途絶/未受信", bg="#c33")
        self.root.after(200, self._poll)

    def _on_status(self, a, args):
        self._last_status = time.monotonic()
        self.recv_lbl.config(text="● 受信中", bg="#2a2")
        if a == "/heli/super" and args:
            self.super_text = args[0]
            self.super_lbl.config(text=args[0] or "(表示なし)")
            self._redraw_canvas()
        elif a == "/heli/position" and len(args) >= 3:
            self.info_lbl.config(text=f"緯度 {args[0]:.5f}  経度 {args[1]:.5f}  高度 {args[2]:.0f}m")
        elif a == "/heli/status" and len(args) >= 3:
            fix = {0: "正常", 1: "バックアップ", 2: "使用不能"}.get(args[0], "?")
            sats = "--" if args[1] < 0 else args[1]
            self.fix_lbl.config(text=f"測位 {fix}  衛星 {sats}")


def main():
    ap = argparse.ArgumentParser(description="ヘリGPS スーパー制御UI")
    ap.add_argument("--td-host", default="127.0.0.1")
    ap.add_argument("--ctrl-port", type=int, default=9001)
    ap.add_argument("--status-port", type=int, default=9002)
    args = ap.parse_args()
    osc = OscClient(args.td_host, args.ctrl_port, args.status_port)
    root = tk.Tk()
    ControlUI(root, osc)
    root.protocol("WM_DELETE_WINDOW", lambda: (osc.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
