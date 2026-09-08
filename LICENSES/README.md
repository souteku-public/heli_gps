# LICENSES/ — 配布物に同梱するライセンス全文

系列局へ配布するパッケージには、**このフォルダごと同梱**してください。
概要・出典の一覧は `../THIRD_PARTY_NOTICES.md`、
フェーズ別の考え方は `../docs/LICENSING.md` を参照。

## 収録済み

| ファイル | 対象 | ライセンス | 出所 |
|---|---|---|---|
| `numpy-LICENSE.txt` | numpy | BSD-3-Clause（同梱依存分を含む） | 配布パッケージから複製 |
| `Pillow-LICENSE.txt` | Pillow | HPND（MIT系） | 配布パッケージから複製 |
| `sounddevice-LICENSE.txt` | python-sounddevice | MIT | **上流 LICENSE を 2026-09-08 に取得して複製** |
| `PortAudio-LICENSE.txt` | PortAudio（sounddeviceが利用） | MIT系 | **上流 LICENSE.txt を 2026-09-08 に取得して複製** |
| `japan-topography-LICENSE.txt` | 市区町村境界データの加工元 | **定型ライセンスなし**（README で無償利用・クレジット不要を明示）＋ 国土数値情報の出典 | **2026-09-08 に確認・修正**（旧記載の「MIT」は誤り。LICENSE ファイルは存在しない） |

> `numpy` / `Pillow` は実際の配布物（dist-info）から複製済みです。
> データの出典表記の詳細は `../docs/ATTRIBUTION.md` を参照してください。

## 追加が必要になるケース

| ケース | 追加するもの |
|---|---|
| **Python 本体を同梱**する（PyInstaller等） | `Python-LICENSE.txt`（PSF License）、Tcl/Tk のライセンス |
| **フォントを同梱**する（`../fonts/`） | `OFL.txt`（SIL OFL 1.1 全文）または IPAフォントライセンス全文 ← **OFLは同梱必須** |
| GStreamer を同梱する（**非推奨**） | LGPL-2.1 全文 ＋ 該当コンポーネントの**ソース入手手段** |

## 同梱してはいけないもの

- **GStreamer 本体** … 各局が公式インストーラで導入（同梱しなければLGPLの配布義務は実質発生しません）
- **Blackmagic Desktop Video / DeckLink SDK** … 再配布不可
- **Windows 同梱フォント**（游ゴシック・メイリオ等） … フォントファイルの再配布は不可

## データの出典表記（配布物・必要に応じて番組クレジット）

```
市区町村境界データ（国土数値情報 行政区域データ N03 第3.0版 / N03-21_210101）:
  「国土数値情報（行政区域データ）」（国土交通省）を加工して作成
  （簡略化の加工元: smartnews-smri/japan-topography ※クレジット不要と明示）
市区町村コード表（muni.json）:
  国土地理院ウェブサイト（地理院地図 muni.js）を加工して作成
郡名テーブル（gun.json）:
  geolonia/japanese-addresses (CC0-1.0) より作成 ※表記義務なし
```

放送・公衆送信時に必要なのは上の**2者（国土交通省・国土地理院）への出典表記**のみです。
掲出先・文言は `../docs/ATTRIBUTION.md` §2 を参照。
