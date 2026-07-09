"""調歩同期シリアル(UART)デコーダ.

NNNフォーマットのシリアル伝送ビット構成:
    スタートビット: 1bit (0)
    データ        : 7bit ASCII (LSBファースト)
    パリティ      : 1bit 偶数パリティ
    ストップビット: 1bit (1)

モデムのビット列は文字が隙間なく連続するため、文字同期を失うと
「次の0を探す」だけの再同期では誤った位置にロックし続けることがある。
そこでビットバッファを持ち、検証(パリティ+ストップビット)に失敗したら
スタートビット候補の1bit先から再走査するバックトラック方式とする。
"""

from __future__ import annotations

from dataclasses import dataclass

CHAR_BITS = 10  # start + 7data + parity + stop


@dataclass
class UartByte:
    value: int          # 7bitデータ
    parity_ok: bool
    framing_ok: bool


class UartDecoder:
    """ビット列から7bitデータを取り出す(バックトラック再同期付き)."""

    def __init__(self):
        self._bits: list[int] = []
        self.error_count = 0
        # 無信号区間の雑音ビットで延々エラーを数えないよう、
        # 直近に正常文字を受信した直後のバックトラックのみ計上する
        self._bits_since_good = 10 ** 9

    def reset(self) -> None:
        self._bits.clear()
        self._bits_since_good = 10 ** 9

    def process(self, bits: list[int]) -> list[UartByte]:
        self._bits.extend(bits)
        out: list[UartByte] = []
        buf = self._bits
        pos = 0
        n = len(buf)
        while True:
            # スタートビット(0)を探す
            while pos < n and buf[pos] != 0:
                pos += 1
            if n - pos < CHAR_BITS:
                break  # ビット不足: 次回に持ち越し
            data = 0
            for i in range(7):
                data |= (buf[pos + 1 + i] & 1) << i
            parity_bit = buf[pos + 8]
            stop_bit = buf[pos + 9]
            parity_ok = parity_bit == (bin(data).count("1") & 1)
            framing_ok = stop_bit == 1
            if parity_ok and framing_ok:
                out.append(UartByte(data, True, True))
                pos += CHAR_BITS
                self._bits_since_good = 0
            else:
                # 同期ずれの可能性 → 1bit先から再走査
                if self._bits_since_good < 3 * CHAR_BITS:
                    self.error_count += 1
                self._bits_since_good += 1
                pos += 1
        del buf[:pos]
        return out
