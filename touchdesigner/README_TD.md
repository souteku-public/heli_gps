# TouchDesigner連携ガイド — SDI入力からGPS住所テロップをFill&Keyで出力

UltraStudioのSDI入力(EMB音声ch3)からGPSを復調し、市区町村の住所文字列を
1080iのFill(文字)+Key(アルファ)としてUltraStudioのSDI OUTから出力する構成です。

```
SDI IN → UltraStudio → TD: Audio Device In (EMB ch3)
                            → Script CHOP (nnn_decoder復調+住所変換)
                            → Text TOP (フォント/サイズ/位置をUIで調整)
                            → Video Device Out (1080i59.94, External Keyer)
                                  → SDI OUT A = Fill / SDI OUT B = Key → スイッチャーDSKへ
```

映像そのものはTDを通さず、スイッチャー(DSK/キーヤー)側で
Fill&Keyを本線に重ねる運用を想定しています。

## 事前準備

1. **Blackmagic Desktop Video** を最新版にインストール
2. **リポジトリの配置**: この`heli_gps`一式を例えば `C:\heli_gps` に置く
3. **TDのPythonにnumpyを確認**: TD標準Pythonにはnumpy同梱済み。
   追加パッケージは不要です(復調・住所変換は標準ライブラリ+numpyのみ)
4. `touchdesigner/gps_decode_callbacks.py` と `build_network.py` の冒頭にある
   `HELI_GPS_LIB = r"C:\heli_gps"` を実際の配置場所に合わせる

## セットアップ (方式A: TD内で復調)

1. TDで新規プロジェクトを開き、Textport(Alt+T)で実行:
   ```python
   exec(open(r"C:\heli_gps\touchdesigner\build_network.py", encoding="utf-8").read())
   ```
   `/project1/HELI_GPS` に雛形ネットワークができます。

2. **audio_in (Audio Device In CHOP)** のパラメータ:
   - Driver / Device: UltraStudio (Blackmagic) を選択
   - Sample Rate: 48000
   - EMB音声のch3が何番目のチャンネルに来るかを確認
     (`audio_in` の出力チャンネルをMIDIっぽく見て、1200Hzのトーンが
     見えるチャンネルがGPSです)
   - ※Audio Device In CHOPにBlackmagicデバイスが出ない場合は
     後述の「方式B: OSC受信」を使ってください

3. **gps_decode (Script CHOP)** のカスタムパラメータ(Heli GPSページ):
   - ビットレート: 1200 (実測確認済みの値)
   - 音声チャンネル: audio_in内でGPSが乗っているチャンネル番号(0始まり)
   - 表示フォーマット: `{address}` のほか `{address} 高度{alt}m` など
     `{lat} {lon} {sats}` が使用可能
   - 住所の詳細度: 市区町村 (町丁目まで出す場合は「町丁目」)
   - 受信途絶時の表示: 空欄なら非表示(テロップが消える)

4. **overlay_text (Text TOP)** — テロップの見た目はここでUI調整:
   - Font: 游ゴシック / Noto Sans JP など日本語フォントを選択
   - Font Size, Position, Align で位置・サイズ調整
   - 背景アルファ0(透明)のまま使うこと(アルファがそのままKeyになります)
   - 座布団(半透明ボックス)が欲しい場合はRectangle TOPとOver TOPで
     overlay_textの手前に合成してからsdi_outへ

5. **sdi_out (Video Device Out TOP)**:
   - Device: UltraStudio を選択
   - Signal Format: **1080i59.94** (放送系に合わせる)
   - **Keyer: External** に設定
     → SDI OUT A からFill、SDI OUT B からKeyが出ます
   - TDが出すのはRGBA1枚で、Fill/Key分離はUltraStudio側が行います

6. プロジェクトFPSを59.94に (File > Project Settings > FPS)。
   テキスト主体なのでインターレースのちらつきが気になる場合は
   文字サイズを大きめに、細い明朝体を避けるのが定石です。

## 方式B: 外部デコード + OSC受信 (音声デバイスが見えない場合の代替)

UltraStudioの音声がTDから取れない環境では、復調を外部アプリで行い
TDへはOSCで住所文字列だけを渡します。

1. PC側でGUIアプリを起動し「OSC送出 (127.0.0.1:9000)」をON:
   ```
   python -m nnn_decoder.app
   ```
   (音声入力はWindowsに見えている任意の経路でOK。UltraStudioの音声が
   Windows録音デバイスに出ていればそれを選択)

2. TD側: OSC In DAT を作成、Port=9000。
   `touchdesigner/osc_in_callbacks.py` の内容をコールバックDATに貼り、
   OSC In DATのCallbacksに指定。`TEXT_TOP`の名前を合わせる。

3. Text TOP以降(手順4〜6)は方式Aと同じ。

OSCは `/heli/position (lat,lon,alt)` `/heli/address (文字列)`
`/heli/status (fix,衛星数,ID)` を毎秒送出しているので、
高度表示や位置に応じた演出もTD側で自由に組めます。

## 動作確認 (実機・ヘリなしで)

テスト音声を再生してループバックすれば全経路を確認できます:

```
python -m nnn_decoder.modulator test.wav --seconds 60
```

これを再生した音声をaudio_in(または外部アプリ)に入れると、
「千葉県千葉市美浜区」付近を南下する模擬データが毎秒更新されます。

## 注意事項

- **住所変換は国土地理院APIを使用**するため、送出PCにインターネット接続が
  必要です。通信断のときは最後に取得できた住所を保持し続けます
  (市区町村境界を越えたときだけ問い合わせる設計なのでAPI負荷は僅少)
- **UltraStudioの同時入出力**: キャプチャ(音声取り)と再生(Fill&Key出力)を
  1台で同時に行えるかは機種依存です。UltraStudio 4K系は可、
  HD Mini等は仕様をご確認ください。不可の場合は音声入力を別経路
  (小型USBオーディオIF等)にするか、入出力で2台に分けてください
- Fill&Key 2出力を使うため、UltraStudio側の設定(Desktop Video Setup)で
  SDI出力が「Fill & Key」相当になっていることも確認してください
