"""NNN系列統一フォーマット パケットパーサ.

データ構成:
    Dummy(55h)×3 | STX(02h) | ID(2byte) | DATA(20byte) | ETX(03h) | BCC(1byte)

    BCC: IDからETXまでのXOR(水平パリティ)

DATA部(20byte, すべてASCII):
    ステータス 4byte | 緯度 6byte | 経度 7byte | 高度 3byte

    ステータス1byte目: 測位状態 0=正常 / 1=バックアップ(前回値) / 2=使用不能
    ステータス2byte目: リザーブ(20h)
    ステータス3byte目: PDOP値 1〜F(16進), 値なし=0
    ステータス4byte目: 受信衛星数 0〜9, データなし=F
    緯度: 10進6桁 DDMMSS (354027 → 北緯35度40分27秒)
    経度: 10進7桁 DDDMMSS (1354027 → 東経135度40分27秒)
    高度: 10進3桁 ×10m (012 → 120m)

測地系は東京測地系。有効範囲: 北緯20〜50度, 東経120〜150度, 高度0〜4000m。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .geodesy import dms_to_deg, tokyo_to_wgs84

STX = 0x02
ETX = 0x03
DATA_LEN = 20
# STX後: ID(2) + DATA(20) + ETX(1) + BCC(1)
FRAME_LEN_AFTER_STX = 2 + DATA_LEN + 1 + 1

FIX_STATUS = {
    0: "正常測位",
    1: "バックアップ(前回測位値)",
    2: "使用不能",
}


@dataclass
class NNNPacket:
    """デコード済みNNNパケット."""

    station_id: str            # ID 2byteのASCII表現 (例 "01")
    fix_status: int            # 0/1/2
    pdop: Optional[int]        # 1〜15, 不明はNone
    satellites: Optional[int]  # 0〜9, 不明はNone
    lat_tokyo: float           # 東京測地系 緯度[度]
    lon_tokyo: float           # 東京測地系 経度[度]
    alt_m: float               # 高度[m]
    lat_wgs84: float = field(init=False)
    lon_wgs84: float = field(init=False)
    raw: bytes = b""
    in_range: bool = True      # 仕様の有効範囲内か

    def __post_init__(self):
        self.lat_wgs84, self.lon_wgs84 = tokyo_to_wgs84(self.lat_tokyo, self.lon_tokyo)

    @property
    def fix_status_text(self) -> str:
        return FIX_STATUS.get(self.fix_status, f"不明({self.fix_status})")

    def __str__(self) -> str:
        return (
            f"ID={self.station_id} {self.fix_status_text} "
            f"緯度={self.lat_wgs84:.6f} 経度={self.lon_wgs84:.6f} (WGS84) "
            f"高度={self.alt_m:.0f}m PDOP={self.pdop} 衛星={self.satellites}"
        )


class ParseError(Exception):
    pass


def _parse_data(station_id_bytes: bytes, data: bytes, raw: bytes) -> NNNPacket:
    status = data[0:4]
    lat_s = data[4:10]
    lon_s = data[10:17]
    alt_s = data[17:20]

    try:
        fix_status = int(chr(status[0]))
    except ValueError:
        raise ParseError(f"測位状態が不正: {status[0]:#x}")
    if fix_status not in (0, 1, 2):
        raise ParseError(f"測位状態が範囲外: {fix_status}")

    pdop_c = chr(status[2]).upper()
    if pdop_c == "0":
        pdop = None
    else:
        try:
            pdop = int(pdop_c, 16)
        except ValueError:
            raise ParseError(f"PDOPが不正: {pdop_c!r}")

    sat_c = chr(status[3]).upper()
    if sat_c == "F":
        satellites = None
    elif sat_c.isdigit():
        satellites = int(sat_c)
    else:
        raise ParseError(f"衛星数が不正: {sat_c!r}")

    if not (lat_s.isdigit() and lon_s.isdigit() and alt_s.isdigit()):
        raise ParseError(f"座標データが数字でない: {lat_s!r} {lon_s!r} {alt_s!r}")

    lat = dms_to_deg(lat_s.decode())
    lon = dms_to_deg(lon_s.decode())
    alt = int(alt_s.decode()) * 10.0

    in_range = (20.0 <= lat <= 50.0) and (120.0 <= lon <= 150.0) and (0.0 <= alt <= 4000.0)

    sid = station_id_bytes.decode("ascii", errors="replace")

    return NNNPacket(
        station_id=sid,
        fix_status=fix_status,
        pdop=pdop,
        satellites=satellites,
        lat_tokyo=lat,
        lon_tokyo=lon,
        alt_m=alt,
        raw=raw,
        in_range=in_range,
    )


class NNNPacketParser:
    """バイトストリームからNNNパケットを抽出するストリーミングパーサ.

    仕様書8項に従い、BCCエラー・パリティエラー時は当該データを無効とし
    前回の正常データを保持する(last_good)。
    """

    def __init__(self):
        self._buf = bytearray()
        self.packets_ok = 0
        self.packets_error = 0
        self.last_good: Optional[NNNPacket] = None
        self.last_error: Optional[str] = None

    def feed(self, data: bytes) -> list[NNNPacket]:
        """バイト列を追加し、完成したパケットのリストを返す."""
        self._buf.extend(data)
        out: list[NNNPacket] = []
        while True:
            idx = self._buf.find(STX)
            if idx < 0:
                # STXなし: ダミー(55h)等は捨てる
                self._buf.clear()
                break
            if idx > 0:
                del self._buf[:idx]
            if len(self._buf) < 1 + FRAME_LEN_AFTER_STX:
                break  # データ待ち

            frame = bytes(self._buf[: 1 + FRAME_LEN_AFTER_STX])
            body = frame[1:]  # ID..BCC
            etx = body[2 + DATA_LEN]
            bcc = body[2 + DATA_LEN + 1]

            if etx != ETX:
                # フレーム不成立 → このSTXを捨てて次を探す
                self.packets_error += 1
                self.last_error = "ETX不一致"
                del self._buf[0]
                continue

            calc = 0
            for b in body[: 2 + DATA_LEN + 1]:  # ID〜ETX
                calc ^= b
            calc &= 0x7F  # 7bit伝送のためBCCも7bit
            if calc != (bcc & 0x7F):
                self.packets_error += 1
                self.last_error = f"BCC不一致 (受信={bcc:#04x} 計算={calc:#04x})"
                del self._buf[0]
                continue

            try:
                pkt = _parse_data(body[0:2], body[2 : 2 + DATA_LEN], frame)
            except ParseError as e:
                self.packets_error += 1
                self.last_error = str(e)
                del self._buf[0]
                continue

            del self._buf[: 1 + FRAME_LEN_AFTER_STX]
            self.packets_ok += 1
            self.last_good = pkt
            out.append(pkt)
        return out
