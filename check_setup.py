"""導入チェック — 起動前に「足りないもの」を一覧で教える.

    python check_setup.py

Python / numpy / Pillow / tkinter / 同梱データ / 同梱フォント / GStreamer を
順に調べ、OK か NG かと、NG のときの直し方を表示する。

このファイルは **numpy も Pillow も無い状態で動く**必要があるので、
標準ライブラリだけで書いてある。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

OK, NG, WARN = "[ OK ]", "[ NG ]", "[warn]"
_results: list[tuple[str, str, str]] = []   # (状態, 項目, 直し方)


def _say(state: str, item: str, detail: str = "", fix: str = "") -> None:
    line = f"{state} {item}"
    if detail:
        line += f"  … {detail}"
    print(line)
    if state == NG:
        _results.append((state, item, fix))


def check_python() -> None:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if v < (3, 10):
        _say(NG, "Python 3.10 以降", ver,
             "python.org から Python 3.10 以降を入れ直してください"
             "（インストーラで Add python.exe to PATH にチェック）")
    else:
        _say(OK, "Python 3.10 以降", ver)


def check_module(name: str, label: str, fix: str, required: bool = True) -> bool:
    try:
        mod = __import__(name)
    except Exception as e:
        _say(NG if required else WARN, label, str(e), fix)
        return False
    ver = getattr(mod, "__version__", "")
    _say(OK, label, ver)
    return True


def check_pillow() -> None:
    """Pillow 本体と、制御UIが使う ImageTk を別々に見る."""
    if not check_module("PIL", "Pillow（描画）",
                        "python -m pip install -r requirements.txt"):
        return
    try:
        from PIL import ImageTk           # noqa: F401
        _say(OK, "Pillow の ImageTk（配置プレビュー）")
    except Exception as e:
        _say(WARN, "Pillow の ImageTk（配置プレビュー）", str(e),
             "配置プレビューが簡易表示になります。送出自体は動きます")


def check_tkinter() -> None:
    check_module("tkinter", "tkinter（制御UI）",
                 "Python を「Modify」→「tcl/tk and IDLE」に"
                 "チェックを入れて入れ直してください")


def check_data() -> None:
    need = [
        ("nnn_decoder/data/muni.json", "市区町村コード表"),
        ("nnn_decoder/data/muni_boundaries.json.gz", "市区町村境界データ"),
        ("nnn_decoder/data/gun.json", "郡名テーブル"),
    ]
    for rel, label in need:
        p = os.path.join(HERE, rel.replace("/", os.sep))
        if os.path.exists(p):
            _say(OK, f"同梱データ {label}", f"{os.path.getsize(p):,} bytes")
        else:
            _say(NG, f"同梱データ {label}", "見つかりません",
                 f"配布物の {rel} をコピーしてください")


def check_font() -> None:
    d = os.path.join(HERE, "fonts")
    try:
        fonts = [f for f in os.listdir(d)
                 if os.path.splitext(f)[1].lower() in (".ttf", ".otf", ".ttc", ".otc")]
    except OSError:
        fonts = []
    if fonts:
        _say(OK, "同梱フォント", ", ".join(fonts))
        if not os.path.exists(os.path.join(d, "OFL.txt")):
            _say(WARN, "fonts/OFL.txt", "見つかりません",
                 "ライセンス全文です。配布物から戻してください（削除禁止）")
    else:
        _say(WARN, "同梱フォント", "fonts/ にフォントがありません",
             "OS のフォントで代用されます。全局で見た目を揃えるなら"
             " fonts/NotoSansJP-VF.ttf を配置してください")


def _gst_exe() -> str | None:
    exe = shutil.which("gst-launch-1.0")
    if exe:
        return exe
    for p in (r"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin",
              r"C:\gstreamer\1.0\msvc_x86_64\bin"):
        cand = os.path.join(p, "gst-launch-1.0.exe")
        if os.path.exists(cand):
            return cand
    return None


def check_gstreamer() -> None:
    exe = _gst_exe()
    if not exe:
        _say(NG, "GStreamer", "gst-launch-1.0 が見つかりません",
             "gstreamer.freedesktop.org から Windows (MSVC 64-bit) の "
             "Runtime と Development を【Complete】で導入してください")
        return
    _say(OK, "GStreamer", exe)
    # decklink プラグインは Complete でないと入らない。ここが一番よく転ぶ。
    inspect = os.path.join(os.path.dirname(exe), "gst-inspect-1.0.exe")
    if not os.path.exists(inspect):
        inspect = shutil.which("gst-inspect-1.0") or ""
    if not inspect:
        _say(WARN, "decklink プラグイン", "gst-inspect-1.0 が無く確認できません")
        return
    try:
        r = subprocess.run([inspect, "decklinkvideosink"],
                           capture_output=True, timeout=60)
        ok = r.returncode == 0
    except Exception as e:
        _say(WARN, "decklink プラグイン", f"確認できません: {e}")
        return
    if ok:
        _say(OK, "decklink プラグイン", "decklinkvideosink あり")
    else:
        _say(NG, "decklink プラグイン", "decklinkvideosink がありません",
             "GStreamer を【Complete（完全）】で入れ直してください。"
             "Typical では decklink が入りません")


def main() -> int:
    print("=" * 62)
    print(" ヘリGPSスーパー 導入チェック")
    print(f" フォルダ: {HERE}")
    print("=" * 62)
    check_python()
    check_module("numpy", "numpy（信号処理）",
                 "python -m pip install -r requirements.txt")
    check_pillow()
    check_tkinter()
    print("-" * 62)
    check_data()
    check_font()
    print("-" * 62)
    check_gstreamer()
    print("=" * 62)

    if not _results:
        print("\n すべて OK です。起動バッチをダブルクリックしてください。")
        print("   start_heli_preview.bat … まずはこれ（SDI出力なしで安全）")
        print("   start_heli_gst.bat     … Fill/Key 出し")
        print("   start_heli_burnin.bat  … バーンイン（1本出し）")
        return 0

    print(f"\n 足りないものが {len(_results)} 件あります。上から順に直してください。\n")
    for i, (_st, item, fix) in enumerate(_results, 1):
        print(f" {i}. {item}")
        print(f"    → {fix}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
