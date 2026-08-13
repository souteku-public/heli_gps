# GStreamer版 ヘリGPSスーパー送出（TouchDesigner不要）

SDIエンベデッド音声からGPSを復調し、市区町村テロップを**Fill&KeyでSDI出力**する
スタンドアロンアプリ。専用ソフト不要で、**Python + GStreamer(LGPL) + Blackmagic
Desktop Video** のみで動作する。

```
SDI IN → decklinkaudiosrc(EMB音声ch3) → 復調 → 住所変換(オフライン)
       → Pillowでテロップ描画(RGBA) → decklinkvideosink(keyer=external)
       → SDI OUT (Fill/Key 2系統) → スイッチャーDSK
```

映像本線はアプリを通らない。アプリはFillとKeyの2系統だけ出し、スイッチャーの
DSKで本線に重ねる（TouchDesigner版と同じ運用）。

## 必要なもの

| 項目 | 内容 |
|---|---|
| Python 3.10+ | numpy, Pillow, PyGObject(gi) |
| GStreamer 1.22+ ランタイム | 公式MSI(Windows)。`gst-plugins-bad`のdecklink要素を含む構成 |
| Blackmagic Desktop Video | UltraStudio/DeckLinkのドライバ |

## インストール（Windows）

1. **GStreamer** をインストール（MSVC版のランタイム＋開発版の両方推奨）
   - https://gstreamer.freedesktop.org/download/
   - 「Complete」構成を選ぶと decklink プラグインが入る
   - 環境変数 `GSTREAMER_1_0_ROOT_MSVC_X86_64` と PATH(bin) が通ること
2. **PyGObject**（GStreamerのPythonバインディング）
   ```
   pip install PyGObject
   ```
   （うまく入らない場合は GStreamer 同梱の Python か、`pipwin`/公式wheelを利用）
3. 本リポジトリの依存
   ```
   pip install numpy pillow
   ```
4. Blackmagic Desktop Video を最新版に

## 事前動作確認（gst-launch / Pythonアプリ前に）

Pythonの前に、GStreamer単体でDeckLinkが見えるか確認する。

```
rem 音声入力が取れるか（数秒でCtrl+C）
gst-launch-1.0 decklinkaudiosrc device-number=0 connection=embedded channels=8 ! audioconvert ! fakesink -v

rem 出力テスト: カラーバーをFill&Keyで出す（REF必須）
gst-launch-1.0 videotestsrc ! video/x-raw,format=BGRA,width=1920,height=1080 ! videoconvert ! decklinkvideosink device-number=0 mode=1080i5994 keyer-mode=external
```

デバイス一覧は `gst-device-monitor-1.0` で確認できる。

## バックエンド: PyGObject不要(既定) / PyGObject

- **subprocess(既定・推奨)**: `gst-launch-1.0` をサブプロセスとして起動し、
  音声/映像を localhost TCP でやり取りする。**PyGObjectのインストール不要**で、
  GStreamer本体だけあれば動く。Windows配布が容易
- **gi**: PyGObject(`import gi`)を使う方式。`--backend gi` で選択

`decklink`の音声取得には映像入力(decklinkvideosrc)の同時起動が必須
(実機で確認済み)。subprocess方式のパイプラインはこれを内蔵している。

## 段階的な立ち上げ(実機)

いきなり本番アプリを動かす前に、経路を分けて確認すると安全です。

1. **音声→復調**(gst-launchのみ。前掲):
   `decklinkvideosrc ! fakesink` と `decklinkaudiosrc ! … wavenc ! filesink` で
   録音 → `python -m nnn_decoder.cli cap.wav --channel 3 --address`
2. **映像出力(Fill&Key)**: 実際のテロップ静止画をPythonが供給する単体テスト:
   ```
   python -m gst_heli.outtest --text "テスト 千葉県君津市上空"
   ```
   REF接続で SDI OUT 1=Fill / 2=Key を確認(Ctrl+Cで終了)
3. **本番(入力+出力 同時)**:
   ```
   python -m gst_heli.app --source decklink --output decklink --osc-control --channel 2
   ```

## 実行

```
rem 本番: SDI入力 → Fill&Key出力、control_ui からの操作も受ける
python -m gst_heli.app --source decklink --output decklink --osc-control ^
    --channel 2 --mode 1080i5994 --keyer external

rem 制御UI(別窓・状態表示つき。TD版と共通)
python control_ui.py
```

### 一括起動(バッチ)

`start_heli_gst.bat` を **heli_gps 直下**(control_ui.py と同じ階層)に置いて
ダブルクリックすると、送出本体と制御UIが同時に起動します。
バッチ冒頭の変数(CHANNEL/MODE/KEYER/デバイス番号)を環境に合わせて調整してください。
GStreamerのbinがPATHに無い場合は、同バッチ内の `GST_BIN` の2行のremを外して
パスを設定します。

送出本体はコンソール付き(`cmd /k`)で起動し、エラーや状態が見えます。
本番で窓を出したくない場合は `cmd /k` を `cmd /c` に変更してください。

ハード無しでロジックを確認するには:
```
rem テスト音声を生成(1chのGPS音声。--channels 1 で読む)
python -m nnn_decoder.modulator test.wav --seconds 10 --mono
python -m gst_heli.app --source wav --wav test.wav --output preview ^
    --preview-dir out --channels 1 --channel 0 --duration 10
```
→ `out/super_*.png` に毎秒のテロップ画像が保存される。

## 主なオプション

| オプション | 意味 |
|---|---|
| `--channel N` | GPS音声チャンネル(0始まり。EMBのCH3なら2) |
| `--mode` | 信号フォーマット(例 1080i5994) |
| `--keyer external` | Fill&Key(2系統)。`internal`=本線に内部合成、`off`=Fillのみ |
| `--geo-mode` | offline(既定・ネット不要) / auto / online |
| `--addr-level` | pref / muni(政令市は市まで) / city / town |
| `--osc-control` | control_ui.py からのライブ操作を受ける(ポート9001) |

## 制御UI(control_ui.py)の操作

`--osc-control` を付けて起動すると、`control_ui.py` から以下をライブ操作できます:

- **住所**: 変換モード / 粒度 / ビットレート / GPS音声ch / 表示書式 / 受信途絶時表示
- **見た目**:
  - **フォント**: 実在するフォントファイルから選択(名前推測をやめたので
    「選ぶと消える」が起きない)
  - **文字色(中)** と **フチ色** を別々に指定
  - **文字サイズ** / **フチの太さ** をスライダーで
- **配置**: 16:9プレビュー上で**文字をドラッグ&ドロップ**して位置決め
  (矢印キーで微調整、Shiftで10px)
- **受信状態**: 受信中/途絶・現在のスーパー・緯度経度・測位状態をライブ表示

## リファレンス(REF)について

BlackmagicのKey/Fill出力は**REF IN(ゲンロック)必須**。局のブラックバースト/
3値シンクをUltraStudioのREF INへ接続すること。無いと出力が出ない。

## ライセンス / 配布(製品化)

- GStreamer本体・PyGObject・使用プラグイン(coreelements/app/decklink/
  videoconvertscale/audioconvert)は**すべてLGPL**。自社Pythonコードは
  動的利用のため非公開のまま製品化できる
- **GPLなコーデック系プラグイン(x264等)は使用しない**(本パイプラインはraw音声・
  raw映像とdecklink要素のみ)。配布時もそれらを同梱しない
- GStreamerは製品同梱せず「前提ソフトとして別途インストール」にすると、LGPLの
  ソース提供義務が実務上ほぼ表記のみで済む
- サードパーティ表記は `THIRD_PARTY_NOTICES.md` を参照
- 最終的なEULA・表記は社内法務の確認を推奨(本記載は法的助言ではない)
