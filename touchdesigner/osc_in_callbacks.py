# TouchDesigner OSC In DAT コールバック (方式B: 外部デコード+OSC受信)
#
# PC側で nnn_decoder のGUIアプリ(OSC送出ON)を動かし、TDはOSCで
# 住所文字列を受けてText TOPに表示するだけの構成に使う。
#
# OSC In DAT のポートを 9000 に設定し、このDATをコールバックに指定する。

TEXT_TOP = "overlay_text"   # 更新するText TOPの名前


def onReceiveOSC(dat, rowIndex, message, byteData, timeStamp, address, args, peer):
    if address == "/heli/address" and args:
        top = dat.parent().op(TEXT_TOP) or op(TEXT_TOP)
        if top is not None and top.par.text.eval() != args[0]:
            top.par.text = args[0]
    return
