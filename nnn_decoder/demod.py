"""MSK(FSK)復調器.

GPSエンコーダ TC-GE30N はCMX469A MSKモデム(4.032MHzクロック)を使用する。
トーン周波数(CMX469A標準):
    1200bps: マーク(論理1)=1200Hz / スペース(論理0)=1800Hz
    2400bps: マーク(論理1)=1200Hz / スペース(論理0)=2400Hz

復調方式:
    マーク/スペース各トーンとの直交相関(1ビット長の移動平均窓)を取り、
    振幅比較で軟判定値を得る(入力レベルに依存しない)。
    ビット同期はデータ遷移でクロック位相を引き込むDPLL。
"""

from __future__ import annotations

import numpy as np

TONES = {
    # baud: (f_mark, f_space)
    1200: (1200.0, 1800.0),
    2400: (1200.0, 2400.0),
}


class MSKDemodulator:
    """ストリーミングMSK復調器. process()にfloat配列を渡すとビット列を返す."""

    def __init__(
        self,
        fs: float,
        baud: int = 1200,
        f_mark: float | None = None,
        f_space: float | None = None,
        invert: bool = False,
        pll_gain: float = 0.15,
    ):
        if f_mark is None or f_space is None:
            if baud not in TONES:
                raise ValueError(f"baud {baud} には f_mark/f_space の指定が必要です")
            f_mark, f_space = TONES[baud]
        self.fs = float(fs)
        self.baud = int(baud)
        self.f_mark = float(f_mark)
        self.f_space = float(f_space)
        self.invert = invert
        self.spb = self.fs / self.baud  # samples per bit
        self.win = max(2, int(round(self.spb)))  # 相関窓 = 1ビット長

        self.pll_gain = float(pll_gain)
        self._clk = 0.0          # ビットクロック位相 [0,1)
        self._clk_inc = self.baud / self.fs
        self._prev_sign = 0
        self._sampled = False    # このビット周期で判定済みか
        self._env = 0.0          # |軟判定値|のエンベロープ(ヒステリシス閾値用)
        self._env_gain = 4.0 / self.spb  # 数ビットの時定数
        self.hysteresis = 0.15   # エンベロープに対する閾値比

        # ギアシフトDPLL: 送受ともクロックは水晶精度で周波数誤差は無視できる。
        # 未ロック時は高ゲインで位相を引き込み、ロック後は低ゲインにして
        # ノイズによる遷移タイミングジッタで位相が乱歩しないようにする。
        self.pll_gain_locked = 0.02
        self._lock = 0           # ロック品質カウンタ (0〜20)

        # 相関器の位相を継続させるためのサンプル通し番号
        self._n0 = 0
        # 移動平均のためのオーバーラップ保存
        self._tail = np.zeros(0, dtype=np.float64)

    def _soft_decisions(self, x: np.ndarray) -> np.ndarray:
        """各サンプル時点の軟判定値(正=マーク, 負=スペース)を返す."""
        n = np.arange(self._n0, self._n0 + len(x), dtype=np.float64)
        soft_parts = []
        w = self.win
        kernel = np.ones(w) / w
        mags = []
        for f in (self.f_mark, self.f_space):
            ph = 2.0 * np.pi * f / self.fs * n
            i = x * np.cos(ph)
            q = x * np.sin(ph)
            # 1ビット窓の移動平均(直交相関)
            im = np.convolve(i, kernel, mode="full")[: len(x)]
            qm = np.convolve(q, kernel, mode="full")[: len(x)]
            mags.append(im * im + qm * qm)
        soft = mags[0] - mags[1]
        return soft

    def process(self, samples: np.ndarray) -> list[int]:
        """音声サンプル(float, 任意レベル)を復調しビット(0/1)のリストを返す."""
        x = np.asarray(samples, dtype=np.float64)
        if x.ndim != 1:
            raise ValueError("mono 1ch のサンプル列を渡してください")
        if len(x) == 0:
            return []

        # 前ブロック末尾を連結して移動平均の境界劣化を避ける
        joined = np.concatenate([self._tail, x])
        n_tail = len(self._tail)
        self._n0 -= n_tail
        soft = self._soft_decisions(joined)
        self._n0 += len(joined)
        keep = min(len(joined), self.win - 1)
        self._tail = joined[len(joined) - keep :].copy()
        # 今回新規に確定する区間(前回処理済みぶんを除く)
        soft = soft[n_tail:]

        bits: list[int] = []
        clk = self._clk
        inc = self._clk_inc
        gain = self.pll_gain
        prev = self._prev_sign
        sampled = self._sampled
        env = self._env
        env_gain = self._env_gain
        hyst = self.hysteresis

        for s in soft:
            a = abs(s)
            env += env_gain * (a - env)
            th = hyst * env
            # ヒステリシス付き符号判定: ノイズによる零交差近傍の
            # チャタリングでDPLLが引きずられてビットスリップするのを防ぐ
            if prev == 0:
                prev = 1 if s >= 0.0 else -1
                transition = False
            elif prev > 0 and s < -th:
                prev = -1
                transition = True
            elif prev < 0 and s > th:
                prev = 1
                transition = True
            else:
                transition = False

            if transition:
                # 遷移はクロック位相0で起こるはず → 位相を0へ引き込む
                err = clk if clk < 0.5 else 1.0 - clk
                if err < 0.12:
                    self._lock = min(self._lock + 1, 20)
                else:
                    self._lock = max(self._lock - 4, 0)
                g = self.pll_gain_locked if self._lock >= 8 else gain
                if clk < 0.5:
                    clk -= g * clk
                else:
                    clk += g * (1.0 - clk)

            clk += inc
            if clk >= 1.0:
                clk -= 1.0
                sampled = False
            if not sampled and clk >= 0.5:
                bit = 1 if prev > 0 else 0
                if self.invert:
                    bit ^= 1
                bits.append(bit)
                sampled = True

        self._clk = clk
        self._prev_sign = prev
        self._sampled = sampled
        self._env = env
        return bits
