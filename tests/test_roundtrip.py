"""変調→復調のラウンドトリップ試験.

実機エンコーダの代わりに modulator.py で仕様どおりのMSK音声を生成し、
復調パイプラインが正しく位置を取り出せることを確認する。
"""

import numpy as np
import pytest

from nnn_decoder.modulator import encode_position_to_audio
from nnn_decoder.pipeline import DecoderPipeline

FS_LIST = [48000, 44100, 32000]


def _decode_all(audio, fs, baud=1200, block=4096):
    pipe = DecoderPipeline(fs, baud=baud)
    pkts = []
    for i in range(0, len(audio), block):
        pkts.extend(pipe.process(audio[i : i + block]))
    return pkts, pipe


@pytest.mark.parametrize("fs", FS_LIST)
@pytest.mark.parametrize("baud", [1200, 2400])
def test_clean_roundtrip(fs, baud):
    audio = encode_position_to_audio(
        fs, baud=baud, station_id="01", fix_status=0, pdop=2, satellites=8,
        lat_dms="354027", lon_dms="1394510", alt_m=500)
    pkts, _ = _decode_all(audio, fs, baud=baud)
    assert len(pkts) == 1
    p = pkts[0]
    assert p.station_id == "01"
    assert p.fix_status == 0
    assert p.pdop == 2
    assert p.satellites == 8
    # 生値(復号したDDMMSS): 35°40'27" / 139°45'10"
    assert abs(p.lat_tokyo - (35 + 40 / 60 + 27 / 3600)) < 1e-9
    assert abs(p.lon_tokyo - (139 + 45 / 60 + 10 / 3600)) < 1e-9
    assert p.alt_m == 500
    assert p.in_range
    # 既定(datum=wgs84)は変換しない: 生値=WGS84
    assert p.lat_wgs84 == p.lat_tokyo
    assert p.lon_wgs84 == p.lon_tokyo


def test_tokyo_datum_conversion():
    """datum='tokyo' 指定時のみ東京測地系→WGS84変換が働くこと."""
    fs = 48000
    audio = encode_position_to_audio(
        fs, lat_dms="354027", lon_dms="1394510", alt_m=500)
    pipe = DecoderPipeline(fs, datum="tokyo")
    pkts = []
    for i in range(0, len(audio), 4096):
        pkts.extend(pipe.process(audio[i : i + 4096]))
    assert len(pkts) == 1
    p = pkts[0]
    # 東京測地系→WGS84で北東へ約11-12秒ずれる(東京付近)
    assert 0.002 < (p.lat_wgs84 - p.lat_tokyo) < 0.004
    assert -0.004 < (p.lon_wgs84 - p.lon_tokyo) < -0.002


def test_noisy_roundtrip():
    """SNR約10dBの白色雑音+レベル変動下でも復調できること."""
    fs = 48000
    rng = np.random.default_rng(1)
    pkts_total = 0
    n_frames = 10
    for k in range(n_frames):
        audio = encode_position_to_audio(
            fs, baud=1200, station_id="0A", fix_status=0, pdop=3, satellites=7,
            lat_dms="354027", lon_dms="1394510", alt_m=800, amplitude=0.3)
        noise = rng.normal(0, 0.09, len(audio))  # SNR ~10dB
        pkts, _ = _decode_all((audio + noise) * (0.5 + 0.5 * (k % 2)), fs)
        pkts_total += sum(1 for p in pkts if p.alt_m == 800)
    assert pkts_total >= 8  # 9割方通れば実用十分


def test_continuous_stream_with_gaps():
    """パケット間に無音・雑音区間があっても連続復調できること."""
    fs = 48000
    rng = np.random.default_rng(2)
    parts = []
    for i in range(3):
        parts.append(rng.normal(0, 0.02, fs // 2))  # 雑音のみ0.5秒
        parts.append(encode_position_to_audio(
            fs, lat_dms=f"35402{i}", lon_dms="1394510", alt_m=100 * (i + 1)))
    audio = np.concatenate(parts)
    pkts, pipe = _decode_all(audio, fs)
    assert len(pkts) == 3
    assert [p.alt_m for p in pkts] == [100, 200, 300]


def test_corrupted_frame_rejected():
    """BCC破壊されたフレームは棄却され、正常フレームだけ通ること."""
    fs = 48000
    good = encode_position_to_audio(fs, alt_m=500)
    bad = encode_position_to_audio(fs, alt_m=990)
    # bad の音声中央部を破壊(データ化け→パリティ/BCCエラー)
    bad = bad.copy()
    mid = len(bad) // 2
    bad[mid : mid + 400] = 0.0
    audio = np.concatenate([bad, np.zeros(1000), good])
    pkts, pipe = _decode_all(audio, fs)
    alts = [p.alt_m for p in pkts]
    assert 500 in alts
    assert 990 not in alts
