# ヘリGPS音声デコーダ (NNN系列統一フォーマット)

ヘリコプター映像システムの音声チャンネルに重畳された GPSエンコーダ
(日立国際電気 TC-GE30N 等) のMSK変調音声を、PCのキャプチャボード/
サウンドデバイスから取り込んでリアルタイム復調し、ヘリコプターの
位置(緯度・経度・高度)を表示するアプリケーションです。

```
ヘリ側: GPS受信機 → RS232C(2400bps) → GPSエンコーダ → MSK音声(1200bps)
        → 映像(1080i)の音声chに重畳 → FPU伝送
地上側: 受信映像 → キャプチャボード → 音声入力 → 本アプリ → 位置表示
```

映像(1080i)自体はデコードに関与しません。キャプチャボードの音声が
Windowsの録音デバイスとして見えていれば、それをそのまま入力にできます。

## 対応仕様 (添付仕様書に準拠)

| 項目 | 内容 |
|---|---|
| 変調方式 | MSK (CMX469A互換)。1200bps: 1200Hz/1800Hz、2400bps: 1200Hz/2400Hz |
| モデムビットレート | 1200bps (既定) / 2400bps 切替可 |
| シリアル構成 | スタート1bit + データ7bit ASCII + 偶数パリティ1bit + ストップ1bit |
| フレーム | Dummy(55h)×3 + STX(02h) + ID(2byte) + DATA(20byte) + ETX(03h) + BCC |
| BCC | ID〜ETXのXOR(水平パリティ) |
| DATA | ステータス4 + 緯度6桁(度分秒) + 経度7桁(度分秒) + 高度3桁(×10m) |
| 測地系 | 東京測地系 → WGS84へ変換して表示(国土地理院1次式近似、誤差数m) |
| 有効範囲 | 北緯20〜50度、東経120〜150度、高度0〜4000m (範囲外は警告表示) |
| エラー対策 | パリティ/BCC/フレームエラー時はデータを無効とし前回値を保持 |

## セットアップ (Windows / macOS / Linux)

Python 3.10以降が必要です。

```
pip install numpy sounddevice
```

WAVファイルのオフライン復調だけなら `numpy` のみで動きます。

## 使い方

### 1. GUI (リアルタイム受信)

```
python -m nnn_decoder.app
```

1. 「音声デバイス」でキャプチャボードの音声入力を選択
2. チャンネル(GPS音声が乗っているch: left/right/mix)とビットレート(通常1200)を選択
3. 「受信開始」

- 測位状態を色付きで表示(緑=正常測位 / 黄=バックアップ / 赤=使用不能・受信途絶)
- 緯度経度(WGS84・度分秒/10進度)、高度、PDOP、衛星数、局IDを表示
- **住所変換**: 同梱の市区町村境界データで**オフライン判定**(ネット不要)。
  町丁目まで必要な場合のみ国土地理院APIモードを選択
- 「地図(オフライン)」で同梱データによる地図に現在位置を表示(ネット不要)
- 「CSVログ保存」で受信履歴をCSV保存
- 「NMEAをUDP送出」でGGA/RMCセンテンスを `127.0.0.1:10110` へ送出
  (OpenCPN・gpsd等の地図ソフトでそのまま航跡表示できます)
- 「OSC送出」で位置・住所を `127.0.0.1:9000` へ送出(TouchDesigner連携用)

### 2. CLI (WAV/映像ファイルの復調)

収録済み素材や録音からの位置ログ復元に使えます。
WAVのほか、音声トラックを含む映像ファイル(MP4/MPEG-TS/MXF/MOV等)を
直接指定できます(ffmpegがPATHにあること。音声を自動抽出します)。

```
python -m nnn_decoder.cli 録音.wav --channel left --csv 位置ログ.csv
python -m nnn_decoder.cli 収録.mp4 --channel right
python -m nnn_decoder.cli 収録.mp4 --channel 3       # 多ch素材の3ch目(1始まり)
python -m nnn_decoder.cli 収録.ts --audio-stream 1   # 2本目の音声トラック
```

多チャンネルLPCM素材(SDIエンベデッド音声のキャプチャ等)にも対応して
います。WAVはWAVE_FORMAT_EXTENSIBLE(3ch以上でVLC/ffmpegが出力する形式)
も直接読めます。素材を小さくして受け渡す場合は、音声だけを
チャンネル数を維持したまま抜き出すのが確実です:

```
ffmpeg -i 収録.mp4 -vn -acodec pcm_s16le 音声のみ.wav   # 全ch維持で音声抽出
ffmpeg -i 収録.mp4 -vn -acodec flac 音声のみ.flac       # ロスレス圧縮で容量半減
```

MSKトーン(1.2〜2.4kHz)は音声圧縮に強く、AAC 48kbpsやMPEG-1 Layer2に
圧縮された収録素材でも復調できることを確認済みです。

### 3. テスト音声の生成 (実機なしでの動作確認)

```
python -m nnn_decoder.modulator test.wav --seconds 10
python -m nnn_decoder.cli test.wav
```

生成したWAVを再生してライン入力にループバックすれば、GUIの
エンドツーエンド確認もできます。

## 性能

- 復調余裕: 1200bpsでSNR約3dBまで完全復調(白色雑音試験)。FPU音声回線の
  実運用SNRに対して十分な余裕があります
- 処理速度: 実時間の約30倍(48kHzサンプリング時)。リアルタイム処理は余裕です

## 構成

```
nnn_decoder/
  demod.py      MSK復調器(直交相関 + ヒステリシス付き軟判定 + ギアシフトDPLL)
  uart.py       調歩同期デコーダ(バックトラック再同期付き)
  packet.py     NNNフレームパーサ(BCC検証・有効範囲チェック・前回値保持)
  geodesy.py    度分秒変換・東京測地系→WGS84変換
  pipeline.py   音声→位置 の一気通貫ストリーミングパイプライン
  modulator.py  エンコーダシミュレータ(試験用MSK音声生成)
  nmea.py       NMEA 0183 (GGA/RMC) 生成・UDP送出
  geocode.py    逆ジオコーディング(オフライン境界判定/地理院APIの両対応)
  osc.py        OSC送出 (TouchDesigner等への連携)
  app.py        GUIアプリケーション (tkinter)
  cli.py        WAV/映像ファイル復調CLI (--address で住所付き)
touchdesigner/  SDI入力→住所テロップ→1080i Fill&Key出力 の連携一式
                (セットアップガイド: touchdesigner/README_TD.md)
tests/          変調→復調ラウンドトリップ試験(雑音・分割・破損フレーム含む)
```

## SDIテロップ送出 (UltraStudio → 1080i Fill&Key)

UltraStudioのSDI入力(EMB音声)からGPSを復調し、市区町村テロップを
1080iのFill&KeyでSDI出力する。2通りの構成があります。

- **GStreamer版（TouchDesigner不要・推奨）**: `gst_heli/README_GST.md`。
  Python + GStreamer(LGPL) + Desktop Video のみ。PyGObject不要
  （gst-launchをサブプロセス使用）。実機で入出力とも検証済み。
  制御は `control_ui.py`（フォント/中・フチ2色/太さ/ドラッグ配置）
- **TouchDesigner版**: `touchdesigner/README_TD.md`。TD上でテロップを描画・出力

## 住所変換の仕様

- 既定は**オフラインモード**: 同梱の市区町村境界データ(約420KB)で
  点内判定するため、**インターネット接続なしで市区町村名が出ます**
  (判定5µs/回、GSI APIとの一致率95%・相違は境界近傍のみを確認済み)
- `auto`/`online`モードでは国土地理院APIで町丁目まで補完できます
- 境界データ出典: 「国土数値情報(行政区域データ)」(国土交通省)を
  スマートニュース メディア研究所が簡略化したもの
  (https://github.com/smartnews-smri/japan-topography)を再加工。
  市区町村コード表は国土地理院 地理院地図のmuni.jsに基づきます

## テスト実行

```
pip install pytest
python -m pytest tests/
```

## 実機投入時の確認ポイント

- キャプチャボードの音声入力レベル: GUIのレベルメータが振れること
  (エンコーダ出力は-10dBm。小さすぎ/クリップどちらも避ける)
- GPS音声がどちらのchに乗っているか(L/R)
- エンコーダの速度設定(1200/2400)とアプリのビットレート設定を一致させる
- 万一マーク/スペースが逆の系がある場合はCLIの `--invert` で確認可能
