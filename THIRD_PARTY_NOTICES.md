# サードパーティ表記 (Third-Party Notices)

本製品は以下のオープンソースソフトウェア・データを利用しています。
（GStreamer版=`gst_heli`を配布する場合を含む）

## ソフトウェア

| 名称 | ライセンス | 用途 | 備考 |
|---|---|---|---|
| GStreamer | LGPL-2.1 | 音声取得・SDI出力 | 別途インストール。ソース: https://gitlab.freedesktop.org/gstreamer/gstreamer 使用プラグインはcoreelements/app/decklink/videoconvertscale/audioconvertのみ(いずれもLGPL)。GPLプラグインは不使用 |
| PyGObject | LGPL-2.1 | GStreamerのPythonバインディング | https://gitlab.gnome.org/GNOME/pygobject |
| NumPy | BSD-3-Clause | 信号処理 | |
| Pillow | MIT-CMU (HPND) | テロップ描画 | |
| Python 標準ライブラリ | PSF | 全般 | |

> GStreamer/PyGObject はLGPLです。動的リンク(通常のライブラリ利用)で使用しており、
> 利用者は同ライブラリを差し替え可能です。LGPL全文および入手先は上記URLを参照。
> 改変して配布する場合は改変ソースを提供します（本製品は無改変で利用）。

## 同梱ライセンス全文

各ライセンスの全文は `LICENSES/` フォルダに同梱しています（配布時は必ず一緒に配布してください）。

本システムは **外部の地図サービス・APIキー・アカウント連携を一切使用しません**（住所判定・地図表示はすべて同梱データによるオフライン処理）。

## データ

| 名称 | 出典 / ライセンス | 用途 |
|---|---|---|
| 市区町村境界データ | 「国土数値情報（行政区域データ）」（国土交通省）を加工して作成。加工元の簡略化データ: smartnews-smri/japan-topography (MIT) | オフライン住所判定 |
| 市区町村コード表 | 国土地理院「地理院地図」muni.js に基づく | 市区町村コード→名称 |
| 郡名テーブル (gun.json) | geolonia/japanese-addresses (CC0-1.0) の市区町村名から町村の郡名を抽出して作成 | 市区町村コード→郡名（区・郡あり表示） |
| 逆ジオコーダAPI（online/autoモード時） | 国土地理院 逆ジオコーダ https://mreversegeocoder.gsi.go.jp/ | 町丁目の取得（利用時は出典表示） |

## フォント

テロップ描画に使用するフォント（游ゴシック / Noto Sans CJK 等）は、
実行環境にインストールされたものを利用します。各フォントのライセンスに従って
ください（商用配布するフォントを同梱する場合は当該ライセンスの確認が必要）。

---

本ファイルは配布時に製品へ同梱してください。EULA本文および最終的な表記内容は
社内法務の確認を推奨します。
