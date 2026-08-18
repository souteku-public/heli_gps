"""音声サンプル → 位置パケット の一気通貫パイプライン."""

from __future__ import annotations

import numpy as np

from .demod import MSKDemodulator
from .packet import NNNPacket, NNNPacketParser
from .uart import UartDecoder


class DecoderPipeline:
    """MSK復調 → UART → NNNパース をまとめたストリーミングデコーダ."""

    def __init__(self, fs: float, baud: int = 1200, invert: bool = False,
                 datum: str = "wgs84"):
        self.demod = MSKDemodulator(fs, baud=baud, invert=invert)
        self.uart = UartDecoder()
        self.parser = NNNPacketParser(datum=datum)

    def process(self, samples: np.ndarray) -> list[NNNPacket]:
        bits = self.demod.process(samples)
        chars = self.uart.process(bits)
        good = bytes(c.value for c in chars if c.parity_ok and c.framing_ok)
        return self.parser.feed(good)

    @property
    def stats(self) -> dict:
        return {
            "packets_ok": self.parser.packets_ok,
            "packets_error": self.parser.packets_error,
            "uart_errors": self.uart.error_count,
            "last_error": self.parser.last_error,
        }
