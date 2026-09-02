# セットアップ手順（配布先の各局向け）

ヘリGPS音声デコード／スーパー送出システムのインストール手順です。
**外部サービス（Google等）のアカウント連携や API キーは一切不要**、
**インターネット接続なし**で動作します。

---

## 0. 事前に用意するもの

| | 内容 |
|---|---|
| PC | Windows 10 / 11（64bit） |
| キャプチャ | Blackmagic DeckLink / UltraStudio（SDI 入出力） |
| 信号 | ヘリ受信映像の SDI（GPS音声がエンベデッドされたもの） |
| 基準同期 | **REF（ゲンロック）** … SDI 出力を行う場合は必須 |

> **本体の配布物には GStreamer と Desktop Video は含まれていません。**
> ライセンス上の理由から、各局で公式版を導入していただきます（下記 1・2）。

---

## 1. Blackmagic Desktop Video の導入

1. Blackmagic Design の公式サポートページから **Desktop Video** をダウンロード
2. インストール後、**Blackmagic Desktop Video Setup** を起動
3. 使用するデバイスの入出力設定を確認（SDI、1080i59.94 等）
4. PC を再起動

---

## 2. GStreamer の導入

1. `https://gstreamer.freedesktop.org/download/` から Windows (MSVC 64-bit) の
   **Runtime installer** と **Development installer** を取得
2. インストール時は必ず **Complete（完全）** を選択
   （`decklink` プラグインが含まれます。Typical では入りません）
3. 既定のインストール先:
   `C:\Program Files\gstreamer\1.0\msvc_x86_64\bin`

**確認**（コマンドプロンプトで）:
```
"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-inspect-1.0.exe" decklinkvideosink
```
→ プロパティ一覧が出れば OK。`No such element` の場合は Complete で入れ直してください。

---

## 3. Python の導入

1. `https://www.python.org/` から **Python 3.10 以降** をインストール
   （インストーラで **Add python.exe to PATH** に必ずチェック）
2. 依存パッケージを導入:

```
pip install -r requirements.txt
```

---

## 4. 本体の配置

配布物一式を任意のフォルダ（例 `C:\heli_gps`）に展開します。

```
heli_gps\
├── control_ui.py            制御UI
├── gst_heli\                送出本体
├── nnn_decoder\             復調・住所変換（境界データ同梱）
├── fonts\                   同梱フォント置き場（README.md 参照）
├── LICENSES\                third-party ライセンス全文
├── docs\LICENSING.md        ライセンス整理（段階別）
├── THIRD_PARTY_NOTICES.md   出典・ライセンス一覧
├── start_heli_gst.bat       起動：Fill/Key 出し
├── start_heli_burnin.bat    起動：バーンイン（1本出し）
└── start_heli_preview.bat   起動：プレビュー（SDI出力なし）
```

---

## 5. フォントについて

`fonts\` にフォントが置かれていれば、それが**最優先**で使われます。
配布物に同梱されている場合は**全局で同一の見た目**になります。

置かれていない場合は次の順で自動選択します。

1. `fonts\`（同梱）
2. **OFL / IPA 系**（Noto Sans JP、IPAゴシック等） ← 推奨
3. 環境依存フォント（游ゴシック、メイリオ等）

> 制御UIのフォント一覧には**日本語字形を持つフォントのみ**が表示されます
> （欧文専用フォントを選ぶとテロップが消えるため、自動で除外しています）。
> 詳細は `fonts\README.md` を参照。

---

## 6. 起動

用途に応じてバッチをダブルクリックしてください。**送出本体と制御UIが同時に起動**します。

| バッチ | 内容 | 外部キーヤー |
|---|---|---|
| `start_heli_preview.bat` | 入力映像＋テロップを**PC画面で確認**（SDI出力なし・REF不要） | ― |
| `start_heli_gst.bat` | **Fill/Key 出し**（スイッチャー側で合成） | 必要 |
| `start_heli_burnin.bat` | **バーンイン**（入力映像＋音声にテロップを焼き込み、1本のSDIで出力） | 不要 |

**初回は `start_heli_preview.bat` での確認を推奨します**（SDI出力を行わないため安全）。

### バッチ内の設定項目（先頭付近）

| 変数 | 意味 | 既定 |
|---|---|---|
| `CHANNEL` | GPS音声のチャンネル（**0始まり**。CH3なら `2`） | `2` |
| `MODE` / `VMODE` | 出力／入力の信号フォーマット | `1080i5994` |
| `INDEV` / `OUTDEV` | DeckLink のデバイス番号 | `0` |
| `AVOFFSET` | バーンイン時のA/V補正[ms]（+で音声を遅らせる） | `0` |
| `GST1` / `GST2` | GStreamer のインストール先 | 既定パス |

---

## 7. 動作確認の順序

1. **音声が来ているか** — 送出本体のコンソールに `[audio] ch levels(CH1..)` が出ます。
   GPS音声のチャンネルだけレベルが立っていることを確認
2. **復調できているか** — `[status] 受信=True packets=…` が増えていく
3. **住所が出るか** — 制御UIの「受信状態」に市区町村名が表示される
4. **テロップの見た目** — プレビューで位置・サイズ・色を調整し「**決定（反映）**」
5. **SDI出力** — Fill/Key またはバーンインのバッチで送出

---

## 8. 運用上の既定値（変更しないでください）

| 設定 | 既定 | 理由 |
|---|---|---|
| 住所変換モード | **オフライン** | 同梱データで完結。外部APIに依存しない |
| 地図 | **オフライン地図** | ネット接続・アカウント不要 |

> 「オンライン（地理院API）」モードは**検証用**です。常用しないでください
> （提供元の想定用途を外れ、可用性の保証もありません）。

---

## 9. よくあるトラブル

| 症状 | 原因・対処 |
|---|---|
| `'gst-launch-1.0' は認識されていません` | GStreamer 未導入か PATH 未設定。バッチの `GST1`/`GST2` を実環境に合わせる |
| `No such element decklinkvideosink` | GStreamer を **Complete** で入れ直す |
| `Audio src needs a video src` | 音声だけでは動きません（映像入力が必要）。SDI入力を接続 |
| テロップが出ない／消える | フォントの問題が多いです。UIでフォントを選び直して「決定」。`fonts\` の同梱フォント推奨 |
| SDI出力が乱れる／`Failed to schedule frame` | **REF（基準同期）**が入っているか確認 |
| 音声が途切れて復調が不安定 | 入力レベルとケーブルを確認。コンソールの ch levels が断続的に 0 になっていないか |
| バーンインで音声がずれる | バッチの `AVOFFSET` を調整（+で音声を遅らせる） |

---

## 10. ライセンス

配布物には `LICENSES\` と `THIRD_PARTY_NOTICES.md` が含まれます。**削除しないでください。**

- 本システムは**外部の地図サービス・APIキーを使用しません**
- 住所判定に用いる市区町村境界データは
  「国土数値情報（行政区域データ）」（国土交通省）を加工して作成しています
- **住所を放送に出す場合は出典表記が必要**です。`docs\LICENSING.md` を参照のうえ、
  自局の法務にご確認ください
