"""逆ジオコーディング(緯度経度 → 住所).

国土地理院の逆ジオコーダAPIを使用し、市区町村コードを
同梱の市区町村テーブル(data/muni.json, 出典: 地理院地図 muni.js)で
名称に変換する。

- API: https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress
- 呼び出しは移動距離としきい時間で間引き(ヘリ毎秒1点でも実質は
  境界を越える前後でしか問い合わせない)
- ネットワーク断のときは前回結果を保持して運用を継続する
"""

from __future__ import annotations

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


class ReverseGeocoder:
    """同期版逆ジオコーダ(キャッシュ・間引き付き)."""

    def __init__(self, min_move_m: float = 150.0, min_interval_s: float = 1.0,
                 timeout_s: float = 3.0):
        self._muni = _load_muni_table()
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

    def lookup(self, lat: float, lon: float, force: bool = False) -> Optional[Address]:
        """位置に対応する住所を返す(間引き条件内なら前回値をそのまま返す)."""
        now = time.monotonic()
        if not force and self._last_pos is not None:
            if (now - self._last_time < self.min_interval_s or
                    _dist_m(*self._last_pos, lat, lon) < self.min_move_m):
                return self.current
        try:
            addr = self._query(lat, lon)
        except Exception:
            self.error_count += 1
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
