"""ヘリGPS音声デコーダ GUIアプリケーション.

PCのキャプチャボード(またはサウンドデバイス)の音声入力から
NNNフォーマットMSK音声をリアルタイム復調し、位置を表示する。

起動:
    python -m nnn_decoder.app

必要パッケージ: numpy, sounddevice
"""

from __future__ import annotations

import csv
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import numpy as np

from .geodesy import deg_to_dms_str
from .nmea import NmeaUdpSender
from .pipeline import DecoderPipeline

try:
    import sounddevice as sd
except (ImportError, OSError):  # OSError: PortAudio未導入
    sd = None

STALE_SEC = 5.0  # この秒数パケットが来なければ「受信途絶」表示


class DecoderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("ヘリGPS音声デコーダ (NNNフォーマット)")
        root.geometry("560x520")

        self._audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)
        self._stream = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._pipe: DecoderPipeline | None = None
        self._nmea: NmeaUdpSender | None = None
        self._csv_file = None
        self._csv_writer = None
        self._level = 0.0
        self._last_pkt = None
        self._last_pkt_time = 0.0
        self._lock = threading.Lock()

        self._build_ui()
        self._refresh_devices()
        self._tick()

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}
        cfg = ttk.LabelFrame(self.root, text="入力設定")
        cfg.pack(fill="x", **pad)

        ttk.Label(cfg, text="音声デバイス:").grid(row=0, column=0, sticky="e")
        self.device_cb = ttk.Combobox(cfg, width=42, state="readonly")
        self.device_cb.grid(row=0, column=1, columnspan=3, sticky="we", **pad)

        ttk.Label(cfg, text="チャンネル:").grid(row=1, column=0, sticky="e")
        self.channel_var = tk.StringVar(value="left")
        ttk.Combobox(cfg, textvariable=self.channel_var, width=6, state="readonly",
                     values=["left", "right", "mix"]).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(cfg, text="ビットレート:").grid(row=1, column=2, sticky="e")
        self.baud_var = tk.StringVar(value="1200")
        ttk.Combobox(cfg, textvariable=self.baud_var, width=6, state="readonly",
                     values=["1200", "2400"]).grid(row=1, column=3, sticky="w", **pad)

        self.nmea_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="NMEAをUDP送出 (127.0.0.1:10110)",
                        variable=self.nmea_var).grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        self.csv_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="CSVログ保存", variable=self.csv_var).grid(
            row=2, column=3, sticky="w", **pad)

        btns = ttk.Frame(self.root)
        btns.pack(fill="x", **pad)
        self.start_btn = ttk.Button(btns, text="受信開始", command=self.start)
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(btns, text="停止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left")
        ttk.Button(btns, text="デバイス再検索", command=self._refresh_devices).pack(side="left", padx=6)
        ttk.Button(btns, text="地図で開く", command=self._open_map).pack(side="right", padx=6)

        lv = ttk.Frame(self.root)
        lv.pack(fill="x", **pad)
        ttk.Label(lv, text="音声レベル:").pack(side="left")
        self.level_bar = ttk.Progressbar(lv, maximum=1.0)
        self.level_bar.pack(side="left", fill="x", expand=True, padx=6)

        pos = ttk.LabelFrame(self.root, text="ヘリコプター位置 (WGS84)")
        pos.pack(fill="both", expand=True, **pad)

        self.status_lbl = tk.Label(pos, text="― 停止中 ―", font=("", 14, "bold"),
                                   fg="white", bg="gray")
        self.status_lbl.pack(fill="x", padx=8, pady=6)

        self.pos_lbl = tk.Label(pos, text="--°--'--\"  /  ---°--'--\"",
                                font=("", 20, "bold"))
        self.pos_lbl.pack(pady=4)
        self.deg_lbl = tk.Label(pos, text="(--.------, ---.------)", font=("", 12))
        self.deg_lbl.pack()
        self.alt_lbl = tk.Label(pos, text="高度: ---- m", font=("", 16))
        self.alt_lbl.pack(pady=4)
        self.meta_lbl = tk.Label(pos, text="ID: --   PDOP: --   衛星数: --")
        self.meta_lbl.pack()
        self.stats_lbl = tk.Label(pos, text="正常パケット: 0   エラー: 0", fg="gray")
        self.stats_lbl.pack(pady=4)

    def _refresh_devices(self):
        if sd is None:
            self.device_cb["values"] = ["(sounddevice未インストール)"]
            self.device_cb.current(0)
            return
        items = []
        self._dev_indices = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                items.append(f"[{i}] {d['name']} ({d['max_input_channels']}ch)")
                self._dev_indices.append(i)
        self.device_cb["values"] = items
        if items:
            try:
                default_in = sd.default.device[0]
                self.device_cb.current(self._dev_indices.index(default_in))
            except (ValueError, TypeError):
                self.device_cb.current(0)

    # ---------- 受信制御 ----------
    def start(self):
        if sd is None:
            messagebox.showerror("エラー",
                                 "sounddevice がインストールされていません。\n"
                                 "pip install sounddevice を実行してください。")
            return
        if not self._dev_indices:
            messagebox.showerror("エラー", "入力デバイスが見つかりません。")
            return
        dev = self._dev_indices[self.device_cb.current()]
        info = sd.query_devices(dev)
        fs = int(info["default_samplerate"] or 48000)
        nch = min(2, info["max_input_channels"])

        self._pipe = DecoderPipeline(fs, baud=int(self.baud_var.get()))
        self._nmea = NmeaUdpSender() if self.nmea_var.get() else None
        if self.csv_var.get():
            path = filedialog.asksaveasfilename(
                defaultextension=".csv", initialfile=f"heligps_{datetime.now():%Y%m%d_%H%M%S}.csv")
            if path:
                self._csv_file = open(path, "w", newline="", encoding="utf-8-sig")
                self._csv_writer = csv.writer(self._csv_file)
                self._csv_writer.writerow(
                    ["time", "id", "fix_status", "lat_wgs84", "lon_wgs84",
                     "lat_tokyo", "lon_tokyo", "alt_m", "pdop", "satellites"])

        channel = self.channel_var.get()

        def audio_cb(indata, frames, t, status):
            x = indata[:, 0] if channel == "left" or indata.shape[1] == 1 else (
                indata[:, 1] if channel == "right" else indata.mean(axis=1))
            try:
                self._audio_q.put_nowait(x.copy())
            except queue.Full:
                pass

        try:
            self._stream = sd.InputStream(
                device=dev, channels=nch, samplerate=fs, dtype="float32",
                blocksize=int(fs * 0.1), callback=audio_cb)
            self._stream.start()
        except Exception as e:
            messagebox.showerror("エラー", f"音声デバイスを開けません:\n{e}")
            return

        self._running = True
        self._worker = threading.Thread(target=self._decode_loop, daemon=True)
        self._worker.start()
        self.start_btn["state"] = "disabled"
        self.stop_btn["state"] = "normal"
        self.status_lbl.config(text="受信待ち…", bg="#c90")

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._nmea:
            self._nmea.close()
            self._nmea = None
        if self._csv_file:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None
        self.start_btn["state"] = "normal"
        self.stop_btn["state"] = "disabled"
        self.status_lbl.config(text="― 停止中 ―", bg="gray")

    def _decode_loop(self):
        import time
        while self._running:
            try:
                x = self._audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._level = float(np.max(np.abs(x))) if len(x) else 0.0
            pkts = self._pipe.process(x.astype(np.float64))
            for pkt in pkts:
                with self._lock:
                    self._last_pkt = pkt
                    self._last_pkt_time = time.monotonic()
                if self._nmea:
                    self._nmea.send(pkt)
                if self._csv_writer:
                    self._csv_writer.writerow(
                        [datetime.now().isoformat(timespec="seconds"),
                         pkt.station_id, pkt.fix_status,
                         f"{pkt.lat_wgs84:.6f}", f"{pkt.lon_wgs84:.6f}",
                         f"{pkt.lat_tokyo:.6f}", f"{pkt.lon_tokyo:.6f}",
                         f"{pkt.alt_m:.0f}", pkt.pdop, pkt.satellites])

    # ---------- 画面更新 ----------
    def _tick(self):
        import time
        self.level_bar["value"] = self._level
        if self._pipe:
            s = self._pipe.stats
            self.stats_lbl.config(
                text=f"正常パケット: {s['packets_ok']}   エラー: {s['packets_error']}")
        with self._lock:
            pkt = self._last_pkt
            age = time.monotonic() - self._last_pkt_time if pkt else None
        if pkt is not None:
            self.pos_lbl.config(
                text=f"{deg_to_dms_str(pkt.lat_wgs84)} N  /  {deg_to_dms_str(pkt.lon_wgs84)} E")
            self.deg_lbl.config(text=f"({pkt.lat_wgs84:.6f}, {pkt.lon_wgs84:.6f})")
            self.alt_lbl.config(text=f"高度: {pkt.alt_m:.0f} m")
            self.meta_lbl.config(
                text=f"ID: {pkt.station_id}   PDOP: {pkt.pdop or '--'}   "
                     f"衛星数: {pkt.satellites if pkt.satellites is not None else '--'}")
            if self._running:
                if age is not None and age > STALE_SEC:
                    self.status_lbl.config(text=f"受信途絶 ({age:.0f}秒)", bg="#c33")
                elif pkt.fix_status == 0:
                    txt = "正常測位" if pkt.in_range else "正常測位 [有効範囲外]"
                    self.status_lbl.config(text=txt, bg="#2a2")
                elif pkt.fix_status == 1:
                    self.status_lbl.config(text="バックアップ(前回測位値)", bg="#c90")
                else:
                    self.status_lbl.config(text="GPSデータ使用不能", bg="#c33")
        self.root.after(200, self._tick)

    def _open_map(self):
        with self._lock:
            pkt = self._last_pkt
        if pkt is None:
            messagebox.showinfo("地図", "まだ位置を受信していません。")
            return
        webbrowser.open(
            f"https://www.google.com/maps?q={pkt.lat_wgs84:.6f},{pkt.lon_wgs84:.6f}")


def main():
    root = tk.Tk()
    app = DecoderApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
