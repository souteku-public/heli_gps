"""WAV/映像ファイルのオフラインデコードCLI.

使い方:
    python -m nnn_decoder.cli 録音.wav
    python -m nnn_decoder.cli 収録.mp4 --channel right --csv out.csv

WAV以外(MP4/TS/MXF/MOV等の映像ファイル)は ffmpeg で音声トラックを
抽出してから復調する(ffmpegがPATHにあること)。
キャプチャボードの収録素材からの位置ログ復元にそのまま使える。
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import struct
import subprocess
import sys
import tempfile

import numpy as np

from .geodesy import deg_to_dms_str
from .pipeline import DecoderPipeline


def extract_audio_with_ffmpeg(path: str, stream: int = 0) -> str:
    """映像ファイルから音声トラックをWAV(48kHz)に抽出し、一時ファイルパスを返す."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "WAV以外のファイルの読み込みには ffmpeg が必要です。\n"
            "https://ffmpeg.org/ からインストールしてPATHに追加してください。")
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    cmd = [ffmpeg, "-y", "-v", "error", "-i", path,
           "-map", f"0:a:{stream}", "-vn", "-acodec", "pcm_s16le",
           "-ar", "48000", tmp]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        os.unlink(tmp)
        raise RuntimeError(f"ffmpegによる音声抽出に失敗しました:\n{res.stderr.strip()}")
    return tmp


def _read_wav_raw(path: str) -> tuple[np.ndarray, int, int]:
    """WAVを読む(モノラル〜多チャンネル、PCM/float、EXTENSIBLE形式対応).

    標準waveモジュールは多チャンネルで使われるWAVE_FORMAT_EXTENSIBLE
    (VLCやffmpegの3ch以上出力)を読めないため自前でRIFFを解析する。
    戻り値: (インターリーブ生データ配列, チャンネル数, サンプリング周波数)
    """
    with open(path, "rb") as f:
        hdr = f.read(12)
        if len(hdr) < 12 or hdr[0:4] != b"RIFF" or hdr[8:12] != b"WAVE":
            raise ValueError(f"WAVファイルではありません: {path}")
        fmt = None
        data = None
        while True:
            ch = f.read(8)
            if len(ch) < 8:
                break
            cid, csz = struct.unpack("<4sI", ch)
            if cid == b"fmt ":
                fmt = f.read(csz)
            elif cid == b"data":
                data = f.read(csz)
            else:
                f.seek(csz, 1)
            if csz & 1:
                f.seek(1, 1)
        if fmt is None or data is None:
            raise ValueError("fmt/dataチャンクが見つかりません")
        tag, nch, fs, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
        if tag == 0xFFFE and len(fmt) >= 26:  # WAVE_FORMAT_EXTENSIBLE
            tag = struct.unpack("<H", fmt[24:26])[0]

        if tag == 1:  # 整数PCM
            if bits == 16:
                x = np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768.0
            elif bits == 24:
                b = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3)
                v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
                     | (b[:, 2].astype(np.int32) << 16))
                v = np.where(v >= 1 << 23, v - (1 << 24), v)
                x = v.astype(np.float64) / float(1 << 23)
            elif bits == 32:
                x = np.frombuffer(data, dtype="<i4").astype(np.float64) / 2147483648.0
            elif bits == 8:
                x = (np.frombuffer(data, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
            else:
                raise ValueError(f"未対応のPCMビット深度: {bits}bit")
        elif tag == 3:  # float PCM
            dtype = "<f4" if bits == 32 else "<f8"
            x = np.frombuffer(data, dtype=dtype).astype(np.float64)
        else:
            raise ValueError(f"未対応のWAVフォーマット (tag={tag:#x})")
        return x, nch, fs


def read_wav(path: str, channel: str) -> tuple[np.ndarray, int]:
    x, nch, fs = _read_wav_raw(path)
    if nch > 1:
        x = x.reshape(-1, nch)
        if channel == "mix":
            x = x.mean(axis=1)
        else:
            idx = {"left": 0, "right": 1}.get(channel)
            if idx is None:
                # 数字指定は1始まりのチャンネル番号 (例 "3" = 3ch目)
                idx = int(channel) - 1
                if not (0 <= idx < nch):
                    raise ValueError(
                        f"チャンネル{channel}は存在しません (このファイルは{nch}ch)")
            x = x[:, min(idx, nch - 1)]
    return x, fs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="NNNフォーマットGPS音声デコーダ (WAV/映像ファイル入力)")
    ap.add_argument("input", help="入力ファイル (WAV, またはMP4/TS/MXF等の映像)")
    ap.add_argument("--baud", type=int, default=1200, choices=[1200, 2400],
                    help="モデムビットレート (既定 1200)")
    ap.add_argument("--channel", default="left",
                    help="使用チャンネル: left / right / mix / チャンネル番号(1始まり, 例 3)"
                         " (既定 left)")
    ap.add_argument("--audio-stream", type=int, default=0,
                    help="映像ファイル内の音声トラック番号 (既定 0)")
    ap.add_argument("--invert", action="store_true", help="マーク/スペース反転")
    ap.add_argument("--csv", help="復調結果をCSVに保存")
    args = ap.parse_args(argv)

    tmp = None
    if not args.input.lower().endswith(".wav"):
        try:
            tmp = extract_audio_with_ffmpeg(args.input, args.audio_stream)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"音声トラック{args.audio_stream}を抽出しました", file=sys.stderr)
        wav_path = tmp
    else:
        wav_path = args.input

    try:
        x, fs = read_wav(wav_path, args.channel)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    finally:
        if tmp:
            os.unlink(tmp)
    pipe = DecoderPipeline(fs, baud=args.baud, invert=args.invert)

    rows = []
    block = int(fs)  # 1秒ずつ処理
    for i in range(0, len(x), block):
        for pkt in pipe.process(x[i : i + block]):
            t = i / fs
            print(
                f"[{t:7.2f}s] ID={pkt.station_id} {pkt.fix_status_text} "
                f"WGS84: {pkt.lat_wgs84:.6f}, {pkt.lon_wgs84:.6f} "
                f"({deg_to_dms_str(pkt.lat_wgs84)} / {deg_to_dms_str(pkt.lon_wgs84)}) "
                f"高度 {pkt.alt_m:.0f}m PDOP={pkt.pdop} 衛星={pkt.satellites}"
                + ("" if pkt.in_range else " [有効範囲外]")
            )
            rows.append([f"{t:.2f}", pkt.station_id, pkt.fix_status,
                         f"{pkt.lat_wgs84:.6f}", f"{pkt.lon_wgs84:.6f}",
                         f"{pkt.lat_tokyo:.6f}", f"{pkt.lon_tokyo:.6f}",
                         f"{pkt.alt_m:.0f}", pkt.pdop, pkt.satellites])

    s = pipe.stats
    print(f"--- 正常 {s['packets_ok']} / エラー {s['packets_error']} "
          f"(UART再同期 {s['uart_errors']}回 ※無信号区間の雑音を含む参考値)",
          file=sys.stderr)
    if s["packets_ok"] == 0 and s["last_error"]:
        print(f"最後のエラー: {s['last_error']}", file=sys.stderr)

    if args.csv and rows:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            wr.writerow(["time_s", "id", "fix_status", "lat_wgs84", "lon_wgs84",
                         "lat_tokyo", "lon_tokyo", "alt_m", "pdop", "satellites"])
            wr.writerows(rows)
        print(f"CSV保存: {args.csv}", file=sys.stderr)

    return 0 if s["packets_ok"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
