# TouchDesigner設定ガイド — SDI入力からGPS住所テロップをFill&Keyで出力

**TouchDesignerを初めて使う方向け**に、ゼロから本番運用までの手順を説明します。

## 全体の構成

```
SDI IN → UltraStudio → TD: audio_in (EMB音声ch3を取得)
                            → gps_decode (GPS復調+市区町村変換)
                            → overlay_text (テロップ描画。フォント/位置はここでUI調整)
                            → sdi_out (1080i59.94, External Keyer)
                                → SDI OUT A = Fill / SDI OUT B = Key → スイッチャーDSKへ
```

映像本線はTDを通しません。TDは「文字のFillとKeyの2系統」だけを出し、
スイッチャーのDSK/キーヤーで本線に重ねる運用です。

## toxファイルについて

toxはTouchDesigner本体でしか生成できないため、リポジトリには
**実行するとtoxを自動生成するスクリプト**(`build_network.py`)を入れてあります。
手順2を1回実行すると `touchdesigner/HELI_GPS.tox` が保存され、
**以後は新しいプロジェクトにこのtoxをドラッグ&ドロップするだけ**で使えます。

---

## 0. 必要なもの

| 項目 | 内容 |
|---|---|
| TouchDesigner | **Commercialライセンス以上が必須**(下記注意) |
| Blackmagic Desktop Video | 最新版をインストール(UltraStudioのドライバ) |
| このリポジトリ | 例: `C:\heli_gps` に配置 |
| インターネット接続 | **不要**(住所変換は同梱データでオフライン判定。町丁目まで出す場合のみ地理院APIを使用) |

> **ライセンスの注意**: 無償のNon-Commercial版は**解像度が1280×1280に制限**
> されるため、1920×1080のテロップ出力ができません。放送業務での使用となるため
> **Commercial**(年$600)以上のライセンスを購入してください。
> 事前検証だけなら無償版でも「1280×720に落とした構成」で流れの確認は可能です。

## 1. インストールと起動

1. https://derivative.ca/download から**Windows版インストーラ**を取得しインストール
2. 起動時にアカウント作成とライセンスキーの有効化を求められるので画面に従う
3. 起動すると英語UIでサンプルネットワークが表示されます
4. **File → New** で新規プロジェクトを作成し、**File → Save** で
   `C:\heli_gps\touchdesigner\heli_telop.toe` などの名前で保存
   (.toeが「プロジェクトファイル」、.toxは「部品ファイル」です)

### TouchDesignerの基本操作(最低限これだけ)

| 操作 | 方法 |
|---|---|
| 画面の移動/拡大 | 右ドラッグ / ホイール |
| ノードの選択 | 左クリック |
| パラメータ画面を出す | ノードを選んで **キーボードの `p`** |
| ノードの中身(ビューア)を大きく見る | ノード上でホイールクリック→ビューア表示 |
| Textport(コマンド入力画面) | **Alt + T** |
| 編集画面⇔本番画面(Perform Mode) | **F1**(戻るのはEsc) |

## 2. ネットワークの自動構築(tox生成)

1. `build_network.py` と `gps_decode_callbacks.py` をメモ帳で開き、先頭の
   `HELI_GPS_LIB = r"C:\heli_gps"` を実際の配置場所に合わせて保存
2. TDで **Alt+T** を押してTextportを開き、次の1行を貼り付けてEnter:

```python
exec(open(r"C:\heli_gps\touchdesigner\build_network.py", encoding="utf-8").read())
```

3. `/project1/HELI_GPS` の中に**6つのノード**が生成され、`HELI_GPS.tox`
   が自動保存されます:
   - **audio_in** (Audio Device In CHOP) … EMB音声。Blackmagic・8ch・自動設定
   - **video_in** (Video Device In TOP) … ★Blackmagic音声を流すために必須
   - **gps_decode** (Script CHOP) … 復調+住所変換
   - **overlay_text** (Text TOP) … テロップ描画
   - **sdi_out** (Video Device Out TOP) … 1080i Fill&Key出力
   - **force_cook** (Execute DAT) … 毎フレーム強制クック(遅延評価対策)
4. ネットワーク画面の何もない所をダブルクリックすると階層を移動できます。
   `HELI_GPS` と書かれた箱をダブルクリックして中に入ってください

> **重要 — 二重に作らない**: このスクリプトは実行時に既存のHELI_GPSを
> 削除してから作り直します。手作業でコピーを作ったり、階層違い
> (`/HELI_GPS` と `/project1/HELI_GPS`)に2つできると、同じUltraStudioを
> 奪い合って誤動作します。**HELI_GPSは1つだけ**にしてください。
>
> スクリプト冒頭の `DEVICE = "UltraStudio HD Mini"` が実機の型番と違う
> 場合は、その行を書き換えてから実行してください。

> 以後、別のプロジェクトで使うときは、エクスプローラから `HELI_GPS.tox` を
> TDのネットワーク画面にドラッグ&ドロップするだけです。

## 3. 各ノードの設定

### 3-1. audio_in (Audio Device In CHOP) — UltraStudioの音声を取る

1. `audio_in` を左クリック → `p` でパラメータ画面
2. **Driver=Blackmagic / Device=お使いの機種 / Number of Channels=8**
   になっているか確認(スクリプトが自動設定済み)
   - **Rate欄が44100とグレー表示でも問題ありません**。Blackmagic選択時は
     実レートがデバイスから自動供給されます(ch数が8になっていれば正常)
3. **★video_in を必ず動かすこと(重要)**: TD＋Blackmagicでは、同じデバイスの
   **映像入力(Video Device In TOP)がアクティブに動いていないと音声が
   流れません**。`video_in` のビューアをオンにして**SDI映像が映ることを
   確認**してください。映像が映った瞬間に audio_in の波形が振れ始めます。
   video_inは映像確認用で出力しませんが、**消さないでください**
4. `audio_in` のビューアをオンにすると `chan1, chan2, ...` の波形が並びます。
   **GPSが乗っているチャンネルを確認**します:
   - GPSチャンネルは**常時ビーッと鳴っている1200Hz系のトーン**なので、
     波形が常に一定に振れているチャンネルがそれです(今回の収録ではch3)
   - 見分けがつかない場合は、次の3-2で「音声チャンネル」を0,1,2,...と
     順に変えて、住所が表示される番号を探すのが確実です

> **audio_inの波形が全chゼロのまま** → まず video_in の映像が映っているか
> 確認(手順3)。映像が映っているのに音声0なら、audio_inのActiveを
> Off→Onで再オープン。
>
> **DeviceにBlackmagicが出てこない場合** → ページ末尾の「方式B: OSC受信」へ。
> テロップ出力側の構成はそのまま使えます。

### 3-2. gps_decode (Script CHOP) — 復調と住所変換

1. `gps_decode` を選択 → `p` → **「Script」タブの Setup Parameters ボタンを
   1回押す**(これで下記のカスタムパラメータが生成されます。押さないと
   「Heli GPS」タブが出ません) → **「Heli GPS」タブ**を開く
2. 設定項目:

| パラメータ | 設定値 |
|---|---|
| ビットレート | **1200 bps**(実収録で確認済み) |
| 音声チャンネル(0始まり) | GPSのch。**SDIのCH3なら「2」**(0始まりのため) |
| 更新するText TOP | overlay_text(既定のまま) |
| 表示フォーマット | `{address}` (例: `{address} 高度{alt}m` も可) |
| 受信途絶時の表示 | 空欄=テロップを消す / `GPS受信なし` など任意 |
| 住所の詳細度 | **市区町村** |
| 住所変換エンジン | **オフライン**(ネット不要)。町丁目が必要なときのみ「自動」 |

3. 正しく設定できていれば、ノードのビューアに `lat / lon / alt / fix / age` の
   チャンネルが出て、latが35.6…などの値になります(fix=0が正常受信)

### 3-3. コントロールUI(★オペレーターはここだけ操作すればOK)

`build_network.py` を実行すると、**HELI_GPSコンテナに「Controls」という
操作パネル(カスタムパラメータページ)が自動生成**されます。運用で触る
項目がすべて1画面に集約されており、ご要望の
「オンライン/オフライン・住所の粒度・フォント・文字サイズ・配置」を
ここから設定できます。

**開き方**: ネットワーク画面で `HELI_GPS` の**箱を1回クリックで選択**し
(中に入らない)、`p` を押す → **「Controls」タブ**。

| 項目 | 内容 |
|---|---|
| 住所変換モード | **オフライン(ネット不要) / 自動 / オンライン(地理院API)** |
| 住所の粒度 | **都道府県 / 市区町村 / 町丁目** |
| 表示書式 | `{address}` / `{address} 高度{alt}m` 等 |
| 受信途絶時の表示 | 空欄=消す / 任意文字 |
| GPS音声ch(0始まり) | CH3なら 2 |
| ビットレート | 1200 / 2400 |
| **フォント** | インストール済み日本語フォントから選択 |
| **文字サイズ** | スライダー |
| 横位置基準 / 縦位置基準 | 左中右 / 下中上 |
| **位置(X,Y)px** | セーフエリア内へ微調整 |
| 文字色 / 不透明度 | カラーピッカー |

変更は overlay_text と gps_decode に**即座に反映**されます(内部で
パラメータバインド)。本番中もこのページだけ操作すれば完結します。

> 既存ネットワークへ後付けする場合はTextportで:
> ```python
> exec(open(r"C:\heli_gps\touchdesigner\setup_ui.py", encoding="utf-8").read())
> ```

### 3-4. overlay_text (Text TOP) — 個別に細かく詰めたい場合

通常はコントロールUI(3-3)で足りますが、フチ取りや座布団など
細かい調整をしたいときは `overlay_text` を選択 → `p` で直接調整します:

| パラメータ | 内容 |
|---|---|
| Font | フォント選択(游ゴシック=Yu Gothic 等。自動設定済み、変更可) |
| Font Size X | 文字サイズ(初期値72) |
| Align X / Align Y | 画面内の基準位置(中央/左右、上下) |
| Position X / Y | 位置の微調整(ピクセル)。初期値は下センターのセーフエリア内 |
| Font Color / Alpha | 文字色・不透明度 |
| Border系 | フチ付き文字にする場合 |

- **背景(Background Alpha)は0のまま**にしてください。この透明部分が
  そのままKey(アルファ)になります
- 縁取りや座布団が必要になったら: Rectangle TOP + Over TOP を
  overlay_text と sdi_out の間に挟みます(必要なら手順を案内します)

### 3-5. sdi_out (Video Device Out TOP) — 1080i Fill&Key出力

`sdi_out` を選択 → `p` でパラメータ画面を開き、上から順に:

1. **Library**: Blackmagic を選択(メーカー選択がある場合)
2. **Device**: UltraStudio を選択
3. **Signal Format**: **1080i 59.94** を選択
   (インターレースはフィールド周波数表記のため、リストでは
   「1080i」の59.94を選びます。「1080i 29.97」表記のビルドもあります)
4. **Output Pixel Format**: **「8-bit + 8-bit Key (Alpha)」** を選択
   ← **これがFill&Key設定です。「Keyer」という名前のパラメータはありません**
   - この設定にすると、UltraStudioの **SDI OUT 1本目=Fill(カラー)、
     2本目=Key(アルファ)** の2系統出力になります
   - 2本をスイッチャーのDSKにFill/Keyとして入力してください
5. **Active**: On

> **重要 — リファレンス(ゲンロック)が必要です**: BlackmagicデバイスのKey/Fill
> 出力は、**REF INに同期信号(ブラックバーストまたは3値シンク)を接続**
> しないと機能しない機種がほとんどです。局内のステーションシンクを
> UltraStudioのREF INに入れてください(スイッチャーと同期も取れるので
> DSK運用上もこれが正解です)。
>
> 万一「8-bit + 8-bit Key (Alpha)」がリストに出ない場合は、
> Desktop Videoのバージョンを最新(12.x以降)に更新してください。

**文字のフチが黒ずむ場合**: DSK側の設定を「プリマルチプライ(乗算済み)」に
合わせるか、TD側で overlay_text と sdi_out の間に挟んだ合成の
プリマルチプライ設定を切り替えてください。

> **スイッチャーを使わない簡易構成**: UltraStudio/DeckLinkにはハードウェア
> キーヤー(SDI INの本線に直接文字を重ねて合成済みで出す機能)を持つ機種も
> ありますが、TDのVideo Device Out TOPからは制御できません。本構成では
> スイッチャーDSK(またはキーヤー付きの後段機器)で重ねてください。

### 3-6. プロジェクトのFPSを59.94にする

Textport(Alt+T)で:

```python
project.cookRate = 59.94
```

を実行(1080i59.94のフィールド周期に合わせます)。File → Saveで保存。

## 4. 動作確認(ヘリなしでできます)

1. コマンドプロンプトで模擬GPS音声を生成:
   ```
   cd C:\heli_gps
   python -m nnn_decoder.modulator test.wav --seconds 60
   ```
2. `test.wav` を再生し、その音をaudio_inに入れる
   (いちばん簡単なのは、audio_inのDeviceを一時的にPCのマイク/ライン入力や
   ステレオミキサーにして、スピーカー再生をループバックする方法)
3. `overlay_text` のビューアに **「千葉県千葉市美浜区」** と表示され、
   毎秒更新されれば復調〜住所変換まで動いています
4. UltraStudioのSDI OUTをモニタ/スイッチャーで確認

## 5. 本番運用

- **F1キー**でPerform Mode(本番画面)へ。編集画面に戻るのはEsc
- 運用PCでは .toe をダブルクリックすれば同じ状態で立ち上がります
- Windowsのスリープ/自動更新の無効化、TDの自動起動(スタートアップに.toe)を推奨

## 方式B: 外部デコード + OSC受信(TDでBlackmagic音声が取れない場合)

1. PC側でGUIアプリを起動し「OSC送出 (127.0.0.1:9000)」をON:
   ```
   python -m nnn_decoder.app
   ```
   (音声はWindowsに見えている任意の入力経路でOK)
2. TD側: ネットワークの空きスペースをダブルクリック → OPメニューから
   **DAT → OSC In** を作成。パラメータで Port=9000
3. **DAT → Text** を作成し、`osc_in_callbacks.py` の内容を貼り付け、
   名前を `osc_in_callbacks` に変更
4. OSC In DATのパラメータ **Callbacks** に `osc_in_callbacks` と入力
5. 以降(overlay_text, sdi_out)は方式Aと同じ

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| テキストが「ヘリGPS待機中」のまま変わらない(latは出ている) | gps_decodeのカスタムパラメータが空。Textportで直接設定: `d=op('/project1/HELI_GPS/gps_decode'); d.par.Texttop='overlay_text'; d.par.Textformat='{address}'; d.par.Staletimeout=5; d.par.Addrlevel='city'; d.par.Geomode='offline'; d.par.Audiochan=2` |
| CHOPのfixが常に2 (パケットは正常) | 同上。Staletimeoutが0だと常に受信途絶扱いになりfix=2で出る。上記でStaletimeout=5を設定 |
| テキストが初期表示のまま一切変わらない | `force_cook`(Execute DAT)があるか確認。無ければbuild_network.pyを再実行(TDは参照されないノードを評価しないため、gps_decodeの強制クックが必要) |
| 文字が「□□□」になる | overlay_textのFontを日本語フォント(Yu Gothic等)に |
| 住所が出ない/更新されない | gps_decodeビューアのfixが0か確認。0でなければ音声チャンネル番号を順に変更 |
| latが0のまま | 音声が来ていない。audio_inのDevice/波形を確認 |
| 住所だけ出ない(latは出る) | インターネット接続を確認(APIに出られていない) |
| SDI出力が真っ黒 | sdi_outのSignal Formatが受け側と一致しているか確認 |
| Keyが出ない/2本目から何も出ない | Output Pixel Formatが「8-bit + 8-bit Key (Alpha)」か、**REF INに同期信号が入っているか**確認 |
| Keyが全白/全黒 | overlay_textのBackground Alphaが0になっているか確認 |
| 出力がカクつく | project.cookRate=59.94か、PCのGPU負荷を確認 |
| 1920x1080にできない | ライセンスがNon-Commercial(1280制限)。Commercialが必要 |

## 注意事項

- 住所変換は国土地理院APIを使用(市区町村を跨ぐときだけ問い合わせる設計)。
  **通信断のときは最後の住所を保持**して表示が止まらないようにしています
- **UltraStudioの同時入出力**(音声キャプチャとFill&Key再生の同時動作)は
  機種依存です。UltraStudio 4K系は可。不可の機種では音声入力を別経路にするか、
  方式Bにしてください
