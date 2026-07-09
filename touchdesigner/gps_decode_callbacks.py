# TouchDesigner Script CHOP コールバック
#
# 入力0: GPS音声を含むオーディオCHOP (Audio Device In CHOP等)
# 出力 : lat / lon / alt / fix / age チャンネル
# 併せて指定したText TOPのテキストを住所文字列で更新する。
#
# 使い方はリポジトリの touchdesigner/README_TD.md を参照。

import sys
import time

# ★環境に合わせて変更: nnn_decoder パッケージがある場所(リポジトリのルート)
HELI_GPS_LIB = r"C:\heli_gps"

if HELI_GPS_LIB not in sys.path:
    sys.path.insert(0, HELI_GPS_LIB)

from nnn_decoder.pipeline import DecoderPipeline          # noqa: E402
from nnn_decoder.geocode import AsyncReverseGeocoder      # noqa: E402

_state = {
    "pipe": None,
    "geo": None,
    "rate": None,
    "baud": None,
    "last_pkt": None,
    "last_time": 0.0,
}


def onSetupParameters(scriptOp):
    page = scriptOp.appendCustomPage("Heli GPS")
    p = page.appendMenu("Baud", label="ビットレート")
    p[0].menuNames = ["1200", "2400"]
    p[0].menuLabels = ["1200 bps", "2400 bps"]
    p[0].default = "1200"
    p = page.appendInt("Audiochan", label="音声チャンネル(0始まり)")
    p[0].default = 0
    p = page.appendStr("Texttop", label="更新するText TOP")
    p[0].default = "overlay_text"
    p = page.appendStr("Textformat", label="表示フォーマット")
    p[0].default = "{address}"
    p = page.appendStr("Staletext", label="受信途絶時の表示")
    p[0].default = ""
    p = page.appendFloat("Staletimeout", label="受信途絶とみなす秒数")
    p[0].default = 5.0
    p = page.appendMenu("Addrlevel", label="住所の詳細度")
    p[0].menuNames = ["pref", "city", "town"]
    p[0].menuLabels = ["都道府県", "市区町村", "町丁目"]
    p[0].default = "city"
    p = page.appendMenu("Geomode", label="住所変換エンジン")
    p[0].menuNames = ["offline", "auto", "online"]
    p[0].menuLabels = ["オフライン(ネット不要・市区町村まで)",
                       "自動(ネット時のみ町丁目補完)",
                       "オンライン(地理院API)"]
    p[0].default = "offline"
    return


def _ensure_pipeline(scriptOp, rate):
    baud = int(scriptOp.par.Baud.eval())
    if (_state["pipe"] is None or _state["rate"] != rate
            or _state["baud"] != baud):
        _state["pipe"] = DecoderPipeline(rate, baud=baud)
        _state["rate"] = rate
        _state["baud"] = baud
    mode = scriptOp.par.Geomode.eval() if hasattr(scriptOp.par, "Geomode") else "offline"
    if _state["geo"] is None or _state.get("geomode") != mode:
        _state["geo"] = AsyncReverseGeocoder(mode=mode)
        _state["geomode"] = mode


def onCook(scriptOp):
    scriptOp.clear()
    if not scriptOp.inputs:
        return
    ain = scriptOp.inputs[0]
    if ain.numChans == 0 or ain.numSamples == 0:
        return
    rate = ain.rate
    _ensure_pipeline(scriptOp, rate)

    chan = min(int(scriptOp.par.Audiochan.eval()), ain.numChans - 1)
    x = ain.numpyArray()[chan]

    for pkt in _state["pipe"].process(x.astype("float64")):
        _state["last_pkt"] = pkt
        _state["last_time"] = time.monotonic()
        _state["geo"].submit(pkt.lat_wgs84, pkt.lon_wgs84)

    pkt = _state["last_pkt"]
    age = time.monotonic() - _state["last_time"] if pkt else 1e9
    # パラメータ未設定(空/0)でも動くよう安全な既定値でフォールバック
    stale_to = float(scriptOp.par.Staletimeout.eval() or 5.0)
    stale = age > stale_to

    # --- Text TOP更新 ---
    top_name = scriptOp.par.Texttop.eval() or "overlay_text"
    top = scriptOp.parent().op(top_name) or op(top_name)
    if top is not None:
        if pkt is None or stale:
            text = scriptOp.par.Staletext.eval()
        else:
            addr = _state["geo"].current
            addr_s = addr.text(scriptOp.par.Addrlevel.eval() or "city") if addr else ""
            text = (scriptOp.par.Textformat.eval() or "{address}").format(
                address=addr_s,
                alt=f"{pkt.alt_m:.0f}",
                lat=f"{pkt.lat_wgs84:.5f}",
                lon=f"{pkt.lon_wgs84:.5f}",
                sats=pkt.satellites if pkt.satellites is not None else "-",
            )
        if top.par.text.eval() != text:
            top.par.text = text

    # --- 出力チャンネル ---
    for name, val in (
        ("lat", pkt.lat_wgs84 if pkt else 0.0),
        ("lon", pkt.lon_wgs84 if pkt else 0.0),
        ("alt", pkt.alt_m if pkt else 0.0),
        ("fix", float(pkt.fix_status) if pkt and not stale else 2.0),
        ("age", min(age, 9999.0)),
    ):
        c = scriptOp.appendChan(name)
        c[0] = val
    return
