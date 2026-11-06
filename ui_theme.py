"""control_ui 用のテーマ(ttk スタイル) — ライト/ダーク + 文字サイズ倍率.

フラット・余白多め・システムフォント・アクセント色ボタン、という
Apple ライクな見た目に整える。tkinter/ttk の範囲でできる範囲(角丸や影は
不可)だが、配色・字体・余白で十分に洗練された印象にする。

全画面の操作卓で使う想定なので、既定の文字サイズ倍率は 2.0。
"""

from __future__ import annotations

import tkinter.font as tkfont

# 全画面で離れて見る想定の既定倍率(1.0 = 従来の大きさ)
DEFAULT_SCALE = 2.0

# ---- パレット ----
LIGHT = {
    "bg": "#f5f5f7",        # ページ背景
    "card": "#ffffff",      # 入力欄・カード
    "ink": "#1d1d1f",       # 主要文字
    "muted": "#6e6e73",     # 補助文字
    "accent": "#0071e3",    # アクセント(ボタン)
    "accent_hi": "#0077ed",
    "accent_lo": "#006adf",
    "accent_dim": "#bcd9f5",
    "border": "#d2d2d7",    # 罫線
    "track": "#e3e3e8",     # スライダーの溝
    "btn": "#e8e8ed",       # 通常ボタン
    "btn_hi": "#dedee3",
    "btn_lo": "#d0d0d6",
    "canvas": "#22262f",    # 配置プレビューの地
    "ok": "#1a9d47",        # 受信中(緑)
    "warn": "#d23b3b",      # 途絶(赤)
    "neutral": "#8e8e93",   # 未接続(グレー)
}

DARK = {
    "bg": "#1c1c1e",
    "card": "#2c2c2e",
    "ink": "#f2f2f7",
    "muted": "#98989f",
    "accent": "#0a84ff",
    "accent_hi": "#3d9bff",
    "accent_lo": "#0070e0",
    "accent_dim": "#2a4a68",
    "border": "#3a3a3c",
    "track": "#3a3a3c",
    "btn": "#3a3a3c",
    "btn_hi": "#48484a",
    "btn_lo": "#2c2c2e",
    "canvas": "#101014",
    "ok": "#30d158",
    "warn": "#ff453a",
    "neutral": "#6e6e73",
}

PALETTES = {"light": LIGHT, "dark": DARK}

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


def apply_theme(root, mode: str = "light", scale: float = DEFAULT_SCALE) -> dict:
    """root にテーマを適用し、パレット/フォント情報を返す.

    mode  … "light" / "dark"
    scale … 文字サイズの倍率(1.0=従来)。全画面運用の既定は 2.0。

    何度呼んでもよい(切替のたびに呼ぶ)。返り値の dict は
    control_ui が tk.Label 等の素のウィジェットを塗るのに使う。
    """
    from tkinter import ttk

    pal = dict(PALETTES.get(mode, LIGHT))
    fam = pick_font_family(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")       # 配色を細かく設定できるベーステーマ
    except Exception:
        pass

    def sz(n: int) -> int:
        return max(7, int(round(n * scale)))

    base = (fam, sz(10))
    bold = (fam, sz(10), "bold")
    pad = max(2, int(round(4 * scale)))
    bg, card, ink = pal["bg"], pal["card"], pal["ink"]
    muted, accent, border = pal["muted"], pal["accent"], pal["border"]
    root.configure(bg=bg)

    style.configure(".", background=bg, foreground=ink, font=base,
                    bordercolor=border)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=ink)
    style.configure("Muted.TLabel", background=bg, foreground=muted)
    style.configure("H1.TLabel", background=bg, foreground=ink,
                    font=(fam, sz(15), "bold"))
    style.configure("Section.TLabel", background=bg, foreground=muted,
                    font=(fam, sz(9), "bold"))
    style.configure("TCheckbutton", background=bg, foreground=ink, font=base)
    style.map("TCheckbutton", background=[("active", bg)],
              foreground=[("disabled", muted)])
    style.configure("TRadiobutton", background=bg, foreground=ink, font=base)
    style.map("TRadiobutton", background=[("active", bg)])

    # セクション枠(ラベルフレーム)
    style.configure("TLabelframe", background=bg, borderwidth=0, relief="flat")
    style.configure("TLabelframe.Label", background=bg, foreground=muted,
                    font=bold)

    # 通常ボタン(淡色・フラット)
    style.configure("TButton", background=pal["btn"], foreground=ink,
                    borderwidth=0, relief="flat",
                    padding=(pad * 3, pad + 1), font=base)
    style.map("TButton",
              background=[("pressed", pal["btn_lo"]), ("active", pal["btn_hi"])],
              foreground=[("disabled", muted)])

    # 詰めたボタン(プリセットの呼出/保存など、横に並べるもの)
    style.configure("Compact.TButton", background=pal["btn"], foreground=ink,
                    borderwidth=0, relief="flat", padding=(pad, pad - 1),
                    font=base)
    style.map("Compact.TButton",
              background=[("pressed", pal["btn_lo"]), ("active", pal["btn_hi"])])

    # アクセントボタン(決定など)
    style.configure("Accent.TButton", background=accent, foreground="#ffffff",
                    borderwidth=0, relief="flat",
                    padding=(pad * 3 + 2, pad + 2), font=bold)
    style.map("Accent.TButton",
              background=[("pressed", pal["accent_lo"]),
                          ("active", pal["accent_hi"]),
                          ("disabled", pal["accent_dim"])],
              foreground=[("disabled", "#eaf3fd")])

    # 入力系
    for w in ("TEntry", "TSpinbox"):
        style.configure(w, fieldbackground=card, background=card, foreground=ink,
                        bordercolor=border, lightcolor=border, darkcolor=border,
                        insertcolor=ink, borderwidth=1, relief="flat",
                        padding=pad, arrowsize=sz(12))
    style.configure("TCombobox", fieldbackground=card, background=card,
                    foreground=ink, bordercolor=border, lightcolor=border,
                    darkcolor=border, borderwidth=1, arrowsize=sz(13),
                    padding=pad)
    style.map("TCombobox", fieldbackground=[("readonly", card)],
              foreground=[("readonly", ink)])
    # ドロップダウンのリスト部分は ttk ではなく tk のオプションで塗る
    try:
        root.option_add("*TCombobox*Listbox.background", card)
        root.option_add("*TCombobox*Listbox.foreground", ink)
        root.option_add("*TCombobox*Listbox.selectBackground", accent)
        root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        root.option_add("*TCombobox*Listbox.font", base)
    except Exception:
        pass

    # スライダー・スクロールバー
    style.configure("Horizontal.TScale", background=bg,
                    troughcolor=pal["track"], borderwidth=0)
    style.configure("Vertical.TScrollbar", background=pal["btn"],
                    troughcolor=bg, bordercolor=bg, arrowcolor=muted,
                    borderwidth=0)
    style.configure("TSeparator", background=border)

    pal["family"] = fam
    pal["scale"] = scale
    pal["mode"] = mode
    pal["sz"] = sz
    return pal
