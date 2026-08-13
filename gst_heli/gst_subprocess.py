"""PyGObject不要のGStreamerブリッジ(gst-launchサブプロセス + TCP).

Windowsで import gi(PyGObject) を使わずに済むよう、実績のある gst-launch-1.0 を
サブプロセスとして起動し、音声/映像を localhost TCP で Python とやり取りする。

  gst-launch(1プロセス):
    decklinkvideosrc → fakesink            (音声取得に必須の映像入力)
    decklinkaudiosrc → audioconvert → tcpclientsink(→ Pythonの音声サーバ)
    tcpclientsrc(← Pythonの映像サーバ) → rawvideoparse → decklinkvideosink(Fill&Key)

  Python:
    音声サーバ: PCM(S16LE, Nch)を受信し on_audio() へ
    映像サーバ: フレーム(BGRA)を frame_provider() から取り、送出(TCPの背圧で自然にペース調整)

pipeline文字列は実機検証済みの値(mode=1080i5994, framerate=30000/1001,
interlace-mode=interleaved, video-format=8bit-bgra, keyer-mode=external)。
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time

import numpy as np


def find_gst_launch(explicit: str | None = None) -> str:
    """gst-launch-1.0 の実行パスを探す."""
    if explicit:
        return explicit
    exe = shutil.which("gst-launch-1.0")
    if exe:
        return exe
    # 既定インストール先の候補
    for p in (r"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe",
              r"C:\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"):
        import os
        if os.path.exists(p):
            return p
    return "gst-launch-1.0"


class _TcpServer:
    """1接続だけ受ける小さなTCPサーバ(localhost)."""

    def __init__(self, port: int, handler):
        self.port = port
        self._handler = handler
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", port))
        self._srv.listen(1)
        self._srv.settimeout(0.5)
        self._stop = False
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()

    def _run(self):
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                self._handler(conn, lambda: self._stop)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def close(self):
        self._stop = True
        try:
            self._srv.close()
        except OSError:
            pass


class GstSubprocessBridge:
    def __init__(self, frame_provider, on_audio, *,
                 in_device=0, out_device=0, channels=8, rate=48000,
                 width=1920, height=1080, mode="1080i5994",
                 framerate="30000/1001", keyer="external",
                 vconnection="sdi", vmode="auto",
                 audio_port=5001, video_port=5002, gst_bin=None,
                 interlace=True, on_log=None,
                 preview=False, preview_width=960, preview_height=540,
                 deinterlace=True, audio_debug=True, audio_timestamp=True):
        self.preview = preview
        self.preview_width, self.preview_height = preview_width, preview_height
        self.deinterlace = deinterlace
        self.audio_debug = audio_debug
        self.audio_timestamp = audio_timestamp
        self.frame_provider = frame_provider
        self.on_audio = on_audio
        self.channels = channels
        self.rate = rate
        self.width, self.height = width, height
        self.mode = mode
        self.framerate = framerate
        self.keyer = keyer
        self.in_device, self.out_device = in_device, out_device
        self.vconnection, self.vmode = vconnection, vmode
        self.audio_port, self.video_port = audio_port, video_port
        self.gst = find_gst_launch(gst_bin)
        self.interlace = interlace
        self.on_log = on_log or (lambda s: print(s, flush=True))
        self._proc = None
        self._audio_srv = None
        self._video_srv = None
        self._frame_bytes = width * height * 4

    # ---- 音声受信: S16LE Nch を numpy で on_audio へ ----
    def _audio_handler(self, conn, stopped):
        bytes_per_set = self.channels * 2          # 1サンプル×全ch
        chunk_sets = self.rate // 10               # 100ms
        want = bytes_per_set * chunk_sets
        buf = b""
        blk = 0
        self.on_log(f"[audio] TCP接続(port {self.audio_port})。音声受信を開始")
        while not stopped():
            try:
                data = conn.recv(65536)
            except OSError:
                break
            if not data:
                break
            buf += data
            while len(buf) >= want:
                block, buf = buf[:want], buf[want:]
                arr = np.frombuffer(block, dtype="<i2").astype(np.float64) / 32768.0
                self.on_audio(arr, self.channels)
                # 診断: 2秒ごとに各chの最大レベルを表示(どのchにGPSがあるか/届いているか)
                blk += 1
                if self.audio_debug and blk % 10 == 0:   # 約1秒ごと
                    m = arr.reshape(-1, self.channels)
                    lv = np.abs(m).max(axis=0)
                    self.on_log("[audio] ch levels(CH1..): "
                                + " ".join(f"{x:.3f}" for x in lv))

    # ---- 映像送信: frame_provider()のBGRAを送り続ける(TCP背圧でペース調整) ----
    def _video_handler(self, conn, stopped):
        while not stopped():
            rgba = self.frame_provider()
            if rgba is None:
                time.sleep(0.01)
                continue
            # RGBA(H,W,4) → BGRA
            bgra = np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]]).tobytes()
            if len(bgra) != self._frame_bytes:
                continue
            try:
                conn.sendall(bgra)
            except OSError:
                break

    def _build_cmd(self):
        if self.preview:
            return self._build_cmd_preview()
        return self._build_cmd_output()

    # 音声取得のブランチ(音声には映像入力が必須なので decklinkvideosrc も動かす)
    def _audio_sink_branch(self):
        dts = "true" if self.audio_timestamp else "false"
        return ["decklinkaudiosrc", f"device-number={self.in_device}",
                "connection=embedded", f"channels={self.channels}", f"do-timestamp={dts}", "!",
                "audioconvert", "!",
                f"audio/x-raw,format=S16LE,channels={self.channels},rate={self.rate}", "!",
                "queue", "leaky=downstream", "max-size-buffers=0", "max-size-bytes=0",
                "max-size-time=0", "!",
                "tcpclientsink", "host=127.0.0.1", f"port={self.audio_port}"]

    def _video_in(self, sink):
        # 映像入力。sink に接続文字列(fakesink 等 / comp.sink_0)を渡す
        return ["decklinkvideosrc", f"device-number={self.in_device}",
                f"connection={self.vconnection}", f"mode={self.vmode}", "!"] + sink

    def _telop_src(self):
        # Pythonから来る BGRA テロップ(TCP) をフレームに切り出す
        return ["tcpclientsrc", "host=127.0.0.1", f"port={self.video_port}", "!",
                "rawvideoparse", "use-sink-caps=false", "format=bgra",
                f"width={self.width}", f"height={self.height}", f"framerate={self.framerate}", "!"]

    def _build_cmd_preview(self):
        pw, ph = self.preview_width, self.preview_height
        scale_caps = f"video/x-raw,format=BGRA,width={pw},height={ph}"
        # 入力映像: deinterlace → 窓サイズにスケール → compositor sink_0
        vin_tail = ((["deinterlace", "!"] if self.deinterlace else [])
                    + ["videoconvert", "!", "videoscale", "!", scale_caps, "!", "comp.sink_0"])
        vin = self._video_in(vin_tail)
        # テロップ: 窓サイズにスケール → compositor sink_1(アルファ合成で上に乗る)
        telop = (self._telop_src()
                 + ["videoscale", "!", "videoconvert", "!", scale_caps, "!", "comp.sink_1"])
        # compositor の出力サイズを明示(pw×ph)。これで sink のウィンドウが
        # 最初のフレームから所望サイズで作られる(小窓化・タイトルバーのみ回避)。
        out_caps = f"video/x-raw,width={pw},height={ph}"
        comp = ["compositor", "name=comp", "background=black", "!",
                out_caps, "!", "videoconvert", "!", "autovideosink", "sync=false"]
        return [self.gst, "-e"] + vin + telop + comp + self._audio_sink_branch()

    def _build_cmd_output(self):
        # 映像(Pythonから) → Fill&Key出力 のブランチ
        video_out = list(self._telop_src())
        if self.interlace:
            # rawvideoparse はプログレッシブしか出さないため、1080i の sink 向けに
            # capssetter(join=false=完全置換)で interlace-mode を interleaved に
            # ラベル差し替え。BGRA(アルファ=Key)を保持したまま1080i化できる。
            full = (f"video/x-raw,format=BGRA,width={self.width},height={self.height},"
                    f"framerate={self.framerate},interlace-mode=interleaved")
            video_out += ["capssetter", "join=false", f"caps={full}", "!"]
        # sync=false を付けると decklink 出力スケジューラが破綻して
        # "Failed to schedule frame" になる。既定(sync=true)で出力クロックに乗せる。
        # フレーム供給は sink のクロックが TCP 背圧経由で Python をペーシングする。
        video_out += ["videoconvert", "!",
                      "decklinkvideosink", f"device-number={self.out_device}",
                      f"mode={self.mode}", "video-format=8bit-bgra",
                      f"keyer-mode={self.keyer}"]
        vin = self._video_in(["fakesink", "sync=false"])
        return [self.gst, "-e"] + vin + self._audio_sink_branch() + video_out

    def start(self):
        # サーバを先に立ててから gst を起動(接続先が居る状態にする)
        self._audio_srv = _TcpServer(self.audio_port, self._audio_handler)
        self._video_srv = _TcpServer(self.video_port, self._video_handler)
        cmd = self._build_cmd()
        self.on_log("gst-launch 起動:\n  " + " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, bufsize=1,
                                      universal_newlines=True)
        threading.Thread(target=self._log_loop, daemon=True).start()

    def _log_loop(self):
        for line in self._proc.stdout:
            self.on_log("[gst] " + line.rstrip())

    def wait(self):
        if self._proc:
            self._proc.wait()

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass
        if self._audio_srv:
            self._audio_srv.close()
        if self._video_srv:
            self._video_srv.close()
