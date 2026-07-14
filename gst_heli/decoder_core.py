"""復調→住所→テロップ文字列 の中核ロジック(入出力非依存・テスト可能).

音声サンプル(mono float)を feed() すると、GPS復調・住所変換を行い、
現在表示すべきスーパー文字列を current_text() で返す。
GStreamer/ファイルどちらの音源からも同じように使える。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from nnn_decoder.geocode import AsyncReverseGeocoder
from nnn_decoder.pipeline import DecoderPipeline


@dataclass
class HeliConfig:
    fs: float = 48000.0
    baud: int = 1200
    channel: int = 2            # EMB音声のGPSチャンネル(0始まり)
    geo_mode: str = "offline"   # offline/auto/online
    addr_level: str = "muni"    # pref/muni/city/town
    text_format: str = "{address}上空"
    stale_text: str = ""        # 受信途絶時の表示(空=消す)
    stale_timeout: float = 5.0


class HeliDecoder:
    """音声→スーパー文字列。スレッドセーフ。"""

    def __init__(self, cfg: HeliConfig):
        self.cfg = cfg
        self._pipe = DecoderPipeline(cfg.fs, baud=cfg.baud)
        self._geo = AsyncReverseGeocoder(mode=cfg.geo_mode)
        self._lock = threading.Lock()
        self._last_pkt = None
        self._last_time = 0.0
        self.packets_ok = 0

    def feed(self, mono: np.ndarray) -> None:
        """1チャンネルぶんの音声サンプル(float)を投入."""
        for pkt in self._pipe.process(np.asarray(mono, dtype=np.float64)):
            with self._lock:
                self._last_pkt = pkt
                self._last_time = time.monotonic()
                self.packets_ok += 1
            self._geo.submit(pkt.lat_wgs84, pkt.lon_wgs84)

    def feed_interleaved(self, inter: np.ndarray, nchan: int) -> None:
        """インターリーブ音声(1次元)からGPSチャンネルを抜いて投入."""
        if nchan <= 1:
            self.feed(inter)
            return
        ch = min(self.cfg.channel, nchan - 1)
        self.feed(inter[ch::nchan])

    def _is_stale(self) -> bool:
        if self._last_pkt is None:
            return True
        return (time.monotonic() - self._last_time) > self.cfg.stale_timeout

    def current_text(self) -> str:
        """今表示すべきスーパー文字列."""
        with self._lock:
            pkt = self._last_pkt
            stale = self._is_stale()
        if pkt is None or stale:
            return self.cfg.stale_text
        addr = self._geo.current
        addr_s = addr.text(self.cfg.addr_level) if addr else ""
        try:
            return self.cfg.text_format.format(
                address=addr_s,
                alt=f"{pkt.alt_m:.0f}",
                lat=f"{pkt.lat_wgs84:.5f}",
                lon=f"{pkt.lon_wgs84:.5f}",
                sats=pkt.satellites if pkt.satellites is not None else "-",
            )
        except Exception:
            return addr_s

    def status(self) -> dict:
        with self._lock:
            pkt = self._last_pkt
            age = (time.monotonic() - self._last_time) if pkt else 1e9
        addr = self._geo.current
        return {
            "receiving": pkt is not None and age < self.cfg.stale_timeout,
            "lat": pkt.lat_wgs84 if pkt else None,
            "lon": pkt.lon_wgs84 if pkt else None,
            "alt": pkt.alt_m if pkt else None,
            "fix": pkt.fix_status if pkt else None,
            "sats": pkt.satellites if pkt else None,
            "address": addr.text(self.cfg.addr_level) if addr else None,
            "packets_ok": self.packets_ok,
        }

    def close(self) -> None:
        self._geo.close()
