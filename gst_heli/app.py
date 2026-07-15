"""GStreamer版 ヘリGPSスーパー送出アプリ(TouchDesigner不要).

音源:  SDIエンベデッド音声(decklink) または WAV/映像ファイル
出力:  Fill&Key SDI(decklink) または プレビューPNG連番

制御:  control_ui.py と同じ OSC プロトコル(/heli/ctrl/*)で live 変更可
状態:  /heli/super /heli/position /heli/status を 127.0.0.1:9002 へ送出

使用例:
    # 実機(SDI入力→Fill&Key出力)
    python -m gst_heli.app --source decklink --output decklink

    # ハード無しでロジック確認(WAV→プレビューPNG)
    python -m gst_heli.app --source wav --wav test.wav --output preview \
        --preview-dir out --duration 10
"""

from __future__ import annotations

import argparse
import queue
import socket
import threading
import time

import numpy as np

from nnn_decoder.osc import OscSender, osc_parse

from .decoder_core import HeliConfig, HeliDecoder
from .renderer import SuperRenderer, SuperStyle


class OscControl:
    """control_ui.py からの /heli/ctrl/* を受けて cfg/style を更新."""

    def __init__(self, cfg: HeliConfig, style: SuperStyle, port: int = 9001):
        self.cfg = cfg
        self.style = style
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", port))
        self._sock.settimeout(0.3)
        self._stop = False
        self._color = list(style.color)
        self._stroke = list(style.stroke_color)
        threading.Thread(target=self._loop, daemon=True).start()

    def _apply(self, name, val):
        c, s = self.cfg, self.style
        if name == "Geomode":
            c.geo_mode = val          # 反映には再起動が必要(geocoderはmode固定)
        elif name == "Addrlevel":
            c.addr_level = val
        elif name == "Textformat":
            c.text_format = val or "{address}上空"
        elif name == "Staletext":
            c.stale_text = val
        elif name == "Audiochan":
            c.channel = int(val)
        elif name == "Fontsize":
            s.font_size = int(val)
        elif name == "Alignx":
            s.align_x = val
        elif name == "Aligny":
            s.align_y = val
        elif name == "Posx":
            s.margin_x = int(val)
        elif name == "Posy":
            s.margin_y = int(val)
        elif name == "Fontpath":
            s.font_path = val or None       # UIが実ファイルパスを直接指定
        elif name == "Font":
            # 旧: フォント名からの推測(Fontpath未使用のとき用)
            if val:
                p = _font_name_to_path(val)
                if p:
                    s.font_path = p
        elif name == "Strokewidth":
            s.stroke_width = int(val)
        elif name in ("Fontcolorr", "Fontcolorg", "Fontcolorb"):
            idx = {"Fontcolorr": 0, "Fontcolorg": 1, "Fontcolorb": 2}[name]
            self._color[idx] = int(max(0.0, min(1.0, float(val))) * 255)
            s.color = tuple(self._color)
        elif name in ("Strokecolorr", "Strokecolorg", "Strokecolorb"):
            idx = {"Strokecolorr": 0, "Strokecolorg": 1, "Strokecolorb": 2}[name]
            self._stroke[idx] = int(max(0.0, min(1.0, float(val))) * 255)
            s.stroke_color = tuple(self._stroke)

    def _loop(self):
        while not self._stop:
            try:
                data, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            addr, args = osc_parse(data)
            if addr.startswith("/heli/ctrl/") and args:
                try:
                    self._apply(addr.rsplit("/", 1)[-1], args[0])
                except Exception:
                    pass

    def close(self):
        self._stop = True


def _font_name_to_path(name: str):
    """フォント名(UI選択)→ Windowsのフォントファイルパス(概略対応)."""
    import os
    table = {
        "Yu Gothic UI": "YuGothM.ttc", "Yu Gothic": "YuGothB.ttc",
        "Meiryo": "meiryo.ttc", "MS Gothic": "msgothic.ttc",
        "BIZ UDPGothic": "BIZ-UDPGothicR.ttc", "游明朝": "yumin.ttf",
        "MS Mincho": "msmincho.ttc",
    }
    fn = table.get(name)
    if fn:
        p = os.path.join(r"C:\Windows\Fonts", fn)
        if os.path.exists(p):
            return p
    return None


class StatusSender:
    """control_ui へ状態を送る(復調時 ~1回/秒)."""

    def __init__(self, host="127.0.0.1", port=9002):
        try:
            self._osc = OscSender(host, port)
        except Exception:
            self._osc = None
        self._last_text = None

    def send(self, decoder: HeliDecoder, text: str):
        if self._osc is None:
            return
        st = decoder.status()
        try:
            if st["lat"] is not None:
                self._osc.send_raw("/heli/position", float(st["lat"]),
                                   float(st["lon"]), float(st["alt"]))
                self._osc.send_raw("/heli/status", int(st["fix"] or 0),
                                   int(st["sats"] if st["sats"] is not None else -1),
                                   "01")
            if text != self._last_text:
                self._last_text = text
                self._osc.send_raw("/heli/super", text)
        except Exception:
            pass


def run(args):
    cfg = HeliConfig(fs=args.rate, baud=args.baud, channel=args.channel,
                     geo_mode=args.geo_mode, addr_level=args.addr_level)
    style = SuperStyle(font_size=args.font_size)
    decoder = HeliDecoder(cfg)
    renderer = SuperRenderer(args.width, args.height, style)
    status = StatusSender(args.status_host, args.status_port)
    ctrl = OscControl(cfg, style, args.ctrl_port) if args.osc_control else None

    # レンダリングのキャッシュ(テキスト変化時のみ再描画)
    cache = {"text": None, "frame": np.zeros((args.height, args.width, 4), np.uint8)}

    def current_frame():
        text = decoder.current_text()
        if text != cache["text"]:
            cache["text"] = text
            cache["frame"] = renderer.render(text)
            status.send(decoder, text)
        return cache["frame"]

    # ---- 出力 ----
    if args.output == "decklink":
        from .gst_io import DecklinkFillKeyOut, main_loop
        out = DecklinkFillKeyOut(current_frame, device_number=args.out_device,
                                 mode=args.mode, width=args.width, height=args.height,
                                 keyer=args.keyer)
        out.start()
    else:
        out = None

    # ---- 音源 ----
    stop_flag = {"stop": False}
    if args.source == "decklink":
        from .gst_io import DecklinkAudioIn, main_loop
        audio = DecklinkAudioIn(device_number=args.in_device, channels=args.channels,
                                rate=int(args.rate),
                                on_samples=lambda arr, n: decoder.feed_interleaved(arr, n))
        audio.start()
        loop = main_loop()
        try:
            loop.run()
        except KeyboardInterrupt:
            pass
        finally:
            audio.stop()
            if out:
                out.stop()
    else:
        # WAV/ファイル: 実時間で少しずつ投入し、プレビューPNGを書き出す
        _run_file_mode(args, decoder, renderer, current_frame, cache)

    if ctrl:
        ctrl.close()
    decoder.close()


def _run_file_mode(args, decoder, renderer, current_frame, cache):
    """ハード無しの検証用: WAVを実時間投入し、プレビューPNGを定期保存."""
    import os
    from nnn_decoder.cli import read_wav

    x, fs = read_wav(args.wav, str(args.channel + 1) if args.channels > 1 else "left")
    decoder.cfg.fs = fs
    # HeliDecoderのpipelineはfsで作成済み。fsが違えば作り直し
    if abs(fs - args.rate) > 1:
        from nnn_decoder.pipeline import DecoderPipeline
        decoder._pipe = DecoderPipeline(fs, baud=args.baud)

    os.makedirs(args.preview_dir, exist_ok=True)
    block = int(fs * 0.1)  # 100ms刻みで実時間投入
    n_blocks = len(x) // block
    saved = 0
    t0 = time.monotonic()
    for i in range(n_blocks):
        decoder.feed(x[i * block:(i + 1) * block])
        # 1秒ごとにプレビュー保存
        if i % 10 == 0:
            frame = current_frame()
            from PIL import Image
            Image.fromarray(frame).save(os.path.join(args.preview_dir, f"super_{saved:04d}.png"))
            saved += 1
            print(f"[{i*0.1:6.1f}s] super={cache['text']!r}  status={decoder.status()['receiving']}")
        if args.realtime:
            target = t0 + (i + 1) * 0.1
            dt = target - time.monotonic()
            if dt > 0:
                time.sleep(dt)
        if args.duration and i * 0.1 >= args.duration:
            break
    print(f"プレビュー {saved} 枚を {args.preview_dir} に保存しました。")


def build_parser():
    ap = argparse.ArgumentParser(description="GStreamer版 ヘリGPSスーパー送出")
    ap.add_argument("--source", choices=["decklink", "wav"], default="decklink")
    ap.add_argument("--output", choices=["decklink", "preview"], default="decklink")
    ap.add_argument("--wav", help="--source wav のときの入力ファイル")
    ap.add_argument("--preview-dir", default="preview_out")
    ap.add_argument("--duration", type=float, default=0, help="file mode: 秒数(0=全部)")
    ap.add_argument("--realtime", action="store_true", help="file mode: 実時間で投入")

    ap.add_argument("--rate", type=float, default=48000)
    ap.add_argument("--baud", type=int, default=1200, choices=[1200, 2400])
    ap.add_argument("--channels", type=int, default=8, help="入力音声ch数")
    ap.add_argument("--channel", type=int, default=2, help="GPS音声ch(0始まり)")
    ap.add_argument("--geo-mode", default="offline", choices=["offline", "auto", "online"])
    ap.add_argument("--addr-level", default="muni", choices=["pref", "muni", "city", "town"])
    ap.add_argument("--font-size", type=int, default=90)

    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--mode", default="1080i5994", help="decklink 信号フォーマット")
    ap.add_argument("--keyer", default="external", choices=["external", "internal", "off"])
    ap.add_argument("--in-device", type=int, default=0)
    ap.add_argument("--out-device", type=int, default=0)

    ap.add_argument("--osc-control", action="store_true", help="control_ui からの操作を受ける")
    ap.add_argument("--ctrl-port", type=int, default=9001)
    ap.add_argument("--status-host", default="127.0.0.1")
    ap.add_argument("--status-port", type=int, default=9002)
    return ap


def main():
    args = build_parser().parse_args()
    if args.source == "wav" and not args.wav:
        raise SystemExit("--source wav には --wav <file> が必要です")
    run(args)


if __name__ == "__main__":
    main()
