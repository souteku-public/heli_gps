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

import os
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


class PortError(RuntimeError):
    """localhost のポートが使えない(他のプロセスが使用中 等)."""


class _TcpServer:
    """1接続だけ受ける小さなTCPサーバ(localhost).

    ポートの扱いに Windows 固有の注意がある:

      SO_REUSEADDR は Unix と Windows で**意味が違う**。Windows では
      「他のプロセスが現に待ち受けているポートにも重ねて bind できる」
      という挙動になり、bind は成功するのに接続はそちらに届かない
      (gst 側は『接続が拒否されました』になる) という分かりにくい
      故障を起こす。そのため Windows では SO_EXCLUSIVEADDRUSE を使い、
      ぶつかったら**はっきり失敗させて**別のポートに移る。
    """

    def __init__(self, port: int, handler, label: str = ""):
        self._handler = handler
        self.label = label
        self._srv = None
        self.port = self._bind(port)
        self._selftest()                 # 本当に接続できるか確かめてから使う
        self._srv.settimeout(0.5)
        self._stop = False
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()

    # ---- bind: 希望ポート → だめなら空きポート ----
    def _bind(self, want: int) -> int:
        errs = []
        for p in (want, 0):              # 0 = OSに空きを選ばせる
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name == "nt":
                # Windows: 重ね bind を禁止し、競合をここで検出する
                try:
                    srv.setsockopt(socket.SOL_SOCKET,
                                   getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
                except OSError:
                    pass
            else:
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind(("127.0.0.1", p))
                srv.listen(4)
            except OSError as e:
                errs.append(f"port {p or 'auto'}: {e}")
                srv.close()
                continue
            self._srv = srv
            return srv.getsockname()[1]
        raise PortError(f"{self.label}: localhost のポートを確保できません "
                        + " / ".join(errs))

    def _selftest(self) -> None:
        """自分で自分に繋いでみて、loopback が本当に通るか確かめる.

        ファイアウォール/セキュリティ製品が loopback を遮っている場合も
        ここで分かる(gst を起動してから謎のエラーになるのを防ぐ)。
        """
        self._srv.settimeout(3.0)
        try:
            probe = socket.create_connection(("127.0.0.1", self.port), timeout=3.0)
        except OSError as e:
            self._srv.close()
            raise PortError(
                f"{self.label}: 127.0.0.1:{self.port} に接続できません ({e})。"
                "ファイアウォール/セキュリティ製品が localhost の通信を"
                "遮っていないか確認してください") from e
        try:
            conn, _ = self._srv.accept()
            conn.close()
        except OSError as e:
            self._srv.close()
            raise PortError(f"{self.label}: loopback の自己接続に失敗 ({e})") from e
        finally:
            probe.close()

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
                 # 既定は「画に手を加えない」。デインターレースしたい呼び出し側
                 # (プレビュー)が明示的に True を渡すこと。既定に頼って両者が
                 # 食い違うと compositor の交渉が失敗する(not-negotiated)。
                 deinterlace=False, audio_debug=True, audio_timestamp=True,
                 out_mode="fillkey", av_offset_ms=0, audio_only=False,
                 comp_format="auto"):
        # バーンイン合成時の中間フォーマット(色の通り道)。詳細は
        # _build_cmd_burnin / _resolve_comp_format を参照。
        #   "auto" = A422 が使えればそれ、だめなら AYUV(どちらも色を保つ)
        self.comp_format = comp_format
        self._comp_format_resolved = None     # auto の判定結果(1回だけ調べる)
        # 切り分け用: 映像出力を一切つながず、GPS音声の取り込みだけを行う。
        # これで「入力が悪いのか、出力が悪いのか」をはっきりさせられる。
        self.audio_only = audio_only
        self.out_mode = out_mode          # "fillkey"=Fill&Key / "burnin"=焼き込み
        self.av_offset_ms = av_offset_ms  # バーンイン時の音声A/V補正(+で音声を遅らせる)
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
        self._errors: list[str] = []
        self._audio_srv = None
        self._video_srv = None
        self._frame_bytes = width * height * 4
        # BGRA変換の作業用。毎フレームの確保と再変換を避けるため(下記 _to_bgra)
        self._bgra_buf = None
        self._last_src = None
        self._last_bgra = None

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
    def _to_bgra(self, rgba) -> bytes:
        """RGBA(H,W,4) → BGRA の bytes。**同じフレームなら前回の結果を使い回す**.

        ここは1秒に約30回まわる。素直に書くと

            np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]]).tobytes()

        となるが、1920x1080 でこれが **約17ms**。29.97fps の猶予 33.4ms の
        半分を1フレームの色順入れ替えだけで使ってしまい、しかも毎秒 500MB 近い
        確保を繰り返す。制御UIなど他のプロセスがCPUを使うと送出が間に合わず、
        映像がカクつく原因になっていた。

        対策は2つ:

        1. **再変換しない** — current_frame() は中身が変わらない限り同じ
           ndarray を返す(renderer.render_layers は描き直したときだけ
           新しい配列を作る)ので、オブジェクトが同一かどうかだけ見れば
           再変換の要否が分かる。元フレームの参照を持ち続けるので、
           解放済みオブジェクトに id が再利用される心配もない。
           実際に文字が変わるのは時刻の更新などで毎秒1回程度。

        2. **確保し直さない** — 変換が要るときもチャンネルごとの代入で
           事前確保したバッファに書く(fancy index より約4倍速い)。
        """
        if rgba is self._last_src and self._last_bgra is not None:
            return self._last_bgra
        buf = self._bgra_buf
        if buf is None or buf.shape != rgba.shape:
            buf = self._bgra_buf = np.empty(rgba.shape, dtype=np.uint8)
        buf[:, :, 0] = rgba[:, :, 2]
        buf[:, :, 1] = rgba[:, :, 1]
        buf[:, :, 2] = rgba[:, :, 0]
        buf[:, :, 3] = rgba[:, :, 3]
        out = buf.tobytes()
        self._last_src, self._last_bgra = rgba, out
        return out

    def _video_handler(self, conn, stopped):
        while not stopped():
            rgba = self.frame_provider()
            if rgba is None:
                time.sleep(0.01)
                continue
            bgra = self._to_bgra(rgba)
            if len(bgra) != self._frame_bytes:
                continue
            try:
                conn.sendall(bgra)
            except OSError:
                break

    def _build_cmd(self):
        if self.audio_only:
            return self._build_cmd_audio_only()
        if self.preview:
            return self._build_cmd_preview()
        if self.out_mode == "burnin":
            return self._build_cmd_burnin()
        return self._build_cmd_output()

    def _build_cmd_audio_only(self):
        """切り分け用: 映像入力(音声取得に必須)＋GPS音声だけ。SDI出力なし.

        本番と同じ device-number / connection / mode / channels を使うので、
        これで GPS が受かれば**入力側は正常**＝原因は出力側にある、と分かる。
        """
        vin = self._video_in(["fakesink", "sync=false"])
        return [self.gst, "-e"] + vin + self._audio_sink_branch()

    # 音声取得のブランチ(音声には映像入力が必須なので decklinkvideosrc も動かす)
    def _audio_sink_branch(self):
        dts = "true" if self.audio_timestamp else "false"
        # 復調にはサンプルの連続性が命(欠けると MSK が壊れる)。
        #  - queue はサイズ無制限(実質ドロップ無し)で瞬間的な詰まりを吸収。
        #  - tcpclientsink sync=false: パイプラインのクロックに同期させず、
        #    届いた音声をそのまま即転送する。ペースは TCP の背圧で Python 側が
        #    決める。sync=true(既定)だとクロック競合時に音声が間引かれ、
        #    復調が断続的になる原因になる。
        return ["decklinkaudiosrc", f"device-number={self.in_device}",
                "connection=embedded", f"channels={self.channels}", f"do-timestamp={dts}", "!",
                "audioconvert", "!",
                f"audio/x-raw,format=S16LE,channels={self.channels},rate={self.rate}", "!",
                "queue", "leaky=no", "max-size-buffers=0", "max-size-bytes=0",
                "max-size-time=0", "!",
                "tcpclientsink", "host=127.0.0.1", f"port={self.audio_port}",
                "sync=false"]

    def _video_in(self, sink):
        # 映像入力。sink に接続文字列(fakesink 等 / comp.sink_0)を渡す
        return ["decklinkvideosrc", f"device-number={self.in_device}",
                f"connection={self.vconnection}", f"mode={self.vmode}", "!"] + sink

    def _telop_src(self, interlaced: bool = False):
        """Pythonから来る BGRA テロップ(TCP) をフレームに切り出す.

        interlaced=True のとき interleaved と名乗らせる。compositor は
        2入力のインターレース指定が揃っていないと交渉に失敗するため、
        1080i をそのまま合成する場合はこちらを使う。
        """
        return ["tcpclientsrc", "host=127.0.0.1", f"port={self.video_port}", "!",
                "rawvideoparse", "use-sink-caps=false", "format=bgra",
                f"width={self.width}", f"height={self.height}",
                f"framerate={self.framerate}"]  \
            + (["interlaced=true"] if interlaced else []) + ["!"]

    def _build_cmd_preview(self):
        pw, ph = self.preview_width, self.preview_height
        scale_caps = f"video/x-raw,format=BGRA,width={pw},height={ph}"
        # 入力映像: deinterlace → 窓サイズにスケール → compositor sink_0
        vin = self._video_in(self._compositor_in()
                             + ["videoscale", "!", scale_caps, "!", "comp.sink_0"])
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

    # ---- バーンイン: 入力映像+音声にテロップを焼き込んで1本で出力 ----
    def _audio_branch_burnin(self):
        """入力音声を tee で分岐: (1)Pythonへ復調用 (2)出力へパススルー."""
        dts = "true" if self.audio_timestamp else "false"
        off_ns = int(self.av_offset_ms) * 1_000_000   # +で音声を遅らせA/V合わせ
        return ["decklinkaudiosrc", f"device-number={self.in_device}",
                "connection=embedded", f"channels={self.channels}",
                f"do-timestamp={dts}", "!",
                "audioconvert", "!",
                f"audio/x-raw,format=S16LE,channels={self.channels},rate={self.rate}", "!",
                "tee", "name=at",
                # (1) 復調用(Python)。連続性優先で sync=false・非リーク無制限キュー
                "at.", "!", "queue", "leaky=no", "max-size-buffers=0",
                "max-size-bytes=0", "max-size-time=0", "!",
                "tcpclientsink", "host=127.0.0.1", f"port={self.audio_port}", "sync=false",
                # (2) 出力パススルー(埋め込み音声として送出)
                "at.", "!", "queue", "!", "audioconvert", "!",
                "decklinkaudiosink", f"device-number={self.out_device}",
                f"ts-offset={off_ns}"]

    def _compositor_in(self):
        """入力映像を compositor に入れる要素列.

        compositor 自体はインターレース映像を扱える。ただし
        **2つの入力でインターレースの有無が食い違うと交渉に失敗する**
        (`not-negotiated` でソースが止まる)。入力が 1080i、テロップが
        progressive のままだとこれに当たる。そこで

          deinterlace=False (既定)
              入力は 1080i のまま。テロップ側を interleaved と名乗らせて
              揃える(_telop_src(interlaced=True))。**画に一切手を加えない**。
              テロップは静止しているので両フィールドに同じ文字が乗り、
              結果は正しい。

          deinterlace=True (--deinterlace)
              入力をプログレッシブに変換して合成する。テロップ側も
              progressive のままなので揃う。1080i の解像感は落ちるため、
              既定では使わない(プレビュー表示など用)。
        """
        if self.deinterlace:
            return ["deinterlace", "!", "videoconvert", "!"]
        return ["videoconvert", "!"]

    def _telop_interlaced(self) -> bool:
        """テロップを interleaved と名乗らせるか(入力と揃えるため)."""
        return bool(self.interlace and not self.deinterlace)

    def _has_format(self, fmt: str) -> bool:
        """この環境の GStreamer がその映像フォーマットを扱えるか.

        小さなパイプラインを1フレームだけ流して確かめる(数十ms)。
        知らないフォーマットを caps に書くと交渉に失敗してパイプライン全体が
        止まり、**同じパイプラインに居る音声取り込み(GPS)まで道連れになる**。
        だから「書いてから失敗する」のではなく、先に確かめる。
        """
        try:
            r = subprocess.run(
                [self.gst, "-q", "videotestsrc", "num-buffers=1", "!",
                 f"video/x-raw,format={fmt},width=16,height=16", "!", "fakesink"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    def _resolve_comp_format(self) -> str:
        """合成に使う中間フォーマットを決める.

        A422 は 4:2:2 のままアルファ合成できるので、入力(UYVY 4:2:2)との
        往復で色差の再サンプリングが起きず、実測で**完全一致**になる。
        ただし比較的新しい形式(GStreamer 1.24 以降)なので、無い環境では
        昔からある AYUV(4:4:4+α)に落とす。AYUV でも輝度は完全に保たれ、
        差が出るのは色差がピクセル単位で切り替わる箇所だけ。
        """
        if self.comp_format != "auto":
            return self.comp_format
        if self._comp_format_resolved is None:
            if self._has_format("A422"):
                self._comp_format_resolved = "A422"
            else:
                self.on_log("[comp] A422 が使えないため AYUV で合成します"
                            "(色は保たれます)")
                self._comp_format_resolved = "AYUV"
        return self._comp_format_resolved

    def _build_cmd_burnin(self):
        # 入力映像 → (そのまま1080i / 任意でdeinterlace) → compositor.sink_0
        vin = self._video_in(self._compositor_in() + ["comp.sink_0"])
        # テロップ(BGRA/α) → compositor.sink_1(アルファ合成で上に乗る)
        # 入力映像とインターレース指定を揃える(揃っていないと not-negotiated)
        telop = (self._telop_src(self._telop_interlaced())
                 + ["videoconvert", "!", "comp.sink_1"])
        # 合成 → 番組映像として焼き込み出力(keyer=off)
        #
        # ここで **compositor の出力フォーマットを明示する** のが重要。
        # 指定しないと compositor は BGRA / colorimetry=0:1:0:0(不明)で
        # 交渉してしまう。すると
        #
        #     入力 UYVY/bt709(限定レンジ 16-235)
        #       → フルレンジRGBへ展開 → 推測した行列・レンジで YUV へ戻す
        #
        # という往復が入り、テロップの無い素通し部分まで色が変わる。
        # 実測(入力=カラーバー等、テロップ完全透過で素通し)では
        #
        #     一致画素 6〜25%   白(輝度)が 253→235, 173→170 に切り詰め
        #
        # つまり「白のレベルを100%で切っている」という症状そのもの。
        #
        # 合成フォーマットを YUV+アルファに固定すると入力の色空間から
        # 出ないので、素通し部分は入力と一致する:
        #
        #     A422(4:2:2+α) 一致 100% / 輝度差 0  ← 既定(auto)
        #     AYUV(4:4:4+α) 輝度差 0、色差のみ硬い色境界で僅差
        #
        # どちらもスーパーホワイトを保持する。アルファ合成が要るので
        # UYVY や Y42B(アルファ無し)は使えない(実測では真っ黒になる)。
        comp = ["compositor", "name=comp", "background=black", "!"]
        cf = self._resolve_comp_format()
        if cf:
            comp += [f"video/x-raw,format={cf}", "!"]
        comp += ["videoconvert", "!"]
        if self.interlace:
            full = (f"video/x-raw,width={self.width},height={self.height},"
                    f"framerate={self.framerate},interlace-mode=interleaved")
            comp += ["capssetter", "join=false", f"caps={full}", "!", "videoconvert", "!"]
        comp += ["decklinkvideosink", f"device-number={self.out_device}",
                 f"mode={self.mode}", "video-format=8bit-yuv", "keyer-mode=off"]
        return [self.gst, "-e"] + vin + telop + comp + self._audio_branch_burnin()

    def start(self):
        # サーバを先に立ててから gst を起動(接続先が居る状態にする)。
        # 希望ポートが他のプロセスに使われていたら空きポートへ自動で移る。
        # gst へは「実際に確保できたポート」を渡すので番号は何でもよい。
        self._audio_srv = _TcpServer(self.audio_port, self._audio_handler,
                                     label="音声(GPS)")
        if self._audio_srv.port != self.audio_port:
            self.on_log(f"[port] 音声ポート {self.audio_port} は使用中のため "
                        f"{self._audio_srv.port} を使います")
            self.audio_port = self._audio_srv.port
        if self.audio_only:
            self._video_srv = None       # 映像は出さないのでサーバ不要
        else:
            self._video_srv = _TcpServer(self.video_port, self._video_handler,
                                         label="映像(テロップ)")
            if self._video_srv.port != self.video_port:
                self.on_log(f"[port] 映像ポート {self.video_port} は使用中のため "
                            f"{self._video_srv.port} を使います")
                self.video_port = self._video_srv.port
        cmd = self._build_cmd()
        self.on_log("gst-launch 起動:\n  " + " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, bufsize=1,
                                      universal_newlines=True)
        threading.Thread(target=self._log_loop, daemon=True).start()

    def _log_loop(self):
        for line in self._proc.stdout:
            line = line.rstrip()
            self.on_log("[gst] " + line)
            low = line.lower()
            if "error" in low or "warning" in low or "failed" in low:
                self._errors.append(line)
                del self._errors[:-20]        # 直近20行だけ覚えておく

    # gst の失敗メッセージ → 日本語の原因・対処
    _HINTS = (
        ("failed to schedule", "出力が基準同期(REF/ゲンロック)に乗れていません。"
                               "REFケーブルと Desktop Video Setup の設定を確認してください"),
        ("in use", "DeckLink が他のアプリに使われています。Media Express / "
                   "プレビュー / もう一方の起動バッチを閉じてください"),
        ("not-negotiated", "映像のキャプス交渉に失敗しました。入力映像とテロップで"
                           "インターレースの指定が食い違っている可能性があります。"
                           "解消しない場合はバッチの EXTRA に --deinterlace を"
                           "指定してみてください"),
        ("internal data stream error", "上流の要素が停止しました。直前の "
                                       "not-negotiated / エラー行を確認してください"),
        ("failed to connect to host", "gst から本体(Python)への localhost 接続が"
                                      "できませんでした。ファイアウォール/セキュリティ製品が"
                                      "loopback を遮っていないか確認してください"),
        ("could not open resource", "gst から本体(Python)への localhost 接続が"
                                    "できませんでした(同上)"),
        ("no such element", "GStreamer が Complete で入っていません。"
                            "Runtime と Development を【Complete】で入れ直してください"),
        ("not configured to support", "そのデバイスでは入力と出力を同時に使えません。"
                                      "Desktop Video Setup で半二重/全二重(Duplex)の設定を"
                                      "見直すか、入出力を別デバイスに分けてください"),
        ("mode", "入力または出力のフォーマット指定が合っていない可能性があります"
                 "（VMODE / MODE を実際の信号に合わせてください）"),
    )

    def diagnose(self) -> str:
        """gst が落ちた理由の見立てを返す(見つからなければ空文字)."""
        if not self._errors:
            return ""
        out = ["", "=" * 60, "  gst-launch が停止しました。直近のメッセージ:", "=" * 60]
        out += ["  " + e for e in self._errors[-8:]]
        hits, seen = [], set()
        for line in self._errors:
            low = line.lower()
            for key, hint in self._HINTS:
                if key in low and hint not in seen:
                    seen.add(hint)
                    hits.append(hint)
        if hits:
            out += ["-" * 60, "  考えられる原因:"]
            out += [f"   ・{h}" for h in hits]
        out += ["-" * 60,
                "  ※ 映像出力が失敗すると、同じパイプライン内の音声取り込みも"
                "一緒に止まります(GPSが受からなくなります)。",
                "  ※ 入力側だけを切り分けるには check_signal.bat を実行してください。",
                "=" * 60, ""]
        return "\n".join(out)

    def wait(self):
        if self._proc:
            rc = self._proc.wait()
            if rc != 0:
                msg = self.diagnose()
                if msg:
                    self.on_log(msg)
                else:
                    self.on_log(f"\n[gst] 終了コード {rc} で停止しました。"
                                "上のログを確認してください。")

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
