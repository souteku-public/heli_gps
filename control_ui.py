"""ヘリGPSスーパー 外部制御UI (tkinter).

TouchDesignerのHELI_GPSを、OSC(UDP)経由でグラフィカルに操作する制御パネル。
TDのControlパラメータより操作しやすいUIを目的とする。

    UI → OSC 127.0.0.1:9001 → TDの osc_ctrl (OSC In DAT)
    TD → OSC 127.0.0.1:9002 → このUI(状態表示: 住所/緯度/fix/受信状態)

起動:
    python control_ui.py
    (別PCのTDを操作する場合)  python control_ui.py --td-host 192.168.0.10

依存: 標準ライブラリのみ(tkinter, socket)。numpy等は不要。
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

# メニュー: (表示ラベル, 送信値)
GEOMODE = [("オフライン(ネット不要)", "offline"),
           ("自動(ネット時は町丁目)", "auto"),
           ("オンライン(地理院API)", "online")]
ADDRLEVEL = [("都道府県", "pref"), ("市町村(政令市は市まで)", "muni"),
             ("市区町村(区あり)", "city"), ("町丁目(要ネット)", "town")]
ALIGNX = [("左", "left"), ("中央", "center"), ("右", "right")]
ALIGNY = [("下", "bottom"), ("中央", "center"), ("上", "top")]
BAUD = [("1200 bps", "1200"), ("2400 bps", "2400")]
FONTS = ["Yu Gothic UI", "Yu Gothic", "BIZ UDPGothic", "Meiryo", "MS Gothic",
         "Noto Sans JP", "HGP創英角ゴシックUB", "游明朝", "MS Mincho"]

STALE_SEC = 3.0


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
            addr, args = osc_parse(data)
            if addr:
                self.inbox.put((addr, args))

    def close(self):
        self._stop = True


class ControlUI:
    def __init__(self, root, osc):
        self.root = root
        self.osc = osc
        self._last_status = 0.0
        root.title("ヘリGPS スーパー制御")
        root.geometry("520x760")
        self._build()
        self._poll()

    def _menu(self, parent, label, items, ctrl_name, default_idx=0, kind="str"):
        fr = ttk.Frame(parent)
        fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        var = tk.StringVar(value=items[default_idx][0])
        labels = [it[0] for it in items]
        cb = ttk.Combobox(fr, textvariable=var, values=labels, state="readonly", width=24)
        cb.pack(side="left", fill="x", expand=True)
        lut = {lab: val for lab, val in items}

        def on_sel(_e=None):
            v = lut[var.get()]
            self.osc.send(f"/heli/ctrl/{ctrl_name}", int(v) if kind == "int" else v)
        cb.bind("<<ComboboxSelected>>", on_sel)
        return var, on_sel

    def _slider(self, parent, label, ctrl_name, lo, hi, default, kind="float"):
        fr = ttk.Frame(parent)
        fr.pack(fill="x", pady=3)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        val = tk.DoubleVar(value=default)
        vlab = ttk.Label(fr, text=f"{default:g}", width=5)
        vlab.pack(side="right")

        def on_move(_v):
            v = val.get()
            vlab.config(text=f"{v:.0f}")
            self.osc.send(f"/heli/ctrl/{ctrl_name}", int(v) if kind == "int" else float(v))
        s = ttk.Scale(fr, from_=lo, to=hi, variable=val, command=on_move)
        s.pack(side="left", fill="x", expand=True, padx=4)
        return val

    def _build(self):
        pad = {"padx": 8}
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # ===== 住所タブ =====
        t1 = ttk.Frame(nb)
        nb.add(t1, text="住所")
        self._menu(t1, "住所変換モード", GEOMODE, "Geomode", 0)
        self._menu(t1, "住所の粒度", ADDRLEVEL, "Addrlevel", 1)
        self._menu(t1, "ビットレート", BAUD, "Baud", 0)
        fr = ttk.Frame(t1); fr.pack(fill="x", pady=3)
        ttk.Label(fr, text="GPS音声ch(0始)", width=16).pack(side="left")
        self.audiochan = tk.IntVar(value=2)
        ttk.Spinbox(fr, from_=0, to=15, textvariable=self.audiochan, width=6,
                    command=lambda: self.osc.send("/heli/ctrl/Audiochan",
                                                  int(self.audiochan.get()))).pack(side="left")
        for label, ctrl in (("表示書式", "Textformat"), ("受信途絶時の表示", "Staletext")):
            fr = ttk.Frame(t1); fr.pack(fill="x", pady=3)
            ttk.Label(fr, text=label, width=16).pack(side="left")
            var = tk.StringVar(value="{address}上空" if ctrl == "Textformat" else "")
            e = ttk.Entry(fr, textvariable=var)
            e.pack(side="left", fill="x", expand=True)
            e.bind("<Return>", lambda _e, v=var, cn=ctrl: self.osc.send(f"/heli/ctrl/{cn}", v.get()))
            ttk.Button(fr, text="適用", width=5,
                       command=lambda v=var, cn=ctrl: self.osc.send(f"/heli/ctrl/{cn}", v.get())).pack(side="left")

        # ===== 見た目タブ =====
        t2 = ttk.Frame(nb)
        nb.add(t2, text="見た目")
        self._menu(t2, "フォント", [(f, f) for f in FONTS], "Font", 0)
        self.fontsize = self._slider(t2, "文字サイズ", "Fontsize", 10, 300, 90)
        self._menu(t2, "横位置基準", ALIGNX, "Alignx", 1)
        self._menu(t2, "縦位置基準", ALIGNY, "Aligny", 0)
        self.posx = self._slider(t2, "位置X(px)", "Posx", -960, 960, 0)
        self.posy = self._slider(t2, "位置Y(px)", "Posy", -540, 540, 60)

        fr = ttk.Frame(t2); fr.pack(fill="x", pady=6)
        ttk.Label(fr, text="文字色", width=16).pack(side="left")
        self.color_sw = tk.Label(fr, text="   ", bg="#ffffff", relief="solid", width=4)
        self.color_sw.pack(side="left", padx=4)
        ttk.Button(fr, text="色を選ぶ", command=self._pick_color).pack(side="left")

        # 矢印キーによる位置微調整
        nudge = ttk.LabelFrame(t2, text="位置微調整 (矢印キー / ボタン。Shiftで×10)")
        nudge.pack(fill="x", pady=8)
        grid = ttk.Frame(nudge); grid.pack(pady=4)
        ttk.Button(grid, text="↑", width=4, command=lambda: self._nudge(0, 1)).grid(row=0, column=1)
        ttk.Button(grid, text="←", width=4, command=lambda: self._nudge(-1, 0)).grid(row=1, column=0)
        ttk.Button(grid, text="↓", width=4, command=lambda: self._nudge(0, -1)).grid(row=1, column=1)
        ttk.Button(grid, text="→", width=4, command=lambda: self._nudge(1, 0)).grid(row=1, column=2)
        self.root.bind("<Up>", lambda e: self._nudge(0, 10 if e.state & 1 else 1))
        self.root.bind("<Down>", lambda e: self._nudge(0, -10 if e.state & 1 else -1))
        self.root.bind("<Left>", lambda e: self._nudge(-10 if e.state & 1 else -1, 0))
        self.root.bind("<Right>", lambda e: self._nudge(10 if e.state & 1 else 1, 0))

        # ===== 状態表示 =====
        st = ttk.LabelFrame(self.root, text="受信状態")
        st.pack(fill="x", padx=6, pady=6)
        self.recv_lbl = tk.Label(st, text="● 未受信", fg="white", bg="gray",
                                 font=("", 12, "bold"))
        self.recv_lbl.pack(fill="x", padx=6, pady=4)
        self.super_lbl = tk.Label(st, text="―", font=("", 20, "bold"))
        self.super_lbl.pack(pady=4)
        self.info_lbl = tk.Label(st, text="緯度 --  経度 --  高度 --", font=("", 11))
        self.info_lbl.pack()
        self.fix_lbl = tk.Label(st, text="測位 --  衛星 --  ID --", font=("", 11))
        self.fix_lbl.pack(pady=2)

    def _pick_color(self):
        rgb, hx = colorchooser.askcolor(color="#ffffff", title="文字色")
        if rgb is None:
            return
        self.color_sw.config(bg=hx)
        r, g, b = (c / 255.0 for c in rgb)
        self.osc.send("/heli/ctrl/Fontcolorr", float(r))
        self.osc.send("/heli/ctrl/Fontcolorg", float(g))
        self.osc.send("/heli/ctrl/Fontcolorb", float(b))

    def _nudge(self, dx, dy):
        self.posx.set(self.posx.get() + dx)
        self.posy.set(self.posy.get() + dy)
        self.osc.send("/heli/ctrl/Posx", float(self.posx.get()))
        self.osc.send("/heli/ctrl/Posy", float(self.posy.get()))

    def _poll(self):
        try:
            while True:
                addr, args = self.osc.inbox.get_nowait()
                self._on_status(addr, args)
        except queue.Empty:
            pass
        # 受信インジケータ
        if time.monotonic() - self._last_status > STALE_SEC:
            self.recv_lbl.config(text="● GPS途絶/未受信", bg="#c33")
        self.root.after(200, self._poll)

    def _on_status(self, addr, args):
        self._last_status = time.monotonic()
        self.recv_lbl.config(text="● 受信中", bg="#2a2")
        if addr == "/heli/super" and args:
            self.super_lbl.config(text=args[0] or "(表示なし)")
        elif addr == "/heli/position" and len(args) >= 3:
            self.info_lbl.config(
                text=f"緯度 {args[0]:.5f}  経度 {args[1]:.5f}  高度 {args[2]:.0f}m")
        elif addr == "/heli/status" and len(args) >= 3:
            fix = {0: "正常", 1: "バックアップ", 2: "使用不能"}.get(args[0], "?")
            sats = "--" if args[1] < 0 else args[1]
            self.fix_lbl.config(text=f"測位 {fix}  衛星 {sats}  ID {args[2]}")


def main():
    ap = argparse.ArgumentParser(description="ヘリGPS スーパー制御UI")
    ap.add_argument("--td-host", default="127.0.0.1", help="TouchDesignerのIP")
    ap.add_argument("--ctrl-port", type=int, default=9001, help="制御送出ポート")
    ap.add_argument("--status-port", type=int, default=9002, help="状態受信ポート")
    args = ap.parse_args()

    osc = OscClient(args.td_host, args.ctrl_port, args.status_port)
    root = tk.Tk()
    ControlUI(root, osc)
    root.protocol("WM_DELETE_WINDOW", lambda: (osc.close(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
