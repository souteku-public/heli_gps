"""逆ジオコーディング(緯度経度 → 住所).

2つのエンジンを持つ:

1) オフライン(既定): 同梱の市区町村境界データで点内判定。
   インターネット不要で市区町村名まで分かる。
   境界データ: 国土数値情報(行政区域データ, 国土交通省)を
   スマートニュース メディア研究所が簡略化したものを再加工
   (nnn_decoder/data/muni_boundaries.json.gz)
2) オンライン: 国土地理院の逆ジオコーダAPI。町丁目まで分かる。
   通信断のときは前回結果を保持して運用を継続する。

市区町村コード→名称は同梱テーブル(data/muni.json, 地理院地図muni.js由来)。

modeパラメータ:
    "offline" (既定) … 同梱データのみ。ネット接続不要。町丁目は出ない
    "online"          … APIのみ(町丁目が必要な場合)
    "auto"            … オフラインで市区町村を即時解決しつつ、
                        ネットが使えれば町丁目をAPIで補完
"""

from __future__ import annotations

import gzip
import json
import math
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

API_URL = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress"
_MUNI_PATH = Path(__file__).parent / "data" / "muni.json"
_BOUNDARY_PATH = Path(__file__).parent / "data" / "muni_boundaries.json.gz"


@dataclass
class Address:
    pref: str          # 都道府県 (例 "千葉県")
    city: str          # 市区町村 (例 "千葉市美浜区")
    town: str = ""     # 町丁目 (例 "幕張西三丁目")
    muni_cd: str = ""

    def text(self, level: str = "city") -> str:
        """表示用文字列. level: 'pref' / 'city' / 'town'"""
        if level == "pref":
            return self.pref
        if level == "town":
            return f"{self.pref}{self.city}{self.town}"
        return f"{self.pref}{self.city}"


def _load_muni_table() -> dict:
    with open(_MUNI_PATH, encoding="utf-8") as f:
        return json.load(f)


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    dy = (lat2 - lat1) * 111320.0
    dx = (lon2 - lon1) * 111320.0 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


class OfflineMuniLookup:
    """同梱境界データによる市区町村の点内判定(インターネット不要).

    TopoJSON(量子化デルタ符号)を展開し、0.2度グリッドの
    バウンディングボックス索引 + 偶奇則レイキャスティングで判定する。
    1回の判定は数十μs〜数百μsで毎秒問い合わせには十分。
    """

    CELL = 0.2  # グリッドセルサイズ[度]

    def __init__(self, path: Path = _BOUNDARY_PATH):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            d = json.load(f)
        sx, sy = d["transform"]["scale"]
        tx, ty = d["transform"]["translate"]

        # アークを座標列に展開
        arcs = []
        for arc in d["arcs"]:
            n = len(arc)
            xs = [0.0] * n
            ys = [0.0] * n
            x = y = 0
            for i, (dx, dy) in enumerate(arc):
                x += dx
                y += dy
                xs[i] = x * sx + tx
                ys[i] = y * sy + ty
            arcs.append((xs, ys))

        def build_ring(arc_ids):
            rx: list[float] = []
            ry: list[float] = []
            for aid in arc_ids:
                if aid >= 0:
                    xs, ys = arcs[aid]
                else:
                    xs, ys = arcs[~aid]
                    xs, ys = xs[::-1], ys[::-1]
                if rx:  # 連結点の重複を除去
                    rx.extend(xs[1:])
                    ry.extend(ys[1:])
                else:
                    rx.extend(xs)
                    ry.extend(ys)
            return rx, ry

        # 自治体ごとに全リング(外周+穴。偶奇則なので区別不要)を保持
        self._geoms: list[tuple[str, list, tuple]] = []  # (muniCd, rings, bbox)
        for g in d["geoms"]:
            if g["t"] == "M":  # MultiPolygon: ポリゴン列→リング列に平坦化
                ring_sets = [r for poly in g["a"] for r in poly]
            else:              # Polygon
                ring_sets = g["a"]
            rings = [build_ring(r) for r in ring_sets]
            xmin = min(min(r[0]) for r in rings)
            xmax = max(max(r[0]) for r in rings)
            ymin = min(min(r[1]) for r in rings)
            ymax = max(max(r[1]) for r in rings)
            self._geoms.append((g["c"], rings, (xmin, ymin, xmax, ymax)))

        # グリッド索引
        self._grid: dict[tuple[int, int], list[int]] = {}
        for i, (_, _, bb) in enumerate(self._geoms):
            for cx in range(int(bb[0] / self.CELL), int(bb[2] / self.CELL) + 1):
                for cy in range(int(bb[1] / self.CELL), int(bb[3] / self.CELL) + 1):
                    self._grid.setdefault((cx, cy), []).append(i)

    @staticmethod
    def _point_in_rings(lon: float, lat: float, rings) -> bool:
        inside = False
        for xs, ys in rings:
            n = len(xs)
            j = n - 1
            for i in range(n):
                if (ys[i] > lat) != (ys[j] > lat):
                    xcross = (xs[j] - xs[i]) * (lat - ys[i]) / (ys[j] - ys[i]) + xs[i]
                    if lon < xcross:
                        inside = not inside
                j = i
        return inside

    def lookup_cd(self, lat: float, lon: float) -> Optional[str]:
        """市区町村コードを返す(該当なし=海上等はNone)."""
        cell = (int(lon / self.CELL), int(lat / self.CELL))
        for i in self._grid.get(cell, ()):
            cd, rings, bb = self._geoms[i]
            if bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]:
                if self._point_in_rings(lon, lat, rings):
                    return cd
        return None


class ReverseGeocoder:
    """同期版逆ジオコーダ(キャッシュ・間引き付き).

    mode="offline"(既定)ならインターネット不要で市区町村まで解決する。
    """

    def __init__(self, min_move_m: float = 150.0, min_interval_s: float = 1.0,
                 timeout_s: float = 3.0, mode: str = "offline"):
        self._muni = _load_muni_table()
        self.mode = mode
        self._offline: Optional[OfflineMuniLookup] = None
        if mode in ("offline", "auto"):
            try:
                self._offline = OfflineMuniLookup()
            except Exception:
                if mode == "offline":
                    raise
                self._offline = None  # autoはAPIにフォールバック
        self.min_move_m = min_move_m
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self._last_pos: Optional[tuple[float, float]] = None
        self._last_time = 0.0
        self.current: Optional[Address] = None
        self.error_count = 0

    def muni_name(self, muni_cd: str) -> Optional[tuple[str, str]]:
        e = self._muni.get(str(int(muni_cd))) if muni_cd else None
        return (e[0], e[1]) if e else None

    def _query(self, lat: float, lon: float) -> Optional[Address]:
        q = urllib.parse.urlencode({"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"})
        req = urllib.request.Request(f"{API_URL}?{q}",
                                     headers={"User-Agent": "heli-gps-decoder"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            data = json.loads(r.read().decode("utf-8"))
        res = data.get("results") or {}
        muni_cd = res.get("muniCd", "")
        if not muni_cd:
            return None  # 海上など住所なし
        names = self.muni_name(muni_cd)
        if names is None:
            return None
        return Address(pref=names[0], city=names[1],
                       town=res.get("lv01Nm") or "", muni_cd=muni_cd)

    def _lookup_offline(self, lat: float, lon: float) -> Optional[Address]:
        cd = self._offline.lookup_cd(lat, lon)
        if cd is None:
            return None
        names = self.muni_name(cd)
        if names is None:
            return None
        return Address(pref=names[0], city=names[1], town="", muni_cd=cd)

    def lookup(self, lat: float, lon: float, force: bool = False) -> Optional[Address]:
        """位置に対応する住所を返す(間引き条件内なら前回値をそのまま返す)."""
        now = time.monotonic()
        if not force and self._last_pos is not None:
            if (now - self._last_time < self.min_interval_s or
                    _dist_m(*self._last_pos, lat, lon) < self.min_move_m):
                return self.current

        addr: Optional[Address] = None
        if self._offline is not None:
            addr = self._lookup_offline(lat, lon)  # ネット不要・即時

        if self.mode in ("online", "auto"):
            # onlineは全解決をAPIで、autoは町丁目の補完・海上境界の補正に使う
            try:
                api = self._query(lat, lon)
                if api is not None:
                    if addr is not None and api.muni_cd == addr.muni_cd:
                        addr = api
                    elif addr is None:
                        addr = api
            except Exception:
                self.error_count += 1
                if self.mode == "online":
                    return self.current  # 通信断は前回値を保持

        self._last_pos = (lat, lon)
        self._last_time = now
        if addr is not None:
            self.current = addr
        return self.current


class AsyncReverseGeocoder:
    """非同期版: submit()で最新位置を渡すとバックグラウンドで解決し、
    .current に反映する。復調スレッドやGUIをブロックしない。"""

    def __init__(self, **kwargs):
        self._geo = ReverseGeocoder(**kwargs)
        self._pending: Optional[tuple[float, float]] = None
        self._cv = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def current(self) -> Optional[Address]:
        return self._geo.current

    @property
    def error_count(self) -> int:
        return self._geo.error_count

    def submit(self, lat: float, lon: float) -> None:
        with self._cv:
            self._pending = (lat, lon)
            self._cv.notify()

    def close(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._pending is None and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                lat, lon = self._pending
                self._pending = None
            self._geo.lookup(lat, lon)
