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


def _screen_size() -> tuple[int, int]:
    """プライマリモニタの解像度(px)を返す。取得失敗時は 1920x1080。"""
    try:                                   # Windows: DPIスケール前の実解像度
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
        u = ctypes.windll.user32
        w, h = int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    try:                                   # 他OS/フォールバック: tkinter
        import tkinter as _tk
        r = _tk.Tk()
        w, h = r.winfo_screenwidth(), r.winfo_screenheight()
        r.destroy()
        return int(w), int(h)
    except Exception:
        return 1920, 1080


def main():
    ap = build_parser()
    # 既定(0)は画面の約1/9(縦横とも1/3)を自動採用。小さすぎ/大きすぎる
    # ときは数値を指定して上書きできる。ウィンドウはドラッグでリサイズ可。
    ap.add_argument("--preview-width", type=int, default=0,
                    help="プレビュー窓の幅px(0=画面の約1/3=面積1/9)")
    ap.add_argument("--preview-height", type=int, default=0,
                    help="プレビュー窓の高さpx(0=画面の約1/3=面積1/9)")
    ap.add_argument("--sample-text", default="○○県○○市上空",
                    help="GPS未受信時に表示するサンプル文字(見た目確認用)")
    ap.add_argument("--no-audio-timestamp", action="store_true",
                    help="decklinkaudiosrc の do-timestamp を無効化(ドロップ対策の実験)")
    args = ap.parse_args()
    args.source = "decklink"

    # 画面の約1/9(縦横1/3)を既定サイズに。偶数に丸める(映像処理の都合)。
    if args.preview_width <= 0 or args.preview_height <= 0:
        sw, sh = _screen_size()
        if args.preview_width <= 0:
            args.preview_width = max(640, (sw // 3) & ~1)
        if args.preview_height <= 0:
            args.preview_height = max(360, (sh // 3) & ~1)
        print(f"[preview] 画面 {sw}x{sh} → プレビュー窓 "
              f"{args.preview_width}x{args.preview_height}(約1/9)", flush=True)

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
        from nnn_decoder.geodesy import deg_to_dms_str
        while not stop["v"]:
            time.sleep(2)
            st = decoder.status()
            print(f"[status] 受信={st['receiving']} packets={st['packets_ok']} "
                  f"住所={st['address']}", flush=True)
            if st["lat"] is not None:
                # 他システムとの照合用に、出力座標(WGS84)を10進とDMSで併記
                print(f"[coord] WGS84 {st['lat']:.6f},{st['lon']:.6f}"
                      f" ({deg_to_dms_str(st['lat'])},{deg_to_dms_str(st['lon'])})"
                      f"  生値 {deg_to_dms_str(st['lat_tokyo'])},"
                      f"{deg_to_dms_str(st['lon_tokyo'])}", flush=True)
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
