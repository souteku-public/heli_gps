"""映像出力だけの単体テスト(段階的な立ち上げ用).

Pythonが「実際のテロップ静止画」をTCPで供給し、gst-launchが
それをFill&KeyでSDI出力する。音声・復調は使わない。
Python→gst→SDI出力(Fill&Key) の経路だけを検証する。

    python -m gst_heli.outtest --text "テスト 千葉県君津市上空"

REF INに同期信号を接続し、SDI OUTをモニタ/スイッチャーで確認する。
Ctrl+Cで終了。
"""

from __future__ import annotations

import argparse

from .gst_subprocess import GstSubprocessBridge
from .renderer import SuperRenderer, SuperStyle


def main():
    ap = argparse.ArgumentParser(description="Fill&Key出力の単体テスト")
    ap.add_argument("--text", default="テロップ出力テスト", help="表示する文字")
    ap.add_argument("--mode", default="1080i5994")
    ap.add_argument("--keyer", default="external", choices=["external", "internal", "off"])
    ap.add_argument("--out-device", type=int, default=0)
    ap.add_argument("--in-device", type=int, default=0)
    ap.add_argument("--vconnection", default="sdi")
    ap.add_argument("--vmode", default="auto")
    ap.add_argument("--no-interlace", action="store_true")
    ap.add_argument("--gst-bin", default=None)
    ap.add_argument("--with-audio-in", action="store_true",
                    help="映像入力+音声入力ブランチも動かす(本番同等の同時I/O確認)")
    args = ap.parse_args()

    renderer = SuperRenderer(1920, 1080, SuperStyle(font_size=90, stroke_width=6))
    frame = renderer.render(args.text)

    def provider():
        return frame

    def on_audio(arr, n):
        pass  # 出力テストでは音声は捨てる

    bridge = GstSubprocessBridge(
        provider, on_audio, out_device=args.out_device, in_device=args.in_device,
        mode=args.mode, keyer=args.keyer, vconnection=args.vconnection,
        vmode=args.vmode, gst_bin=args.gst_bin, interlace=not args.no_interlace)
    print(f"出力テスト開始: \"{args.text}\"  (Ctrl+Cで終了)")
    print("SDI OUT 1=Fill / 2=Key を確認してください。")
    bridge.start()
    try:
        bridge.wait()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
