"""control_ui 用の Apple 風テーマ(ttk スタイル).

フラット・淡色・余白多め・システムフォント・アクセント色ボタン、という
Apple ライクな見た目に整える。tkinter/ttk の範囲でできる範囲(角丸や影は
不可)だが、配色・字体・余白で十分に洗練された印象にする。
"""

from __future__ import annotations

import tkinter.font as tkfont

# ---- パレット(Apple ライトテーマ風) ----
BG = "#f5f5f7"          # ページ背景(薄いグレー)
CARD = "#ffffff"        # 入力欄・カード
INK = "#1d1d1f"         # 主要文字
MUTED = "#6e6e73"       # 補助文字
ACCENT = "#0071e3"      # アクセント(ボタン)
ACCENT_HOVER = "#0077ed"
BORDER = "#d2d2d7"      # 罫線
TRACK = "#e3e3e8"       # スライダーの溝
OK = "#1a9d47"          # 受信中(緑)
WARN = "#d23b3b"        # 途絶(赤)
NEUTRAL = "#8e8e93"     # 未接続(グレー)

# 好ましいUIフォント(日本語対応を優先)
_FONT_PREF = [
    "Yu Gothic UI", "Meiryo UI", "Meiryo",          # Windows
    "Hiragino Kaku Gothic ProN", "Hiragino Sans",   # macOS
    "Noto Sans CJK JP", "Noto Sans JP",             # Linux
    "Segoe UI", "Helvetica Neue", "Arial",
]


def pick_font_family(root) -> str:
    try:
        fams = set(tkfont.families(root))
    except Exception:
        return "TkDefaultFont"
    for f in _FONT_PREF:
        if f in fams:
            return f
    return "TkDefaultFont"


def apply_theme(root) -> dict:
    """root に Apple 風テーマを適用し、パレット/フォント情報を返す."""
    from tkinter import ttk

    fam = pick_font_family(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")       # 配色を細かく設定できるベーステーマ
    except Exception:
        pass

    base = (fam, 10)
    root.configure(bg=BG)

    style.configure(".", background=BG, foreground=INK, font=base,
                    bordercolor=BORDER)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("H1.TLabel", background=BG, foreground=INK, font=(fam, 15, "bold"))
    style.configure("Section.TLabel", background=BG, foreground=MUTED,
                    font=(fam, 9, "bold"))

    # セクション枠(ラベルフレーム)
    style.configure("TLabelframe", background=BG, borderwidth=0, relief="flat")
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED,
                    font=(fam, 10, "bold"))

    # 通常ボタン(淡色・フラット)
    style.configure("TButton", background="#e8e8ed", foreground=INK,
                    borderwidth=0, relief="flat", padding=(12, 6), font=base)
    style.map("TButton",
              background=[("pressed", "#d0d0d6"), ("active", "#dedee3")],
              foreground=[("disabled", "#b0b0b6")])

    # アクセントボタン(決定など)
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    borderwidth=0, relief="flat", padding=(14, 7),
                    font=(fam, 10, "bold"))
    style.map("Accent.TButton",
              background=[("pressed", "#006adf"), ("active", ACCENT_HOVER),
                          ("disabled", "#bcd9f5")],
              foreground=[("disabled", "#eaf3fd")])

    # 入力系(白地・細罫)
    for w in ("TEntry", "TSpinbox"):
        style.configure(w, fieldbackground=CARD, background=CARD, foreground=INK,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        borderwidth=1, relief="flat", padding=4, arrowsize=12)
    style.configure("TCombobox", fieldbackground=CARD, background=CARD,
                    foreground=INK, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, borderwidth=1, arrowsize=13, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", CARD)])

    # スライダー
    style.configure("Horizontal.TScale", background=BG, troughcolor=TRACK,
                    borderwidth=0)

    return {"family": fam, "bg": BG, "card": CARD, "ink": INK, "muted": MUTED,
            "accent": ACCENT, "border": BORDER, "ok": OK, "warn": WARN,
            "neutral": NEUTRAL}
