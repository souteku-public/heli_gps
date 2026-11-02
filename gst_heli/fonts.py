"""システムにインストールされたフォントの列挙と、ライセンス区分の判定.

制御UIのフォント選択肢を「実在するフォントファイル」から作るための補助。
名前からパスを推測すると存在しない指定になり文字が消えるため、
実ファイルを列挙してパスごと選ばせる。

さらに **ライセンス区分**(kind)を付けて返す。放送に出すフォントは
「配布物に同梱したOFLフォント」か「Windows同梱フォント」に限るのが安全で、
市販フォント(モリサワ等)をオペレーターが誤って選ぶ事故を防ぐため、
UI側では既定で kind="other" を隠す(docs/ATTRIBUTION.md §4 参照)。

  kind="bundled" … 配布物の fonts/ にある同梱フォント(SIL OFL)。最優先・最安全
  kind="os"      … OS同梱フォント。Windowsの場合は下の許可リストに一致するもの
  kind="other"   … それ以外(後から入れたフォント)。**EULA要確認**
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

# Windows が標準で同梱する日本語フォントのファイル名(拡張子なし・小文字)。
#
# ディレクトリだけでは判定できない。市販フォント(モリサワ等)を全ユーザー向けに
# インストールすると、それらも C:\Windows\Fonts に入るため。
# そこで「Windows同梱である」ことは**ファイル名の許可リスト**で判定する。
_WINDOWS_BUNDLED = {
    "yugothb", "yugothm", "yugothl", "yugothr", "yugothib", "yugothic",
    "yuminl", "yumin", "yumindb",
    "meiryo", "meiryob",
    "msgothic", "msmincho",
    "biz-udgothicr", "biz-udgothicb", "biz-udpgothicr", "biz-udpgothicb",
    "biz-udminchom", "biz-udpminchom",
    "uddigikyokashon-b", "uddigikyokashon-r",
    "uddigikyokashonk-b", "uddigikyokashonk-r",
    "uddigikyokashonp-b", "uddigikyokashonp-r",
}

# Linux / macOS のシステムフォントディレクトリ。
# 本番環境は Windows だが、開発・検証時にここのフォントを使えるようにしておく。
_UNIX_SYSTEM_DIRS = ("/usr/share/fonts", "/System/Library/Fonts")

# 再配布可(SIL OFL / IPAライセンス)のフォント。配布・放送で安全なため最優先。
_OFL_HINTS = ("noto", "ipag", "ipam", "ipaex", "sourcehan", "mplus", "m+")

# その他の日本語フォント(環境依存・EULA要確認)
_JP_HINTS = ("yugoth", "yumin", "meiryo", "msgothic", "msmincho", "biz-ud", "hg")

# よく使う日本語フォントの表示名(一覧を読みやすくするだけ。判定には使わない)
_PRETTY = {
    "notosansjp-vf": "Noto Sans JP（同梱）",
    "notosansjp-bold": "Noto Sans JP Bold",
    "notosansjp-regular": "Noto Sans JP",
    "yugothb": "游ゴシック Bold",
    "yugothm": "游ゴシック Medium",
    "yugothl": "游ゴシック Light",
    "yugothr": "游ゴシック Regular",
    "yuminb": "游明朝 Bold",
    "yumin": "游明朝",
    "meiryo": "メイリオ",
    "meiryob": "メイリオ Bold",
    "msgothic": "MS ゴシック",
    "msmincho": "MS 明朝",
    "biz-udgothicr": "BIZ UDゴシック",
    "biz-udgothicb": "BIZ UDゴシック Bold",
    "biz-udpgothicr": "BIZ UD Pゴシック",
    "biz-udpgothicb": "BIZ UD Pゴシック Bold",
}

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


def classify_font(path: str) -> str:
    """フォントのライセンス区分を返す: "bundled" / "os" / "other".

    "other" は後からインストールされたフォント。市販フォント(モリサワ等)が
    ここに該当するため、放送に出す前に EULA の確認が必要。
    """
    ap = os.path.abspath(path)
    if os.path.dirname(ap) == os.path.abspath(_BUNDLED_DIR):
        return "bundled"
    stem = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0].lower()
    # 区切り文字を "/" に統一して判定する(Linux上でWindowsパスを扱う検証のため)
    low = path.replace("\\", "/").lower()
    if "/windows/fonts/" in low or low.startswith("windows/fonts/"):
        # Windows のフォントフォルダ。同梱フォントの許可リストに載っていれば "os"。
        # 載っていなければ後入れ(市販フォント等)とみなす。
        return "os" if stem in _WINDOWS_BUNDLED else "other"
    if "/microsoft/windows/fonts/" in low:
        return "other"                   # ユーザー単位インストール=後入れ
    if any(ap.startswith(d) for d in _UNIX_SYSTEM_DIRS):
        return "os"
    return "other"


def pretty_name(path: str) -> str:
    """一覧表示用の名前(既知の日本語フォントは読みやすい名前にする)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return _PRETTY.get(stem.lower(), stem)


def list_system_fonts(japanese_only: bool = True,
                      include_other: bool = False) -> list[tuple[str, str, str]]:
    """(表示名, フルパス, 区分) の一覧を返す(安全なものを上位に、名前順).

    japanese_only=True(既定)では、日本語字形を持たないフォント(欧文専用)を
    除外する。これを選ぶとテロップが消える(□にもならず空白になる)ため。

    include_other=False(既定)では、区分 "other"(後入れフォント)を除外する。
    市販フォントを誤って放送に出す事故を防ぐため。UI の
    「その他のフォントも表示」で True にできる。
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
                        found.setdefault(os.path.join(root, fn), "")
        except OSError:
            continue

    items: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for path in found:
        kind = classify_font(path)
        if kind == "other" and not include_other:
            continue
        name = pretty_name(path)
        if name in seen:                 # 同名(別ディレクトリ)は先勝ち
            continue
        seen.add(name)
        items.append((name, path, kind))

    def sort_key(item):
        """同梱 → OFL/IPA → その他日本語 → 残り の順に並べる."""
        name, path, kind = item
        base = os.path.basename(path).lower()
        if kind == "bundled":
            rank = 0                                     # 同梱(配布物と同一の見た目)
        elif any(h in base for h in _OFL_HINTS):
            rank = 1                                     # 再配布可(OFL/IPA)
        elif any(h in base for h in _JP_HINTS):
            rank = 2                                     # OS同梱の日本語フォント
        else:
            rank = 3
        return (rank, name.lower())

    items.sort(key=sort_key)
    if japanese_only:
        filtered = [it for it in items if font_has_japanese(it[1])]
        if filtered:                     # 万一全滅したら元の一覧を返す
            items = filtered
    return items


def default_font() -> tuple[str, str, str] | None:
    """既定で選ぶフォント(同梱 Noto Sans JP)。無ければ一覧の先頭."""
    items = list_system_fonts()
    for it in items:
        if it[2] == "bundled":
            return it
    return items[0] if items else None
