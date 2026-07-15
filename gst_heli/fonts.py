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


def list_system_fonts() -> list[tuple[str, str]]:
    """(表示名, フルパス) の一覧を返す(日本語系を上位に、名前順)."""
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

    return sorted(found.items(), key=sort_key)
