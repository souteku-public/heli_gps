"""NNNフォーマット MSK変調器(GPSエンコーダ・シミュレータ).

実機がなくても復調系の試験ができるように、仕様書どおりの
パケット生成とMSK音声波形の生成を行う。
"""

from __future__ import annotations

import numpy as np

from .demod import TONES
from .packet import STX, ETX


def make_data_field(
    fix_status: int,
    pdop: int | None,
    satellites: int | None,
    lat_dms: str,
    lon_dms: str,
    alt_m: int,
) -> bytes:
    """DATA部(20byte)を生成. lat_dms='DDMMSS', lon_dms='DDDMMSS'."""
    if len(lat_dms) != 6 or len(lon_dms) != 7:
        raise ValueError("緯度は6桁, 経度は7桁で指定してください")
    pdop_c = "0" if pdop is None else format(min(pdop, 15), "X")
    sat_c = "F" if satellites is None else str(min(satellites, 9))
    alt_s = format(int(alt_m) // 10, "03d")
    s = f"{fix_status}\x20{pdop_c}{sat_c}{lat_dms}{lon_dms}{alt_s}"
    data = s.encode("ascii")
    assert len(data) == 20
    return data


def make_frame(station_id: str, data: bytes) -> bytes:
    """Dummy×3 + STX + ID + DATA + ETX + BCC のフレームを生成."""
    if len(station_id) != 2:
        raise ValueError("IDは2文字で指定してください (例 '01')")
    body = station_id.encode("ascii") + data + bytes([ETX])
    bcc = 0
    for b in body:
        bcc ^= b
    bcc &= 0x7F
    return bytes([0x55, 0x55, 0x55, STX]) + body + bytes([bcc])


def bytes_to_uart_bits(data: bytes, idle_bits: int = 8) -> list[int]:
    """バイト列を調歩同期(1start + 7data LSBファースト + 偶数パリティ + 1stop)のビット列へ."""
    bits: list[int] = [1] * idle_bits
    for byte in data:
        b7 = byte & 0x7F
        parity = bin(b7).count("1") & 1  # 偶数パリティ
        bits.append(0)  # start
        for i in range(7):
            bits.append((b7 >> i) & 1)
        bits.append(parity)
        bits.append(1)  # stop
    bits.extend([1] * idle_bits)
    return bits


def msk_modulate(
    bits: list[int],
    fs: float,
    baud: int = 1200,
    amplitude: float = 0.5,
    f_mark: float | None = None,
    f_space: float | None = None,
) -> np.ndarray:
    """ビット列を連続位相FSK(MSK)音声波形に変換."""
    if f_mark is None or f_space is None:
        f_mark, f_space = TONES[baud]
    spb = fs / baud
    phase = 0.0
    out = np.zeros(int(np.ceil(len(bits) * spb)), dtype=np.float64)
    idx = 0
    t_edge = 0.0
    for bit in bits:
        f = f_mark if bit else f_space
        t_edge += spb
        n = int(round(t_edge)) - idx
        dph = 2.0 * np.pi * f / fs
        ph = phase + dph * np.arange(1, n + 1)
        out[idx : idx + n] = amplitude * np.sin(ph)
        phase = ph[-1] % (2.0 * np.pi) if n > 0 else phase
        idx += n
    return out[:idx]


def write_test_wav(
    path: str,
    fs: int = 48000,
    baud: int = 1200,
    seconds: int = 10,
    stereo: bool = True,
) -> None:
    """動作確認用のテストWAVを生成(毎秒1パケット、緯度が1秒ずつ進む)."""
    import wave

    parts = []
    for i in range(seconds):
        sec = 20 + (i % 40)
        a = encode_position_to_audio(
            fs, baud=baud, lat_dms=f"3540{sec:02d}", lon_dms="1394510",
            alt_m=500 + 10 * i)
        pad = np.zeros(max(0, fs - len(a)))
        parts += [a, pad]
    x = np.concatenate(parts)
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)
    if stereo:
        pcm = np.column_stack([pcm, np.zeros_like(pcm)])  # GPS音声はLch
    with wave.open(path, "wb") as w:
        w.setnchannels(2 if stereo else 1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm.tobytes())


def _main():
    import argparse

    ap = argparse.ArgumentParser(description="NNNフォーマット テスト音声WAV生成")
    ap.add_argument("out", help="出力WAVファイル")
    ap.add_argument("--baud", type=int, default=1200, choices=[1200, 2400])
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--mono", action="store_true")
    args = ap.parse_args()
    write_test_wav(args.out, baud=args.baud, seconds=args.seconds,
                   stereo=not args.mono)
    print(f"生成: {args.out} ({args.seconds}秒, {args.baud}bps)")


def encode_position_to_audio(
    fs: float,
    baud: int = 1200,
    station_id: str = "01",
    fix_status: int = 0,
    pdop: int | None = 2,
    satellites: int | None = 8,
    lat_dms: str = "354027",
    lon_dms: str = "1394510",
    alt_m: int = 500,
    amplitude: float = 0.5,
) -> np.ndarray:
    """位置1点ぶんのNNNフレームをMSK音声波形として生成."""
    data = make_data_field(fix_status, pdop, satellites, lat_dms, lon_dms, alt_m)
    frame = make_frame(station_id, data)
    bits = bytes_to_uart_bits(frame)
    return msk_modulate(bits, fs, baud, amplitude)


if __name__ == "__main__":
    _main()
