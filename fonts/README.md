# fonts/ — 同梱フォント置き場

このフォルダに置いたフォントは **テロップ描画で最優先** に使われ、
制御UIのフォント一覧でも**最上位**に表示されます。

配布物にフォントを同梱しておくと、**全系列局で同一の見た目**になります
（局ごとにインストール済みフォントが違っても崩れません）。

## 置いてよいフォント（再配布可のもののみ）

| フォント | ライセンス | 備考 |
|---|---|---|
| **Noto Sans JP** (Bold / Regular) | SIL Open Font License 1.1 | **推奨**。太字があり放送テロップ向き |
| Noto Sans CJK JP | SIL Open Font License 1.1 | 上記の CJK 統合版 |
| IPAex ゴシック / IPA ゴシック | IPAフォントライセンス v1.0 | 太字なし。細い印象になる点に注意 |
| M+ FONTS | SIL Open Font License 1.1 | |

対応拡張子: `.ttf` / `.otf` / `.ttc` / `.otc`

## 置いてはいけないフォント

- **Windows 同梱フォント**（游ゴシック・メイリオ・MS ゴシック等）
  → フォントファイルの**再配布は不可**。各局のWindows環境のものを使う分には問題ありませんが、
    このフォルダに入れて配布してはいけません。
- モリサワ等の**商用フォント**（別途ライセンス契約が必要）

## 入手方法（Noto Sans JP の例）

1. Noto Fonts の配布元（`notofonts.github.io` / `github.com/notofonts/noto-cjk`）から
   `NotoSansJP-Bold.otf` および `NotoSansJP-Regular.otf` を取得
2. このフォルダに置く
3. **同じ場所に `OFL.txt`（ライセンス全文）も必ず置く** ← OFL の必須条件

```
fonts/
├── README.md              （このファイル）
├── OFL.txt                （SIL OFL 1.1 ライセンス全文 ※フォント同梱時は必須）
├── NotoSansJP-Bold.otf
└── NotoSansJP-Regular.otf
```

> **重要**: SIL OFL でフォントを再配布する場合、**ライセンス全文の同梱が必須**です。
> また OFL フォントは「Reserved Font Name」が設定されている場合、
> 改変版に元の名前を使えません（無改変で配布する限り問題ありません）。

## フォントを置かない場合

`fonts/` が空でも動作します。その場合は次の順で自動的に探索します。

1. `fonts/`（このフォルダ）
2. OFL / IPA 系（Noto、IPAゴシック等）
3. 環境依存フォント（游ゴシック、メイリオ等）※EULA 要確認

放送に出す運用（Phase 2）では、**1 または 2 のフォントを使ってください**。
詳細は `docs/LICENSING.md` を参照。
