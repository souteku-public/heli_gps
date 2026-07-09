# Keyboard In DAT コールバック — 矢印キーでテロップ位置を微調整
#
# 上下左右キーで overlay_text の表示位置(HELI_GPSコンテナの Pos パラメータ)を
# 動かす。Shift同時押しで大きく動く。
#
# 使い方はネットワーク自動構築(build_network.py)で自動配置される。
# 手動配置する場合:
#   1. HELI_GPS内に Keyboard In DAT を作成
#   2. このスクリプトをコールバックDATに貼り、Keyboard In DATのCallbacksに指定
#
# 位置の基準: overlay_text の Position は「中心からのオフセット(px)」。
# 画面右が +X、上が +Y。ここでは見た目に合わせ
#   右キー=+X / 左キー=-X / 上キー=+Y / 下キー=-Y とする。


def _step(dat):
    # ステップ幅: 通常1px、Shiftで10px(コンテナのNudgestepがあれば優先)
    try:
        base = float(dat.parent().par.Nudgestep.eval())
    except Exception:
        base = 1.0
    return base


def onKey(dat, key, character, alt, lAlt, rAlt, ctrl, lCtrl, rCtrl,
          shift, lShift, rShift, state, time):
    if not state:          # キーを押した瞬間だけ処理(離した時は無視)
        return
    if key not in ("left", "right", "up", "down"):
        return
    comp = dat.parent()    # HELI_GPS コンテナ
    step = _step(dat) * (10.0 if shift else 1.0)
    try:
        if key == "left":
            comp.par.Posx -= step
        elif key == "right":
            comp.par.Posx += step
        elif key == "up":
            comp.par.Posy += step
        elif key == "down":
            comp.par.Posy -= step
    except Exception as e:
        # Pos が未生成の場合など
        debug("nudge失敗:", e)
    return


# Keyboard In DATが要求する他のコールバックは空実装(無くてもよいが明示)
def onValueChange(dat, key, character, prevValue, value):
    return
