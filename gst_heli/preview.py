"""見た目確認用プレビュー: 入力SDI映像 + テロップ をPC窓に合成表示.

SDI出力はしない(REF不要)。入力映像に実際のテロップを重ねてPCの
ウィンドウに表示するので、control_ui.py でフォント/色/フチ/位置を
調整しながら仕上がりを確認できる。

    python -m gst_heli.preview --osc-control --channel 2
    python control_ui.py     (別ウィンドウで操作)

GPS未受信でも見た目を確認できるよう、既定でサンプル文字を表示する
(--sample-text)。実GPSが復調できればその住所に切り替わる。

※ SDIデバイスは1プロセスしか入力を開けないため、本番送出(gst_heli.app)
   とは同時に実行できない(プレビューで詰めてから本番へ)。
"""

from __future__ import annotations

import threading
import time

from .app import build_parser, make_engine
from .gst_subprocess import GstSubprocessBridge


def main():
    ap = build_parser()
    # 既定を 1280x720 に(小さすぎて操作しにくいという指摘への対応)。
    # ウィンドウはドラッグでリサイズ可能(--preview-width/height で初期サイズ変更)。
    ap.add_argument("--preview-width", type=int, default=1280)
    ap.add_argument("--preview-height", type=int, default=720)
    ap.add_argument("--sample-text", default="○○県○○市上空",
                    help="GPS未受信時に表示するサンプル文字(見た目確認用)")
    ap.add_argument("--no-audio-timestamp", action="store_true",
                    help="decklinkaudiosrc の do-timestamp を無効化(ドロップ対策の実験)")
    args = ap.parse_args()
    args.source = "decklink"

    eng = make_engine(args)
    decoder = eng["decoder"]
    # 未受信時はサンプル文字を出す(見た目確認用)
    eng["cfg"].stale_text = args.sample_text

    bridge = GstSubprocessBridge(
        eng["current_frame"],
        lambda arr, n: decoder.feed_interleaved(arr, n),
        in_device=args.in_device, channels=args.channels, rate=int(args.rate),
        width=args.width, height=args.height, framerate="30000/1001",
        vconnection=args.vconnection, vmode=args.vmode,
        audio_port=args.audio_port, video_port=args.video_port,
        gst_bin=args.gst_bin,
        preview=True, preview_width=args.preview_width,
        preview_height=args.preview_height,
        audio_timestamp=not args.no_audio_timestamp)

    # 2秒ごとに復調状況を表示(受信/パケット数)
    stop = {"v": False}

    def status_loop():
        while not stop["v"]:
            time.sleep(2)
            st = decoder.status()
            print(f"[status] 受信={st['receiving']} packets={st['packets_ok']} "
                  f"住所={st['address']}", flush=True)
    threading.Thread(target=status_loop, daemon=True).start()

    print("プレビュー開始: 入力映像にテロップを重ねてPC窓に表示します(Ctrl+Cで終了)")
    bridge.start()
    try:
        bridge.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop["v"] = True
        bridge.stop()
        if eng["ctrl"]:
            eng["ctrl"].close()
        decoder.close()


if __name__ == "__main__":
    main()
