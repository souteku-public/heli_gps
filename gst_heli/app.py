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

    def __init__(self, cfg: HeliConfig, style: SuperStyle, port: int = 9001,
                 on_change=None):
        self.cfg = cfg
        self.style = style
        # 見た目・住所設定が変わったら呼ぶ(描画キャッシュ破棄の合図)。
        # これが無いと、文字列が変わるまで新しい見た目が反映されない。
        self.on_change = on_change
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
                    if self.on_change:
                        self.on_change()   # 次フレームで即再描画させる
                except Exception:
                    pass

    def close(self):
        self._stop = True


def _font_name_to_path(name: str):
    """フォント名(UI選択)→ Windowsのフォントファイルパス(概略対応)."""
    import os
    table = {
        # 再配布可(OFL)を優先
        "Noto Sans JP Bold": "NotoSansJP-Bold.otf",
        "Noto Sans JP": "NotoSansJP-Regular.otf",
        # 環境依存(EULA要確認)
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
    """control_ui へ状態を送る.

    位置(/heli/position)と測位状態(/heli/status)は住所文字が変わらなくても
    受信が続く限り定期的(既定 0.5秒ごと)に送り続ける。こうしないと
    control_ui 側が「受信途絶」表示になり、緯度経度もフリーズしてしまう。
    スーパー文字(/heli/super)は変化したときだけ送る。
    """

    def __init__(self, host="127.0.0.1", port=9002, interval_s: float = 0.5):
        try:
            self._osc = OscSender(host, port)
        except Exception:
            self._osc = None
        self._last_text = None
        self._interval = interval_s
        self._last_send = 0.0

    def send(self, decoder: HeliDecoder, text: str):
        if self._osc is None:
            return
        now = time.monotonic()
        text_changed = text != self._last_text
        # 文字が変わらない間引き送信(受信途絶表示・座標フリーズを防ぐ)
        if not text_changed and (now - self._last_send) < self._interval:
            return
        self._last_send = now
        st = decoder.status()
        try:
            if st["lat"] is not None:
                self._osc.send_raw("/heli/position", float(st["lat"]),
                                   float(st["lon"]), float(st["alt"]))
                # 受信状態(1=受信中/0=途絶)を先頭に付けて送る。
                # 定期送信で接続は保ちつつ、UIは実際の受信可否を表示できる。
                self._osc.send_raw("/heli/status", int(bool(st["receiving"])),
                                   int(st["fix"] or 0),
                                   int(st["sats"] if st["sats"] is not None else -1))
            if text_changed:
                self._last_text = text
                self._osc.send_raw("/heli/super", text)
        except Exception:
            pass


def make_engine(args):
    """復調・住所・描画・OSC制御をまとめて用意し、current_frame等を返す.

    本番送出(app)とプレビュー(preview)で共有する。
    """
    cfg = HeliConfig(fs=args.rate, baud=args.baud, channel=args.channel,
                     geo_mode=args.geo_mode, addr_level=args.addr_level,
                     datum=getattr(args, "datum", "wgs84"),
                     stale_timeout=getattr(args, "stale_timeout", 5.0),
                     hold_timeout=getattr(args, "hold_timeout", 15.0))
    style = SuperStyle(font_size=args.font_size)
    decoder = HeliDecoder(cfg)
    renderer = SuperRenderer(args.width, args.height, style)
    status = StatusSender(args.status_host, args.status_port)
    cache = {"text": None, "frame": np.zeros((args.height, args.width, 4), np.uint8),
             "style_ver": 0, "drawn_ver": -1}

    def mark_dirty():
        # 見た目/住所設定が変わった。バージョンを進めて次フレームで再描画。
        cache["style_ver"] += 1

    ctrl = (OscControl(cfg, style, args.ctrl_port, on_change=mark_dirty)
            if args.osc_control else None)

    def current_frame():
        text = decoder.current_text()
        ver = cache["style_ver"]
        # 文字が変わった時 or 見た目設定が変わった時に再描画。
        # 後者が無いと「決定」を押しても位置が変わるまで反映されなかった。
        if text != cache["text"] or ver != cache["drawn_ver"]:
            cache["text"] = text
            cache["drawn_ver"] = ver
            cache["frame"] = renderer.render(text)
        # 位置・状態は受信中は定期的に送る(StatusSender側で間引き)。
        # 住所文字が安定しても control_ui が途絶表示にならないようにするため。
        status.send(decoder, text)
        return cache["frame"]

    return dict(cfg=cfg, style=style, decoder=decoder, renderer=renderer,
                status=status, ctrl=ctrl, cache=cache, current_frame=current_frame)


def run(args):
    eng = make_engine(args)
    decoder, renderer = eng["decoder"], eng["renderer"]
    ctrl, cache, current_frame = eng["ctrl"], eng["cache"], eng["current_frame"]

    # ---- ファイル(WAV)モードはハード不要 ----
    if args.source == "wav":
        _run_file_mode(args, decoder, renderer, current_frame, cache)
        if ctrl:
            ctrl.close()
        decoder.close()
        return

    # ---- 実機(decklink) ----
    if args.backend == "subprocess":
        # PyGObject不要: gst-launchサブプロセス + TCP
        from .gst_subprocess import GstSubprocessBridge
        bridge = GstSubprocessBridge(
            current_frame,
            lambda arr, n: decoder.feed_interleaved(arr, n),
            in_device=args.in_device, out_device=args.out_device,
            channels=args.channels, rate=int(args.rate),
            width=args.width, height=args.height, mode=args.mode,
            keyer=args.keyer, vconnection=args.vconnection, vmode=args.vmode,
            audio_port=args.audio_port, video_port=args.video_port,
            gst_bin=args.gst_bin, interlace=not args.no_interlace,
            deinterlace=args.deinterlace,
            out_mode=args.output_mode, av_offset_ms=args.av_offset_ms)
        bridge.start()
        try:
            bridge.wait()
        except KeyboardInterrupt:
            pass
        finally:
            bridge.stop()
    else:
        # PyGObject(gi)方式
        from .gst_io import DecklinkFillKeyOut, DecklinkAudioIn, main_loop
        out = DecklinkFillKeyOut(current_frame, device_number=args.out_device,
                                 mode=args.mode, width=args.width, height=args.height,
                                 keyer=args.keyer) if args.output == "decklink" else None
        if out:
            out.start()
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
    ap.add_argument("--addr-level", default="muni",
                    choices=["pref", "muni", "city", "citygun", "town"])
    ap.add_argument("--datum", default="wgs84", choices=["wgs84", "tokyo"],
                    help="NNN座標の測地系。wgs84=変換なし(既定) / tokyo=WGS84へ変換")
    ap.add_argument("--font-size", type=int, default=90)
    ap.add_argument("--stale-timeout", type=float, default=5.0,
                    help="この秒数を超えたら『受信中』でないと判定")
    ap.add_argument("--hold-timeout", type=float, default=15.0,
                    help="受信途絶後も直近スーパーを保持する秒数(音声瞬断対策)")

    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--mode", default="1080i5994", help="出力 信号フォーマット")
    ap.add_argument("--keyer", default="external", choices=["external", "internal", "off"])
    ap.add_argument("--output-mode", default="fillkey", choices=["fillkey", "burnin"],
                    help="fillkey=Fill&Key出し(外部キーヤー前提) / "
                         "burnin=入力映像+音声にテロップを焼き込んで1本で出力")
    ap.add_argument("--deinterlace", action="store_true",
                    help="burnin時に入力をデインタレースして合成(既定OFF=iのまま重畳)")
    ap.add_argument("--av-offset-ms", type=int, default=0,
                    help="burnin時のA/V補正[ms](+で音声を遅らせる)")
    ap.add_argument("--in-device", type=int, default=0)
    ap.add_argument("--out-device", type=int, default=0)
    # backend / subprocess方式のオプション
    ap.add_argument("--backend", choices=["subprocess", "gi"], default="subprocess",
                    help="subprocess=gst-launch(PyGObject不要,既定) / gi=PyGObject")
    ap.add_argument("--vconnection", default="sdi", help="映像入力コネクション(音声取得に必須)")
    ap.add_argument("--vmode", default="auto", help="映像入力mode(auto=自動検出)")
    ap.add_argument("--audio-port", type=int, default=5001)
    ap.add_argument("--video-port", type=int, default=5002)
    ap.add_argument("--gst-bin", default=None, help="gst-launch-1.0のパス(未指定は自動探索)")
    ap.add_argument("--no-interlace", action="store_true",
                    help="出力caps に interlace-mode=interleaved を付けない")

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
