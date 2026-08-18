"""オフライン地図ウィンドウ(ヘリ位置プロット).

インターネット接続なしで、同梱の市区町村境界(国土数値情報由来)を
ベクター地図として描画し、現在のヘリ位置をマーカー表示する。

    from ui_map import MapWindow
    mw = MapWindow(root, palette)
    mw.update_position(lat, lon, address)   # /heli/position 受信ごとに呼ぶ

境界データの読み込み(数MB)は初回のみ・別スレッドで行う。
"""

from __future__ import annotations

import math
import threading
import tkinter as tk
from tkinter import ttk


class MapWindow:
    def __init__(self, parent, palette: dict | None = None):
        p = palette or {}
        self.bg = "#0b1020"          # 地図の地(濃紺)
        self.land = "#1b2440"        # 陸(面)
        self.line = "#3a4a78"        # 境界線
        self.heli = "#ff3b30"        # ヘリ(赤)
        self.trailc = "#ff9f0a"      # 軌跡(橙)
        self.ink = p.get("ink", "#e8e8ee")

        self.top = tk.Toplevel(parent)
        self.top.title("ヘリ位置 地図(オフライン)")
        self.top.configure(bg=p.get("bg", "#f5f5f7"))
        self.top.geometry("720x760")

        self.W, self.H = 700, 660
        self.span = 0.40             # 画面横に収める経度[度](ズームで変える)
        self.center = None           # (lon, lat)
        self.follow = tk.BooleanVar(value=True)
        self.trail: list[tuple[float, float]] = []
        self.lookup = None
        self._loading = True
        self._last_pos = None
        self._addr = ""

        bar = ttk.Frame(self.top); bar.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Button(bar, text="－", width=3, command=lambda: self.zoom(1.4)).pack(side="left")
        ttk.Button(bar, text="＋", width=3, command=lambda: self.zoom(1 / 1.4)).pack(side="left", padx=(4, 10))
        ttk.Checkbutton(bar, text="ヘリに追従", variable=self.follow).pack(side="left")
        self.info = ttk.Label(bar, text="地図データを読み込み中…")
        self.info.pack(side="right")

        self.canvas = tk.Canvas(self.top, width=self.W, height=self.H,
                                bg=self.bg, highlightthickness=0)
        self.canvas.pack(padx=10, pady=(0, 10), fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self.zoom(1 / 1.2))
        self.canvas.bind("<Button-5>", lambda e: self.zoom(1.2))

        self._drawn_once = False
        threading.Thread(target=self._load, daemon=True).start()
        self.top.after(300, self._tick)

    # ---- データ読み込み(別スレッド。UI描画はメインスレッドの_tickで) ----
    def _load(self):
        try:
            from nnn_decoder.geocode import OfflineMuniLookup
            lk = OfflineMuniLookup()
        except Exception as e:
            lk = None
            self._load_err = str(e)
        self.lookup = lk
        self._loading = False

    def _tick(self):
        # メインスレッドで読み込み完了を検知して1回描画(スレッド安全)
        if not self.alive():
            return
        if not self._loading and not self._drawn_once:
            self._drawn_once = True
            self._redraw()
        self.top.after(400, self._tick)

    def alive(self) -> bool:
        try:
            return bool(self.top.winfo_exists())
        except Exception:
            return False

    # ---- 操作 ----
    def zoom(self, factor: float):
        self.span = max(0.02, min(6.0, self.span * factor))
        self._redraw()

    def _on_wheel(self, e):
        self.zoom(1 / 1.2 if e.delta > 0 else 1.2)

    def _on_resize(self, e):
        self.W, self.H = e.width, e.height
        self._redraw()

    def update_position(self, lat: float, lon: float, address: str = ""):
        if not self.alive():
            return
        self._last_pos = (lon, lat)
        self._addr = address or ""
        if self.center is None or self.follow.get():
            self.center = (lon, lat)
        if not self.trail or self._dist(self.trail[-1], (lon, lat)) > 0.0005:
            self.trail.append((lon, lat))
            if len(self.trail) > 600:
                self.trail = self.trail[-600:]
        self._redraw()

    @staticmethod
    def _dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    # ---- 投影 ----
    def _scales(self):
        cx_lon, cy_lat = self.center
        px_per_lon = self.W / self.span
        px_per_lat = px_per_lon / max(0.2, math.cos(math.radians(cy_lat)))
        return px_per_lon, px_per_lat

    def _project(self, lon, lat):
        cx_lon, cy_lat = self.center
        px_lon, px_lat = self._scales()
        x = self.W / 2 + (lon - cx_lon) * px_lon
        y = self.H / 2 - (lat - cy_lat) * px_lat
        return x, y

    def _view_bbox(self):
        cx_lon, cy_lat = self.center
        px_lon, px_lat = self._scales()
        half_lon = (self.W / 2) / px_lon
        half_lat = (self.H / 2) / px_lat
        return (cx_lon - half_lon, cy_lat - half_lat,
                cx_lon + half_lon, cy_lat + half_lat)

    # ---- 描画 ----
    def _redraw(self):
        if not self.alive():
            return
        c = self.canvas
        c.delete("all")
        if self._loading:
            c.create_text(self.W / 2, self.H / 2, text="地図データを読み込み中…",
                          fill=self.ink, font=("", 12))
            return
        if self.lookup is None:
            c.create_text(self.W / 2, self.H / 2,
                          text="地図データを読み込めませんでした",
                          fill=self.heli, font=("", 12))
            return
        if self.center is None:
            c.create_text(self.W / 2, self.H / 2,
                          text="GPS受信待ち(位置を受信すると地図を表示)",
                          fill=self.ink, font=("", 12))
            return

        lon0, lat0, lon1, lat1 = self._view_bbox()
        m = (lon1 - lon0) * 0.1
        geoms = self.lookup.geoms_in_view(lon0 - m, lat0 - m, lon1 + m, lat1 + m)
        for _cd, rings in geoms:
            for xs, ys in rings:
                pts = []
                for k in range(len(xs)):
                    x, y = self._project(xs[k], ys[k])
                    pts.append(x); pts.append(y)
                if len(pts) >= 6:
                    c.create_polygon(*pts, fill=self.land, outline=self.line,
                                     width=1)

        # 軌跡
        if len(self.trail) >= 2:
            tp = []
            for lon, lat in self.trail:
                x, y = self._project(lon, lat)
                tp.append(x); tp.append(y)
            c.create_line(*tp, fill=self.trailc, width=2, smooth=True)

        # 現在位置マーカー
        if self._last_pos is not None:
            x, y = self._project(*self._last_pos)
            c.create_line(x - 12, y, x + 12, y, fill=self.heli, width=1)
            c.create_line(x, y - 12, x, y + 12, fill=self.heli, width=1)
            c.create_oval(x - 6, y - 6, x + 6, y + 6, outline=self.heli, width=2)

        # スケールバー(概算)
        px_lon, _ = self._scales()
        km = 5.0
        seg = (km * 1000) / (111320 * math.cos(math.radians(self.center[1]))) * px_lon
        if 20 < seg < self.W:
            y0 = self.H - 24
            c.create_line(16, y0, 16 + seg, y0, fill=self.ink, width=2)
            c.create_text(16 + seg / 2, y0 - 10, text=f"{km:.0f} km",
                          fill=self.ink, font=("", 9))

        if self._last_pos is not None:
            lon, lat = self._last_pos
            txt = f"{self._addr}   {lat:.5f}, {lon:.5f}   (span {self.span:.2f}°)"
            self.info.config(text=txt)
