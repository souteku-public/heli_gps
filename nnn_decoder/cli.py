"""WAVファイル/録音のオフラインデコードCLI.

使い方:
    python -m nnn_decoder.cli 録音.wav
    python -m nnn_decoder.cli 録音.wav --baud 2400 --channel right --csv out.csv

キャプチャボードの音声を一度WAVに録音して動作確認する用途、
および過去の収録素材からの位置ログ復元に使える。
"""

from __future__ import annotations

import argparse
import csv
import sys
import wave

import numpy as np

from .geodesy import deg_to_dms_str
from .pipeline import DecoderPipeline


def read_wav(path: str, channel: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        fs = w.getframerate()
        nch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw == 2:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483648.0
    elif sw == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    else:
        raise ValueError(f"未対応のサンプル幅: {sw*8}bit")
    if nch > 1:
        x = x.reshape(-1, nch)
        idx = {"left": 0, "right": 1}.get(channel)
        if idx is None:  # mix
            x = x.mean(axis=1)
        else:
            x = x[:, min(idx, nch - 1)]
    return x, fs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NNNフォーマットGPS音声デコーダ (WAVファイル入力)")
    ap.add_argument("wav", help="入力WAVファイル")
    ap.add_argument("--baud", type=int, default=1200, choices=[1200, 2400],
                    help="モデムビットレート (既定 1200)")
    ap.add_argument("--channel", default="left", choices=["left", "right", "mix"],
                    help="使用チャンネル (既定 left)")
    ap.add_argument("--invert", action="store_true", help="マーク/スペース反転")
    ap.add_argument("--csv", help="復調結果をCSVに保存")
    args = ap.parse_args(argv)

    x, fs = read_wav(args.wav, args.channel)
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
