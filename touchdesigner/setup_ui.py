# HELI_GPS コントロールUI セットアップ (push方式・別ウィンドウ表示対応)
#
# HELI_GPSコンテナに「Controls」カスタムパラメータページを作り、
# 値が変わるたびに gps_decode / overlay_text へ push する。
# overlay_text 側は常に定数値を保持するので、式バインドのように
# 0になって文字が消えることがない。
#
# 後付け実行(Textport, Alt+T):
#   exec(open(r"C:\heli_gps\touchdesigner\setup_ui.py", encoding="utf-8").read())
#
# 実行後、別ウィンドウでグラフィカルに操作:
#   op('/project1/HELI_GPS').openParameters()

# Controls(コンテナ) → 実ノード のパラメータ対応表
#   キー: コンテナのカスタムPar名 / 値: (対象ノード名, 対象Par名)
CONTROL_MAP = {
    "Geomode":    ("gps_decode",   "Geomode"),
    "Addrlevel":  ("gps_decode",   "Addrlevel"),
    "Textformat": ("gps_decode",   "Textformat"),
    "Staletext":  ("gps_decode",   "Staletext"),
    "Audiochan":  ("gps_decode",   "Audiochan"),
    "Baud":       ("gps_decode",   "Baud"),
    "Font":       ("overlay_text", "font"),
    "Fontsize":   ("overlay_text", "fontsizex"),
    "Alignx":     ("overlay_text", "alignx"),
    "Aligny":     ("overlay_text", "aligny"),
    "Posx":       ("overlay_text", "positionx"),
    "Posy":       ("overlay_text", "positiony"),
    "Fontcolorr": ("overlay_text", "fontcolorr"),
    "Fontcolorg": ("overlay_text", "fontcolorg"),
    "Fontcolorb": ("overlay_text", "fontcolorb"),
}


def setup_ui(container=None):
    c = container or op("/project1/HELI_GPS") or op("/HELI_GPS")
    if c is None:
        print("HELI_GPS が見つかりません。先に build_network.py を実行してください。")
        return
    dec = c.op("gps_decode")
    text = c.op("overlay_text")
    if dec is None or text is None:
        print("gps_decode / overlay_text が見つかりません。")
        return

    # フォント候補
    try:
        font_names = list(text.par.font.menuNames)
        font_labels = list(text.par.font.menuLabels)
    except Exception:
        font_names = font_labels = []
    if not font_names:
        font_names = ["Yu Gothic UI", "Yu Gothic", "BIZ UDPGothic",
                      "Meiryo", "MS Gothic", "Noto Sans JP"]
        font_labels = font_names

    # --- Controlsページを作り直す ---
    for pg in list(c.customPages):
        if pg.name == "Controls":
            pg.destroy()
    page = c.appendCustomPage("Controls")

    # ===== 住所 =====
    p = page.appendMenu("Geomode", label="住所変換モード")[0]
    p.menuNames = ["offline", "auto", "online"]
    p.menuLabels = ["オフライン(ネット不要)", "自動(ネット時は町丁目補完)",
                    "オンライン(地理院API)"]
    p.default = "offline"
    p = page.appendMenu("Addrlevel", label="住所の粒度")[0]
    p.menuNames = ["pref", "muni", "city", "town"]
    p.menuLabels = ["都道府県", "市町村(政令市は市まで)",
                    "市区町村(区あり)", "町丁目(要ネット)"]
    p.default = "muni"
    p = page.appendStr("Textformat", label="表示書式")[0]
    p.default = "{address}上空"
    p = page.appendStr("Staletext", label="受信途絶時の表示")[0]
    p.default = ""
    p = page.appendInt("Audiochan", label="GPS音声ch(0始まり)")[0]
    p.default = 2
    p.normMin, p.normMax = 0, 15
    p = page.appendMenu("Baud", label="ビットレート")[0]
    p.menuNames = ["1200", "2400"]
    p.menuLabels = ["1200 bps", "2400 bps"]
    p.default = "1200"

    # ===== テキスト表示 =====
    p = page.appendMenu("Font", label="フォント")[0]
    p.menuNames = font_names
    p.menuLabels = font_labels
    p.default = font_names[0]
    p = page.appendFloat("Fontsize", label="文字サイズ")[0]
    p.default = 90
    p.normMin, p.normMax = 10, 300
    p.clampMin = True
    p = page.appendMenu("Alignx", label="横位置基準")[0]
    p.menuNames = ["left", "center", "right"]
    p.menuLabels = ["左", "中央", "右"]
    p.default = "center"
    p = page.appendMenu("Aligny", label="縦位置基準")[0]
    p.menuNames = ["bottom", "center", "top"]
    p.menuLabels = ["下", "中央", "上"]
    p.default = "bottom"
    p = page.appendXY("Pos", label="位置(X,Y)px")
    p[0].default, p[1].default = 0, 60
    p = page.appendFloat("Nudgestep", label="矢印キーの移動量(px)")[0]
    p.default = 1
    p.normMin, p.normMax = 1, 50
    p.clampMin = True
    p = page.appendRGB("Fontcolor", label="文字色")
    for i in range(3):
        p[i].default = 1.0

    # ===== 対象パラメータを定数モードにして初期値をpush =====
    # (式バインドを使わない = 0で消える事故を防ぐ)
    for cpar, (opname, tpar) in CONTROL_MAP.items():
        tgt = c.op(opname)
        if tgt is None:
            continue
        try:
            getattr(tgt.par, tpar).mode = ParMode.CONSTANT
            setattr(tgt.par, tpar, getattr(c.par, cpar).eval())
        except Exception as e:
            print(f"init push失敗 {opname}.{tpar}: {e}")

    # アルファと背景は常に固定(文字は必ず不透明、背景は透明=Keyになる)
    for n, v in (("fontalpha", 1.0), ("bgalpha", 0.0)):
        try:
            getattr(text.par, n).mode = ParMode.CONSTANT
            setattr(text.par, n, v)
        except Exception:
            pass

    # ===== 値変更を実ノードへpushする Parameter Execute DAT =====
    pe = c.op("ui_sync") or c.create(parameterexecuteDAT, "ui_sync")
    pe.nodeX, pe.nodeY = 700, 380

    def _setpar(o, names, val):
        for n in names:
            try:
                setattr(o.par, n, val)
                return True
            except Exception:
                pass
        return False

    _setpar(pe, ("op", "ops"), c.path)
    _setpar(pe, ("pars", "parameters"), " ".join(CONTROL_MAP.keys()))
    _setpar(pe, ("builtin",), False)
    _setpar(pe, ("custom",), True)
    _setpar(pe, ("valuechange",), True)
    _setpar(pe, ("active",), True)
    pe.text = (
        "MAP = " + repr(CONTROL_MAP) + "\n"
        "def onValueChange(par, prev):\n"
        "    m = MAP.get(par.name)\n"
        "    if not m: return\n"
        "    t = par.owner.op(m[0])\n"
        "    if t is None: return\n"
        "    try: setattr(t.par, m[1], par.eval())\n"
        "    except Exception: pass\n"
        "    return\n"
    )

    print("=== コントロールUIを作成しました(push方式) ===")
    print("別ウィンドウで開く: op('/project1/HELI_GPS').openParameters()")


setup_ui()
try:
    (op("/project1/HELI_GPS") or op("/HELI_GPS")).openParameters()
except Exception:
    pass
