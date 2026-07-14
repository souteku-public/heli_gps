"""GStreamer入出力 — SDIエンベデッド音声取得 と Fill&Key SDI出力.

GStreamer(PyGObject)が無い環境ではimportに失敗するため、
呼び出し側は try/except で ファイル/プレビューのフォールバックに切り替える。

使用プラグイン(ホワイトリスト): coreelements, app, decklink, videoconvertscale,
audioconvert。いずれもLGPL。GPLなコーデック系プラグインは使用しない。
"""

from __future__ import annotations

import numpy as np

# GStreamer本体(無い環境ではImportError)
import gi  # noqa: E402
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

_INITED = False


def _ensure_init():
    global _INITED
    if not _INITED:
        Gst.init(None)
        _INITED = True


class DecklinkAudioIn:
    """decklinkaudiosrc → appsink でSDIエンベデッド音声を取得し、
    コールバックへ (interleaved_float32, nchannels) を渡す。"""

    def __init__(self, device_number: int = 0, channels: int = 8,
                 rate: int = 48000, on_samples=None):
        _ensure_init()
        self.channels = channels
        self.rate = rate
        self.on_samples = on_samples
        # F32LE・指定chでappsinkに引き出す(コーデック無し=LGPLのみ)
        desc = (
            f"decklinkaudiosrc device-number={device_number} "
            f"connection=embedded channels={channels} ! "
            f"audioconvert ! "
            f"audio/x-raw,format=F32LE,channels={channels},rate={rate},"
            f"layout=interleaved ! "
            f"appsink name=asink emit-signals=true max-buffers=8 drop=true sync=false"
        )
        self.pipeline = Gst.parse_launch(desc)
        self.appsink = self.pipeline.get_by_name("asink")
        self.appsink.connect("new-sample", self._on_sample)

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                arr = np.frombuffer(mapinfo.data, dtype=np.float32)
                if self.on_samples is not None and arr.size:
                    self.on_samples(arr, self.channels)
            finally:
                buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)


class DecklinkFillKeyOut:
    """appsrc → decklinkvideosink(keyer=external)でFill&Key出力.

    push(rgba_ndarray) で 1080 RGBA フレームを送る。alphaがKeyになる。
    """

    def __init__(self, frame_provider, device_number: int = 0,
                 mode: str = "1080i5994", width: int = 1920, height: int = 1080,
                 fps_n: int = 60000, fps_d: int = 1001, keyer: str = "external"):
        """frame_provider: 現在表示すべき RGBA(H,W,4) uint8 を返す関数.

        appsrc の need-data(sink のクロックに追従)で毎フレーム呼ばれる。
        テロップは静止画に近いので、呼ばれるたび最新のキャッシュ画像を返せばよい。
        """
        _ensure_init()
        self.width, self.height = width, height
        self.frame_provider = frame_provider
        # BGRAでappsrc → videoconvert → decklinkvideosink。
        # keyer-mode=external でFill&Key、mode で信号フォーマット指定。
        desc = (
            f"appsrc name=vsrc is-live=true format=time block=true "
            f"caps=video/x-raw,format=BGRA,width={width},height={height},"
            f"framerate={fps_n}/{fps_d} ! "
            f"videoconvert ! "
            f"decklinkvideosink device-number={device_number} "
            f"video-format=8bit-bgra mode={mode} keyer-mode={keyer} sync=false"
        )
        self.pipeline = Gst.parse_launch(desc)
        self.appsrc = self.pipeline.get_by_name("vsrc")
        self._dur = Gst.util_uint64_scale_int(Gst.SECOND, fps_d, fps_n)
        self._pts = 0
        self.appsrc.connect("need-data", self._on_need_data)

    def _on_need_data(self, src, length):
        rgba = self.frame_provider()
        if rgba is None:
            rgba = np.zeros((self.height, self.width, 4), dtype=np.uint8)
        bgra = np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]]).tobytes()
        buf = Gst.Buffer.new_wrapped(bgra)
        buf.pts = self._pts
        buf.duration = self._dur
        self._pts += self._dur
        src.emit("push-buffer", buf)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        try:
            self.appsrc.emit("end-of-stream")
        except Exception:
            pass
        self.pipeline.set_state(Gst.State.NULL)


def main_loop() -> "GLib.MainLoop":
    return GLib.MainLoop()
