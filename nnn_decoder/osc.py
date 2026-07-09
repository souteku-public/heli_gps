"""OSC (Open Sound Control) 送出.

TouchDesigner等の映像ソフトへ、復調した位置と住所をUDP/OSCで渡す。
依存ライブラリなしの最小実装(送信のみ)。

送出アドレス(既定 127.0.0.1:9000):
    /heli/position  (fff)  lat_wgs84, lon_wgs84, alt_m
    /heli/address   (s)    表示用住所文字列 (例 "千葉県千葉市美浜区")
    /heli/status    (iis)  fix_status, satellites, station_id
"""

from __future__ import annotations

import socket
import struct

from .packet import NNNPacket


def _pad4(b: bytes) -> bytes:
    return b + b"\x00" * ((4 - len(b) % 4) % 4)


def _osc_str(s: str) -> bytes:
    b = s.encode("utf-8") + b"\x00"
    return _pad4(b)


def osc_message(address: str, *args) -> bytes:
    """OSCメッセージをエンコード. 対応型: int, float, str."""
    tags = ","
    payload = b""
    for a in args:
        if isinstance(a, bool):
            a = int(a)
        if isinstance(a, int):
            tags += "i"
            payload += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"
            payload += struct.pack(">f", a)
        elif isinstance(a, str):
            tags += "s"
            payload += _osc_str(a)
        else:
            raise TypeError(f"OSC未対応型: {type(a)}")
    return _osc_str(address) + _osc_str(tags) + payload


class OscSender:
    """位置・住所をOSCで送出する."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000):
        self.addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_packet(self, pkt: NNNPacket, address_text: str = "") -> None:
        self._sock.sendto(
            osc_message("/heli/position",
                        float(pkt.lat_wgs84), float(pkt.lon_wgs84), float(pkt.alt_m)),
            self.addr)
        if address_text:
            self._sock.sendto(osc_message("/heli/address", address_text), self.addr)
        self._sock.sendto(
            osc_message("/heli/status", int(pkt.fix_status),
                        int(pkt.satellites if pkt.satellites is not None else -1),
                        pkt.station_id),
            self.addr)

    def close(self) -> None:
        self._sock.close()
