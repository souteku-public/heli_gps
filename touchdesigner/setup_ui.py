# HELI_GPS コントロールUI セットアップスクリプト
#
# HELI_GPSコンテナに「Controls」カスタムパラメータページを追加し、
# gps_decode(住所変換モード/粒度/書式)と overlay_text(フォント/サイズ/
# 位置/色/整列)を1画面から操作できるようにする。
#
# 既存ネットワークへの後付け実行(Textport, Alt+T):
#   exec(open(r"C:\heli_gps\touchdesigner\setup_ui.py", encoding="utf-8").read())
#
# 実行後: /project1/HELI_GPS を選択して `p` を押すと「Controls」タブに
# すべての操作項目が並ぶ。これがオペレーター用UIになる。

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

    # フォント候補(overlay_textのfontメニューがあればそれを使う)
    try:
        font_names = list(text.par.font.menuNames)
        font_labels = list(text.par.font.menuLabels)
    except Exception:
        font_names = font_labels = []
    if not font_names:
        font_names = ["Yu Gothic UI", "Yu Gothic", "BIZ UDPGothic",
                      "Meiryo", "MS Gothic", "Noto Sans JP"]
        font_labels = font_names

    # --- Controlsページを作り直す(重複防止) ---
    for pg in list(c.customPages):
        if pg.name == "Controls":
            pg.destroy()
    page = c.appendCustomPage("Controls")

    # ===== 住所変換 =====
    p = page.appendMenu("Geomode", label="住所変換モード")[0]
    p.menuNames = ["offline", "auto", "online"]
    p.menuLabels = ["オフライン(ネット不要)", "自動(ネット時は町丁目補完)",
                    "オンライン(地理院API)"]
    p.default = "offline"

    p = page.appendMenu("Addrlevel", label="住所の粒度")[0]
    p.menuNames = ["pref", "city", "town"]
    p.menuLabels = ["都道府県", "市区町村", "町丁目"]
    p.default = "city"

    p = page.appendStr("Textformat", label="表示書式")[0]
    p.default = "{address}"
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
    p.default = 72
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
    p[0].default = 0
    p[1].default = 60

    p = page.appendRGB("Fontcolor", label="文字色")
    for i in range(3):
        p[i].default = 1.0
    p = page.appendFloat("Fontalpha", label="文字の不透明度")[0]
    p.default = 1.0
    p.normMin, p.normMax = 0, 1
    p.clampMin = p.clampMax = True

    # ===== バインド(UI → 各ノード) =====
    # 対象パラメータをEXPRESSIONモードにしてコンテナのカスタムPを参照させる。
    # UIを変えると即座に反映される。
    def bind(target_op, target_par, expr):
        try:
            par = getattr(target_op.par, target_par)
            par.mode = ParMode.EXPRESSION
            par.expr = expr
        except Exception as e:
            print(f"bind失敗 {target_op.name}.{target_par}: {e}")

    P = "parent().par."
    # gps_decode 側
    bind(dec, "Geomode", f"{P}Geomode.eval()")
    bind(dec, "Addrlevel", f"{P}Addrlevel.eval()")
    bind(dec, "Textformat", f"{P}Textformat.eval()")
    bind(dec, "Staletext", f"{P}Staletext.eval()")
    bind(dec, "Audiochan", f"{P}Audiochan.eval()")
    bind(dec, "Baud", f"{P}Baud.eval()")
    # overlay_text 側 (fontsizex等は実パラメータ名)
    bind(text, "font", f"{P}Font.eval()")
    bind(text, "fontsizex", f"{P}Fontsize.eval()")
    bind(text, "alignx", f"{P}Alignx.eval()")
    bind(text, "aligny", f"{P}Aligny.eval()")
    bind(text, "positionx", f"{P}Posx.eval()")
    bind(text, "positiony", f"{P}Posy.eval()")
    bind(text, "fontcolorr", f"{P}Fontcolorr.eval()")
    bind(text, "fontcolorg", f"{P}Fontcolorg.eval()")
    bind(text, "fontcolorb", f"{P}Fontcolorb.eval()")
    bind(text, "fontalpha", f"{P}Fontalpha.eval()")

    print("=== コントロールUIを作成しました ===")
    print("HELI_GPS を選択して `p` を押し、「Controls」タブで操作してください。")


setup_ui()
