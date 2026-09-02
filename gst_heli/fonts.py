"""システムにインストールされたフォントの列挙.

制御UIのフォント選択肢を「実在するフォントファイル」から作るための補助。
名前からパスを推測すると存在しない指定になり文字が消えるため、
実ファイルを列挙してパスごと選ばせる。
"""

from __future__ import annotations

import os

# 探索するフォントディレクトリ(同梱fonts/ を先頭に、以降 Windows/Linux/macOS)
_FONT_DIRS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"),
    r"C:\Windows\Fonts",
    os.path.expanduser(r"~\AppData\Local\Microsoft\Windows\Fonts"),
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
    "/System/Library/Fonts",
    "/Library/Fonts",
]

# 配布同梱フォント置き場(リポジトリ直下 fonts/)。一覧の最上位に出す。
_BUNDLED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "fonts")

# 再配布可(SIL OFL / IPAライセンス)のフォント。配布・放送で安全なため最優先。
_OFL_HINTS = ("noto", "ipag", "ipam", "ipaex", "sourcehan", "mplus", "m+")

# その他の日本語フォント(環境依存・EULA要確認)
_JP_HINTS = ("yugoth", "yumin", "meiryo", "msgothic", "msmincho", "biz-ud", "hg")

# 字形の有無を判定するための相異なる漢字サンプル。
# 日本語非対応フォントは、これらを全て同じ「.notdef(□)」で描くので、
# 描画結果が全部同じ=非対応、と判定できる(参照コードポイント不要で確実)。
_JP_SAMPLE = "国東京空市原港"
_cjk_cache: dict[str, bool] = {}


def font_has_japanese(path: str) -> bool:
    """フォントが日本語(漢字)字形を持つか。結果はキャッシュ。

    Pillow が無い環境では判定不能として True(除外しない)を返す。
    """
    if path in _cjk_cache:
        return _cjk_cache[path]
    ok = _test_japanese(path)
    _cjk_cache[path] = ok
    return ok


def _test_japanese(path: str) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return True                      # 判定できない→フォントを除外しない
    try:
        f = ImageFont.truetype(path, 40)
    except Exception:
        return False                     # 開けない(可変サイズ非対応の絵文字等)
    shapes = set()
    drew = 0
    for ch in _JP_SAMPLE:
        try:
            img = Image.new("L", (64, 64), 0)
            ImageDraw.Draw(img).text((4, 4), ch, font=f, fill=255)
            if img.getbbox() is None:
                continue                 # 何も描かれない=その字は無い
            drew += 1
            shapes.add(img.tobytes())
        except Exception:
            continue
    if drew == 0:
        return False
    return len(shapes) > 1               # 相異なる字形=本物の漢字を持つ


def list_system_fonts(japanese_only: bool = True) -> list[tuple[str, str]]:
    """(表示名, フルパス) の一覧を返す(日本語系を上位に、名前順).

    japanese_only=True(既定)では、日本語字形を持たないフォント(欧文専用)を
    除外する。これを選ぶとテロップが消える(□にもならず空白になる)ため。
    """
    found: dict[str, str] = {}
    for d in _FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        try:
            for root, _dirs, files in os.walk(d):
                for fn in files:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in (".ttf", ".ttc", ".otf", ".otc"):
                        name = os.path.splitext(fn)[0]
                        found.setdefault(name, os.path.join(root, fn))
        except OSError:
            continue

    def sort_key(item):
        """同梱fonts/ → OFL/IPA → その他日本語 → 残り の順に並べる."""
        name, path = item
        base = os.path.basename(path).lower()
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(_BUNDLED_DIR):
            rank = 0                                     # 同梱(配布物と同一の見た目)
        elif any(h in base for h in _OFL_HINTS):
            rank = 1                                     # 再配布可(OFL/IPA)
        elif any(h in base for h in _JP_HINTS):
            rank = 2                                     # 環境依存の日本語フォント
        else:
            rank = 3
        return (rank, name.lower())

    items = sorted(found.items(), key=sort_key)
    if japanese_only:
        filtered = [(n, p) for (n, p) in items if font_has_japanese(p)]
        if filtered:                     # 万一全滅したら元の一覧を返す
            items = filtered
    return items
