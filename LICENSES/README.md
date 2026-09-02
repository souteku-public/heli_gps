# LICENSES/ — 配布物に同梱するライセンス全文

系列局へ配布するパッケージには、**このフォルダごと同梱**してください。
概要・出典の一覧は `../THIRD_PARTY_NOTICES.md`、
フェーズ別の考え方は `../docs/LICENSING.md` を参照。

## 収録済み

| ファイル | 対象 | ライセンス | 出所 |
|---|---|---|---|
| `numpy-LICENSE.txt` | numpy | BSD-3-Clause（同梱依存分を含む） | 配布パッケージから複製 |
| `Pillow-LICENSE.txt` | Pillow | HPND（MIT系） | 配布パッケージから複製 |
| `sounddevice-LICENSE.txt` | python-sounddevice | MIT | 標準MIT本文 ※要照合 |
| `PortAudio-LICENSE.txt` | PortAudio（sounddeviceが利用） | MIT系 | 標準本文 ※要照合 |
| `japan-topography-LICENSE.txt` | 市区町村境界データの加工元 | MIT ＋ 国土数値情報の出典 | ※要照合 |

> **※要照合** … 実際に配布するバージョンに付属するライセンス本文と
> 突き合わせて確認・差し替えてください（バージョンで文言が変わることがあります）。
> `numpy` / `Pillow` は実際の配布物から複製済みです。

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
市区町村境界データ:
  「国土数値情報（行政区域データ）」（国土交通省）を加工して作成
  （簡略化: smartnews-smri/japan-topography, MIT）
市区町村コード表:
  国土地理院「地理院地図」muni.js に基づく
郡名テーブル:
  geolonia/japanese-addresses (CC0-1.0) より作成
```
