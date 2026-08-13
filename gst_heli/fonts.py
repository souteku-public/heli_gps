"""システムにインストールされたフォントの列挙.

制御UIのフォント選択肢を「実在するフォントファイル」から作るための補助。
名前からパスを推測すると存在しない指定になり文字が消えるため、
実ファイルを列挙してパスごと選ばせる。
"""

from __future__ import annotations

import os

# 探索するフォントディレクトリ(Windows/Linux/macOS)
_FONT_DIRS = [
    r"C:\Windows\Fonts",
    os.path.expanduser(r"~\AppData\Local\Microsoft\Windows\Fonts"),
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
    "/System/Library/Fonts",
    "/Library/Fonts",
]

# 日本語向けに優先して上位に出したいファイル名の一部(小文字比較)
_JP_HINTS = ("yugoth", "yumin", "meiryo", "msgothic", "msmincho", "biz-ud",
             "notosanscjk", "notoserifcjk", "ipag", "ipam", "hg")

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
        name, path = item
        base = os.path.basename(path).lower()
        jp = 0 if any(h in base for h in _JP_HINTS) else 1
        return (jp, name.lower())

    items = sorted(found.items(), key=sort_key)
    if japanese_only:
        filtered = [(n, p) for (n, p) in items if font_has_japanese(p)]
        if filtered:                     # 万一全滅したら元の一覧を返す
            items = filtered
    return items
