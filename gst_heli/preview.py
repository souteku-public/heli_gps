"""見た目確認用プレビュー: 入力SDI映像 + テロップ をPC窓に合成表示.

SDI出力はしない(REF不要)。入力映像に実際のテロップを重ねてPCの
ウィンドウに表示するので、control_ui.py でフォント/色/フチ/位置を
調整しながら仕上がりを確認できる。

    python -m gst_heli.preview --osc-control --channel 2
    python control_ui.py     (別ウィンドウで操作)

※ SDIデバイスは1プロセスしか入力を開けないため、本番送出(gst_heli.app)
   とは同時に実行できない(プレビューで詰めてから本番へ)。
"""

from __future__ import annotations

from .app import build_parser, make_engine
from .gst_subprocess import GstSubprocessBridge


def main():
    ap = build_parser()
    ap.add_argument("--preview-width", type=int, default=960)
    ap.add_argument("--preview-height", type=int, default=540)
    # プレビューでは出力/keyer/modeは未使用
    args = ap.parse_args()
    args.source = "decklink"

    eng = make_engine(args)
    decoder = eng["decoder"]
    bridge = GstSubprocessBridge(
        eng["current_frame"],
        lambda arr, n: decoder.feed_interleaved(arr, n),
        in_device=args.in_device, channels=args.channels, rate=int(args.rate),
        width=args.width, height=args.height, framerate="30000/1001",
        vconnection=args.vconnection, vmode=args.vmode,
        audio_port=args.audio_port, video_port=args.video_port,
        gst_bin=args.gst_bin,
        preview=True, preview_width=args.preview_width,
        preview_height=args.preview_height)
    print("プレビュー開始: 入力映像にテロップを重ねてPC窓に表示します(Ctrl+Cで終了)")
    bridge.start()
    try:
        bridge.wait()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
        if eng["ctrl"]:
            eng["ctrl"].close()
        decoder.close()


if __name__ == "__main__":
    main()
