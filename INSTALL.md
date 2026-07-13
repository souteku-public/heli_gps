# インストール手順

用途に応じて2通りあります。**TouchDesignerでSDIテロップを出す運用（本番）**なら
A だけでOKです（Pythonの追加インストールは不要）。**PC単体で音声/映像ファイルや
サウンド入力から確認する**なら B を使います。

---

## A. TouchDesigner運用(本番: SDI入力→住所テロップ→Fill&Key出力)

TouchDesigner本体にPythonとnumpyが同梱されているため、**別途のPythonインストールや
pipは不要**です。以下の3ステップだけです。

### A-1. コード一式を配置

GitHubのブランチ `claude/helicopter-gps-audio-decoder-cr257z` から取得します。

- **方法1(簡単・ZIP)**: GitHubのページで `Code ▾` → `Download ZIP` →
  展開して `C:\heli_gps` に置く(中に `nnn_decoder` と `touchdesigner`
  フォルダが入っている状態にする)
- **方法2(git)**:
  ```
  git clone -b claude/helicopter-gps-audio-decoder-cr257z <リポジトリURL> C:\heli_gps
  ```

> 置き場所は任意ですが、以降 `C:\heli_gps` を前提に説明します。別の場所に
> 置いた場合は、次のパス設定でその場所を指定してください。

### A-2. パスを合わせる

メモ帳で以下2ファイルの冒頭を開き、`HELI_GPS_LIB` を実際の置き場所に修正:

- `C:\heli_gps\touchdesigner\build_network.py`
- `C:\heli_gps\touchdesigner\gps_decode_callbacks.py`

```python
HELI_GPS_LIB = r"C:\heli_gps"        # ←実際の場所に
```

`build_network.py` の `DEVICE = "UltraStudio HD Mini"` も、お使いの機種名に
合っているか確認(デバイス欄のプルダウン表記と一致させる)。

### A-3. TouchDesignerで構築

1. **Blackmagic Desktop Video** を最新版(12.x以降)でインストール
2. TouchDesigner(Commercial以上)を起動 → File → New → File → Save で
   `C:\heli_gps\touchdesigner\heli_telop.toe` として保存
3. **Alt+T** でTextportを開き、次の1行を実行:
   ```python
   exec(open(r"C:\heli_gps\touchdesigner\build_network.py", encoding="utf-8").read())
   ```

これでネットワークとコントロールUIが一式生成されます。以降のデバイス選択・
チャンネル・Fill&Key・REF入力などの確認は `touchdesigner/README_TD.md` を
参照してください。

> **numpyについて**: TouchDesigner同梱のPythonにnumpyが入っています。もし
> import エラーが出る場合のみ、TDのPythonに合わせて別途numpyを入れます
> (通常は不要)。

---

## B. PC単体での確認・運用(GUIアプリ / ファイル復調)

キャプチャボードの音声をWindowsのサウンド入力として使う場合や、収録済みの
WAV/映像ファイルから位置を復元する場合に使います。

### B-1. Python

Python 3.10以降をインストール(https://www.python.org/ 。インストール時
「Add Python to PATH」にチェック)。

### B-2. 依存パッケージ

コマンドプロンプトで、配置したフォルダに移動して:

```
cd C:\heli_gps
pip install -r requirements.txt
```

- `numpy` … 必須(復調・住所判定)
- `sounddevice` … ライブ受信GUIに必要(WAV/映像ファイル復調だけなら不要)

### B-3. (映像ファイルを扱う場合) ffmpeg

MP4/MOV/TS等から音声を抽出するのに使います。

```
winget install --id Gyan.FFmpeg
```

コマンドプロンプトを開き直して `ffmpeg -version` が表示されればOK。
WAVファイルだけを扱うなら不要です。

### B-4. 動作確認

```
cd C:\heli_gps

: テスト音声を生成
python -m nnn_decoder.modulator test.wav --seconds 10

: 復調(住所つき。オフラインなのでネット不要)
python -m nnn_decoder.cli test.wav --address

: ライブGUI(サウンド入力から)
python -m nnn_decoder.app
```

CLIで「千葉県千葉市…」等が表示されれば成功です。実素材の場合は
`--channel 3`(GPSが3ch目のとき)などでチャンネルを指定します。
映像ファイルはそのまま `python -m nnn_decoder.cli 収録.mp4 --channel 3` で
読めます(ffmpegが必要)。

---

## 住所変換について(A・B共通)

- 既定は**オフライン**(同梱の市区町村境界データ)。インターネット接続なしで
  市町村まで判定します
- 町丁目まで出したい場合のみ「自動」または「オンライン」モードにします
  (国土地理院APIを使うためネット接続が必要)

## テスト(任意)

開発時の動作確認をしたい場合:

```
pip install pytest
python -m pytest tests/
```
