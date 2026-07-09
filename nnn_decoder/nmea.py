"""NMEA 0183 出力.

復調した位置をGGA/RMCセンテンスに変換し、UDP送出する。
地図ソフト(OpenCPN, gpsd, カーナビアプリ等)にそのまま食わせられる。
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone

from .packet import NNNPacket


def _checksum(body: str) -> str:
    cs = 0
    for c in body:
        cs ^= ord(c)
    return f"{cs:02X}"


def _fmt_lat(lat: float) -> tuple[str, str]:
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    d = int(lat)
    m = (lat - d) * 60.0
    return f"{d:02d}{m:07.4f}", hemi


def _fmt_lon(lon: float) -> tuple[str, str]:
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    d = int(lon)
    m = (lon - d) * 60.0
    return f"{d:03d}{m:07.4f}", hemi


def packet_to_gga(pkt: NNNPacket, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    t = when.strftime("%H%M%S.00")
    lat, ns = _fmt_lat(pkt.lat_wgs84)
    lon, ew = _fmt_lon(pkt.lon_wgs84)
    quality = 1 if pkt.fix_status == 0 else (6 if pkt.fix_status == 1 else 0)
    nsat = pkt.satellites if pkt.satellites is not None else 0
    hdop = f"{float(pkt.pdop):.1f}" if pkt.pdop is not None else ""
    body = (
        f"GPGGA,{t},{lat},{ns},{lon},{ew},{quality},{nsat:02d},{hdop},"
        f"{pkt.alt_m:.1f},M,,M,,"
    )
    return f"${body}*{_checksum(body)}\r\n"


def packet_to_rmc(pkt: NNNPacket, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    t = when.strftime("%H%M%S.00")
    d = when.strftime("%d%m%y")
    lat, ns = _fmt_lat(pkt.lat_wgs84)
    lon, ew = _fmt_lon(pkt.lon_wgs84)
    status = "A" if pkt.fix_status in (0, 1) else "V"
    body = f"GPRMC,{t},{status},{lat},{ns},{lon},{ew},,,{d},,,A"
    return f"${body}*{_checksum(body)}\r\n"


class NmeaUdpSender:
    """NMEAセンテンスをUDPで送出する(既定 127.0.0.1:10110)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 10110):
        self.addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, pkt: NNNPacket) -> None:
        payload = (packet_to_gga(pkt) + packet_to_rmc(pkt)).encode("ascii")
        self._sock.sendto(payload, self.addr)

    def close(self) -> None:
        self._sock.close()
