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
    datum: str = "wgs84"        # 生座標の測地系(wgs84=変換なし / tokyo=変換)
    geo_mode: str = "offline"   # offline/auto/online
    addr_level: str = "muni"    # pref/muni/city/citygun/town
    # 住所の見せ方。既定は従来どおり「千葉県鴨川市上空」。
    #   drop_pref_suffix/drop_muni_suffix/addr_sep を組み合わせると
    #   「千葉・鴨川上空」のような表記にできる。
    # 既定は「千葉・鴨川市上空」。
    #   都道府県の接尾辞は省くが、市区町村の接尾辞は**残す**。
    # 従来形(千葉県鴨川市上空)に戻すには drop_pref_suffix を False、
    # addr_sep を "" にする。
    drop_pref_suffix: bool = True    # 「千葉県」→「千葉」
    drop_muni_suffix: bool = False   # 「鴨川市」→「鴨川」(既定は省かない)
    addr_sep: str = "・"             # 都道府県と市区町村の区切り
    offshore_suffix: str = "沖"      # 海上のときに付ける語("沖"/"沿岸"/空=なし)
    addr_suffix: str = "上空"        # 末尾に付ける語
    addr_suffix_on: bool = True      # 末尾の語を付けるか
    # 海上(沖/沿岸)のときは末尾の語を付けない。
    # 「茨城・鹿嶋沿岸上空」→「茨城・鹿嶋沿岸」のように重複を避ける。
    offshore_drop_suffix: bool = False
    text_format: str = "{address}{suffix}"
    stale_text: str = ""        # 受信途絶時の表示(空=消す)
    stale_timeout: float = 5.0  # これを超えたら「受信中」ではないと判定
    # 受信が途切れても直近スーパーを保持する秒数(音声の瞬断でテロップが
    # 消えないようにする)。この時間を過ぎたら stale_text に切り替える。
    hold_timeout: float = 15.0


class HeliDecoder:
    """音声→スーパー文字列。スレッドセーフ。"""

    def __init__(self, cfg: HeliConfig):
        self.cfg = cfg
        self._pipe = DecoderPipeline(cfg.fs, baud=cfg.baud, datum=cfg.datum)
        self._geo = AsyncReverseGeocoder(mode=cfg.geo_mode)
        self._lock = threading.Lock()
        self._last_pkt = None
        self._last_time = 0.0
        self.packets_ok = 0
        # 直近に表示した非空スーパー(瞬断時の保持用)
        self._held_text = ""
        self._held_time = 0.0

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

    def address_text(self) -> str:
        """住所部分だけの文字列(末尾の「上空」等は付けない)."""
        addr = self._geo.current
        if not addr:
            return ""
        c = self.cfg
        return addr.text(c.addr_level, c.offshore_suffix,
                         drop_pref_suffix=c.drop_pref_suffix,
                         drop_muni_suffix=c.drop_muni_suffix,
                         sep=c.addr_sep)

    def _is_offshore(self) -> bool:
        a = self._geo.current
        return bool(a and a.offshore)

    def _format(self, pkt) -> str:
        addr_s = self.address_text()
        if not addr_s:
            return ""
        c = self.cfg
        suffix = c.addr_suffix if c.addr_suffix_on else ""
        # 海上では「沖」「沿岸」が既に付いているので、末尾の語を外せる
        if suffix and c.offshore_drop_suffix and self._is_offshore():
            suffix = ""
        try:
            return c.text_format.format(
                address=addr_s,
                suffix=suffix,
                alt=f"{pkt.alt_m:.0f}",
                lat=f"{pkt.lat_wgs84:.5f}",
                lon=f"{pkt.lon_wgs84:.5f}",
                sats=pkt.satellites if pkt.satellites is not None else "-",
            )
        except Exception:
            return addr_s + suffix

    def current_text(self) -> str:
        """今表示すべきスーパー文字列.

        受信中は最新の住所を表示。受信が途切れても hold_timeout 以内なら
        直近スーパーを保持し、音声の瞬断でテロップが消えないようにする。
        """
        now = time.monotonic()
        with self._lock:
            pkt = self._last_pkt
            stale = self._is_stale()
        if pkt is not None and not stale:
            text = self._format(pkt)
            if text:
                self._held_text = text
                self._held_time = now
            return text
        # 受信途絶: 直近スーパーを一定時間だけ保持(瞬断対策)
        if self._held_text and (now - self._held_time) <= self.cfg.hold_timeout:
            return self._held_text
        return self.cfg.stale_text

    def status(self) -> dict:
        with self._lock:
            pkt = self._last_pkt
            age = (time.monotonic() - self._last_time) if pkt else 1e9
        return {
            "receiving": pkt is not None and age < self.cfg.stale_timeout,
            "lat": pkt.lat_wgs84 if pkt else None,
            "lon": pkt.lon_wgs84 if pkt else None,
            # 生の東京測地系(NNNのDDMMSSそのまま)。他システムとの照合用。
            "lat_tokyo": pkt.lat_tokyo if pkt else None,
            "lon_tokyo": pkt.lon_tokyo if pkt else None,
            "alt": pkt.alt_m if pkt else None,
            "fix": pkt.fix_status if pkt else None,
            "sats": pkt.satellites if pkt else None,
            "address": self.address_text() or None,
            "packets_ok": self.packets_ok,
        }

    def boundary_lookup(self):
        """住所判定に使っている境界データを返す(地図描画で再利用).

        同じデータを二重に読み込まないため。オンラインモード等で
        オフラインデータを持たない場合は None。
        """
        try:
            return self._geo.offline
        except Exception:
            return None

    def close(self) -> None:
        self._geo.close()
