"""測地系変換・座標ユーティリティ.

NNNフォーマットの座標は東京測地系(Tokyo Datum)の度分秒。
地図表示(Google Maps等)にはWGS84(世界測地系)へ変換して使う。
"""

from __future__ import annotations


def dms_to_deg(s: str) -> float:
    """固定長DMS文字列を10進度に変換.

    緯度 "DDMMSS" (354027 → 35°40'27") / 経度 "DDDMMSS" (1354027 → 135°40'27")
    """
    s = s.strip()
    if len(s) == 6:
        d, m, sec = int(s[0:2]), int(s[2:4]), int(s[4:6])
    elif len(s) == 7:
        d, m, sec = int(s[0:3]), int(s[3:5]), int(s[5:7])
    else:
        raise ValueError(f"DMS文字列長が不正: {s!r}")
    return d + m / 60.0 + sec / 3600.0


def deg_to_dms_str(deg: float) -> str:
    """10進度を「D°M'S"」表記に変換(表示用)."""
    d = int(deg)
    m_f = (deg - d) * 60.0
    m = int(m_f)
    s = (m_f - m) * 60.0
    return f"{d}°{m:02d}'{s:04.1f}\""


def tokyo_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """東京測地系 → WGS84(世界測地系) 近似変換(単位: 度).

    国土地理院の1次式による標準的な近似(誤差は数m程度で、
    本用途(1秒≒30m分解能のヘリ位置把握)には十分)。
    """
    lat_w = lat - 0.00010695 * lat + 0.000017464 * lon + 0.0046017
    lon_w = lon - 0.000046038 * lat - 0.000083043 * lon + 0.010040
    return lat_w, lon_w


def wgs84_to_tokyo(lat: float, lon: float) -> tuple[float, float]:
    """WGS84 → 東京測地系 近似変換(テスト・逆変換用)."""
    lat_t = lat + 0.00010696 * lat - 0.000017467 * lon - 0.0046020
    lon_t = lon + 0.000046047 * lat + 0.000083049 * lon - 0.010041
    return lat_t, lon_t
