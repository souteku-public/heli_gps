# OSC In DAT コールバック — 外部Python制御UIからの操作を受ける
#
# Python制御UI(control_ui.py)が送る /heli/ctrl/<パラメータ名> <値> を受信し、
# HELI_GPSコンテナのControlsパラメータ(またはoverlay_text)へ反映する。
# 反映後は既存の ui_sync(push)が overlay_text / gps_decode に伝える。
#
# OSC In DAT のポートを 9001 に設定し、このDATをコールバックに指定する。

# コンテナの Controls カスタムPar名(setup_ui.py と一致)
_CONTAINER_PARS = {
    "Geomode", "Addrlevel", "Textformat", "Staletext", "Audiochan", "Baud",
    "Fontsize", "Alignx", "Aligny", "Posx", "Posy", "Nudgestep",
    "Fontcolorr", "Fontcolorg", "Fontcolorb",
}


def onReceiveOSC(dat, rowIndex, message, byteData, timeStamp, address, args, peer):
    if not address.startswith("/heli/ctrl/"):
        return
    name = address.rsplit("/", 1)[-1]
    val = args[0] if args else None
    if val is None:
        return
    comp = dat.parent()   # HELI_GPS コンテナ

    # フォントは menu 不一致を避けるため overlay_text.font へ直接設定
    if name == "Font":
        t = comp.op("overlay_text")
        if t is not None:
            try:
                t.par.font = val
            except Exception:
                pass
        return

    if name in _CONTAINER_PARS:
        try:
            setattr(comp.par, name, val)
        except Exception:
            pass
    return
