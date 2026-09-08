# サードパーティ表記 (Third-Party Notices)

本製品は以下のオープンソースソフトウェア・データを利用しています。
（GStreamer版=`gst_heli`を配布する場合を含む）

## ソフトウェア

| 名称 | ライセンス | 用途 | 備考 |
|---|---|---|---|
| GStreamer | LGPL-2.1 | 音声取得・SDI入出力 | **同梱せず各局が公式インストーラで導入**。ソース: https://gitlab.freedesktop.org/gstreamer/gstreamer 使用プラグインはcoreelements/app/decklink/videoconvertscale/audioconvertのみ(いずれもLGPL)。GPLプラグインは不使用 |
| NumPy | BSD-3-Clause | 信号処理 | `LICENSES/numpy-LICENSE.txt` |
| Pillow | MIT-CMU (HPND) | テロップ・地図描画 | `LICENSES/Pillow-LICENSE.txt` |
| sounddevice / PortAudio | MIT | 音声入力（PC単体テスト時） | `LICENSES/sounddevice-LICENSE.txt` |
| Python 標準ライブラリ（tkinter 含む） | PSF | 全般・制御UI | 各局が公式Pythonを導入 |

> GStreamer はLGPLです。**本製品には同梱せず**、各局が公式インストーラで導入する構成のため
> ソース提供義務は発生しません（`README_SETUP.md` 参照）。gst-launch-1.0 を別プロセスとして
> 起動する疎結合構成で、GStreamer 自体は無改変です。PyGObject は使用していません。

## 同梱ライセンス全文

各ライセンスの全文は `LICENSES/` フォルダに同梱しています（配布時は必ず一緒に配布してください）。

本システムは **外部の地図サービス・APIキー・アカウント連携を一切使用しません**（住所判定・地図表示はすべて同梱データによるオフライン処理）。

## データ

| 同梱ファイル | 正式なパッケージ名 / 出典・ライセンス | 用途 |
|---|---|---|
| `nnn_decoder/data/muni_boundaries.json.gz` | **国土数値情報「行政区域データ」（N03）第3.0版**（`N03-21_210101`, 令和3年1月1日時点）（国土交通省）を加工して作成。加工元の簡略化データ: smartnews-smri/japan-topography（**定型ライセンスなし**。README で無償利用・加工者クレジット不要を明示） | オフライン住所判定（点内判定）＋地図スーパー描画 |
| `nnn_decoder/data/muni.json` | **国土地理院ウェブサイト**（地理院地図の市区町村コード表 `https://maps.gsi.go.jp/js/muni.js`）を加工して作成 | 市区町村コード→名称（テロップ・地図ラベル） |
| `nnn_decoder/data/gun.json` | geolonia/japanese-addresses (**CC0-1.0**) の市区町村名から町村の郡名を抽出して作成 | 市区町村コード→郡名（区・郡あり表示） |
| （データ同梱なし） | 国土地理院 逆ジオコーダ `https://mreversegeocoder.gsi.go.jp/` | `--geo-mode online`/`auto` 指定時のみ使用。**既定は `offline` で通信しません**（検証用） |

### 出典表記（必須）

放送・公衆送信・配布物に用いる場合、次の2者への**出典記載**と**加工した旨の記載**が必要です。

```
出典：「国土数値情報（行政区域データ）」（国土交通省）
      https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-v3_0.html （2021-09-28 取得）を加工して作成
出典：国土地理院ウェブサイト https://maps.gsi.go.jp/js/muni.js （2026-09-08 取得）を加工して作成
```

地図スーパーON時は、地図インセット内に
`出典:国土数値情報(国土交通省)・国土地理院を加工して作成` が**自動描画されます（消去不可）**。
掲出方法の詳細と根拠は `docs/ATTRIBUTION.md` を参照してください。

**地理院タイル等の測量成果は使用していないため、測量法第29条・第30条の承認申請は不要です。**

## フォント

| | |
|---|---|
| 同梱フォント | **Noto Sans JP**（可変フォント, `Version 2.004-H2`）`fonts/NotoSansJP-VF.ttf` |
| ライセンス | **SIL Open Font License 1.1** — 全文 `fonts/OFL.txt`（**削除禁止**） |
| 改変 | なし（バイナリ無改変。ファイル名のみ変更） |
| 放送での使用 | **可**。OFL はフォントソフトウェアの再配布を規律するもので、**フォントで組んだ出力物には制約がありません** |
| 埋め込み | OS/2 `fsType = 0`（Installable Embedding ＝ 制限なし） |

制御UIで**システムフォントを選択した場合**は、当該フォントのEULAが適用されます。
Windows同梱フォント（游ゴシック・メイリオ等）は**再配布不可**のため同梱していません。

---

本ファイルは配布時に製品へ同梱してください。EULA本文および最終的な表記内容は
社内法務の確認を推奨します。
