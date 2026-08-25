# GStreamer版 ヘリGPSスーパー送出（TouchDesigner不要）

SDIエンベデッド音声からGPSを復調し、市区町村テロップを **Fill&Key で SDI出力** する
スタンドアロン構成。専用ソフト不要で、**Python + GStreamer(LGPL) + Blackmagic
Desktop Video** のみで動作する。

```
SDI IN → decklinkaudiosrc(EMB音声ch3) → 復調 → 住所変換(オフライン)
       → Pillowでテロップ描画(RGBA) → decklinkvideosink(keyer=external)
       → SDI OUT (Fill/Key 2系統) → スイッチャーDSK
```

映像本線はこのアプリを通らない。アプリはFillとKeyの2系統だけ出し、スイッチャーの
DSKで本線に重ねる。**PyGObject不要**（`gst-launch-1.0`をサブプロセスとして使う）。

> 実機（UltraStudio HD Mini）で入力=SDI音声→住所、出力=1080i Fill&Key の
> 両方を検証済み。以下の値・手順はその確認に基づく。

---

## 1. セットアップ

### 1-1. Python と依存
- Python 3.10+（インストール時「Add Python to PATH」を有効化）
- 依存パッケージ:
  ```
  cd C:\heli_gps
  pip install numpy pillow
  ```
  （`gst_heli` は標準ライブラリ + numpy + Pillow のみ。PyGObjectは**不要**）

### 1-2. GStreamer ランタイム
1. https://gstreamer.freedesktop.org/download/ から
   **MSVC 64-bit の runtime installer** を入手し、**Setup Type=Complete** で
   インストール（decklinkプラグインが含まれる）
2. 既定インストール先は `C:\Program Files\gstreamer\1.0\msvc_x86_64\bin`
3. **確認**（この2つが通ればOK）:
   ```
   set "PATH=C:\Program Files\gstreamer\1.0\msvc_x86_64\bin;%PATH%"
   gst-launch-1.0 --version
   gst-inspect-1.0 decklinkvideosink
   ```
   `decklinkvideosink` の情報が出れば decklinkプラグインあり＝合格。
4. 毎回 set したくなければ、Windowsの「環境変数 → システム環境変数 Path」に
   上記 bin を追加して恒久化する。

### 1-3. Blackmagic Desktop Video
- UltraStudio/DeckLink のドライバを最新版にインストール。
- **REF IN に本線と同じ同期信号（59.94系のブラックバースト/3値シンク）を接続**。
  Fill&Key出力はゲンロック必須（無いと出力がスケジュールできない）。

---

## 2. 段階的な立ち上げ（実機・推奨順）

いきなり本番アプリを動かす前に、経路を分けて確認すると安全。
すべて `C:\heli_gps` で、事前に `set "PATH=…gstreamer…\bin;%PATH%"` を実行。

### 手順A. 音声→復調（入力側の確認）
DeckLinkは**音声取得に映像入力の同時起動が必須**なので、映像も同時に開く。
5秒ほどで Ctrl+C（`-e`でWAVが閉じる）:
```
gst-launch-1.0 -e decklinkvideosrc connection=sdi mode=auto device-number=0 ! fakesink  decklinkaudiosrc connection=embedded channels=8 do-timestamp=true device-number=0 ! audioconvert ! wavenc ! filesink location=cap.wav
```
```
python -m nnn_decoder.cli cap.wav --channel 3 --address
```
→ 「◯◯県◯◯市…」等が出れば入力〜復調OK。（GPSは通常 EMB CH3＝`--channel 3`）

### 手順B. 映像出力（Fill&Key）の確認
実際のテロップ静止画をPythonが供給し、Fill&Keyで出す単体テスト:
```
python -m gst_heli.outtest --text "テスト 千葉県君津市上空"
```
→ **SDI OUT 1=Fill / 2=Key** に文字が出れば出力OK（Ctrl+Cで終了）。

### 手順B'. 見た目プレビュー（PC画面で確認）
SDI出力せず、**入力SDI映像にテロップを重ねたものをPCのウィンドウに表示**する。
REF不要。制御UIで見た目を追い込むのに使う:
```
python -m gst_heli.preview --osc-control --channel 2
python control_ui.py
```
または `start_heli_preview.bat` をダブルクリック。
※SDIデバイスは1プロセスしか入力を開けないため、**本番送出(手順C)とは
  同時に実行できない**（プレビューで詰めてから本番へ）。

### 手順C. 本番（入力+出力 同時）
```
python -m gst_heli.app --source decklink --output decklink --osc-control --channel 2
python control_ui.py
```
または `start_heli_gst.bat` をダブルクリック。
→ 実ヘリGPS音声から住所テロップをFill&Key出力しつつ、制御UIで見た目を調整。

---

## 3. 実機で確定した出力パラメータ（1080i59.94）

`gst_heli` はこの値で組んである（`gst_subprocess.py`）。手動テスト時の参考:

| 項目 | 値 | 備考 |
|---|---|---|
| mode | `1080i5994` | 出力信号フォーマット |
| framerate | `30000/1001` | 29.97（1080iのフレーム） |
| interlace化 | `capssetter join=false … interlace-mode=interleaved` | rawvideoparseはprogressiveのみ→ラベル差し替えでBGRA(アルファ=Key)を保持したまま1080i化 |
| video-format | `8bit-bgra` | アルファがKeyになる |
| keyer-mode | `external` | Fill&Key 2系統 |
| sync | **付けない**（既定sync=true） | `sync=false`だと`Failed to schedule frame`になる |
| 音声 | `decklinkaudiosrc connection=embedded channels=8` | **decklinkvideosrcの同時起動が必須** |

> 1080p運用でよければ `--mode 1080p2997 --no-interlace` でも出力可能。

---

## 4. 一括起動バッチ（2つの出力モード）

出力方式は2種類。UIは共通（同じOSC制御）で、**起動バッチで選ぶ**。

| バッチ | 出力方式 | 用途 | キーヤー |
|---|---|---|---|
| `start_heli_gst.bat` | **Fill/Key** | 外部スイッチャー/キーヤーで合成 | 外部キーヤー必須 |
| `start_heli_burnin.bat` | **バーンイン** | 入力映像+音声にテロップを焼き込み、**1本のSDIで出力** | 不要 |

**heli_gps 直下**（control_ui.py と同じ階層）に置いてダブルクリックすると、
送出本体と制御UIが同時に起動する。バッチ冒頭の変数（CHANNEL/MODE/VMODE/
デバイス番号、`GST1/GST2` のGStreamerパス）を環境に合わせる。送出本体は
コンソール付き（`cmd /k`）で、異常時にログが見える。

- **切替について**: 出力方式はパイプライン構造が異なるため、起動時に選ぶ。
  UI上での動的切替は「一度停止→別モードで再起動」となり、切替時に1〜2秒の
  出力途切れが出る（放送は起動時に決める運用を推奨）。
- **バーンインの前提**: 入出力同時（フルデュプレックス）対応のDeckLinkと
  基準同期(REF)が必要。A/Vずれは `--av-offset-ms`（+で音声を遅らせる）で補正。
  1080iはインタレースのまま重畳する既定。品質次第で `--deinterlace` も可。
  ※実機でA/V同期・1080i品質の確認/微調整が必要。

---

## 5. 制御UI（control_ui.py）

送出本体を `--osc-control` で起動し、`python control_ui.py` を別に立てると、
OSC(127.0.0.1)経由でライブ操作できる。

- **住所**: 変換モード / 粒度(市町村・政令市は市まで 等) / GPS音声ch / 表示書式
- **見た目**: フォント(実在ファイルから選択) / 文字サイズ / **文字色(中)** と
  **フチ色** を別々 / **フチの太さ**
- **配置**: 16:9プレビュー上で**ドラッグ&ドロップ**位置指定（矢印キー微調整）
- **状態表示**: 受信中/途絶・現在のスーパー・緯度経度・測位状態をライブ表示

---

## 6. ハード無しでの確認（開発・デモ用）

GStreamer/DeckLinkが無くても、UIとロジックは確認できる:
```
rem テスト音声(1chのGPS音声)を生成
python -m nnn_decoder.modulator test.wav --seconds 30 --mono

rem WAV→プレビューPNG(住所テロップが out\ に出る)。制御UIにも状態が出る
python -m gst_heli.app --source wav --wav test.wav --output preview ^
    --preview-dir out --channels 1 --channel 0 --realtime --osc-control
python control_ui.py
```

---

## 7. トラブルシューティング

| 症状 | 対処 |
|---|---|
| `gst-launch-1.0 … 認識されません` | PATH未設定。`set "PATH=…gstreamer…\bin;%PATH%"` |
| 音声が録れない/`Audio src needs a video src` | 手順Aのように`decklinkvideosrc`を同時に動かす（必須仕様） |
| 出力が`not-negotiated (-4)` | interlace化のcaps不整合。`gst_heli`は`capssetter join=false`で対応済み。手動時は §3 の値に合わせる |
| 出力が`Failed to schedule frame 0x80004005` | ①`sync=false`を付けない ②**REF IN**に同期信号が入っているか |
| 文字が「□□□」/フォント変更で消える | 制御UIでインストール済み日本語フォントを選ぶ（実ファイル指定なので消えない） |

---

## 8. ライセンス / 製品化（LGPL）

- GStreamer本体・使用プラグイン（coreelements/app/tcp/rawparse/decklink/
  videoconvertscale/audioconvert）は**すべてLGPL**。自社Pythonコードは
  サブプロセス/動的利用のため**非公開のまま製品化できる**
- **GPLなコーデック系プラグイン（x264等）は使用しない**（本構成はraw音声・
  raw映像とdecklink要素のみ）
- GStreamerは製品同梱せず「前提ソフトとして別途インストール」にすると、
  LGPLの実務負担は表記のみで済む
- サードパーティ表記は `../THIRD_PARTY_NOTICES.md` を参照
- 最終的なEULA・表記は社内法務の確認を推奨（本記載は法的助言ではない）
