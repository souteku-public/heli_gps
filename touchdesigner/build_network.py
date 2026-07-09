# TouchDesigner ネットワーク自動構築スクリプト
#
# TDのTextport(Alt+T)で次を実行するとネットワークの雛形を自動生成する:
#   exec(open(r"C:\heli_gps\touchdesigner\build_network.py", encoding="utf-8").read())
#
# 生成物 (/project1/HELI_GPS):
#   audio_in (Audio Device In CHOP)  … UltraStudioのEMB音声
#   gps_decode (Script CHOP)         … GPS復調+住所変換
#   overlay_text (Text TOP 1920x1080 RGBA) … 表示文字
#   sdi_out (Video Device Out TOP)   … 1080i Fill&Key出力
#
# デバイス選択・キーヤー設定など環境依存のパラメータは
# README_TD.md の手順に従って手動で設定すること。

import os

HELI_GPS_LIB = r"C:\heli_gps"   # ★リポジトリの場所に合わせて変更

root = op("/project1")
if root is None:
    root = op("/").create(baseCOMP, "project1")

c = root.op("HELI_GPS") or root.create(containerCOMP, "HELI_GPS")

# --- 音声入力 ---
audio = c.op("audio_in") or c.create(audiodeviceinCHOP, "audio_in")
audio.nodeX, audio.nodeY = 0, 200
try:
    audio.par.active = True
except Exception:
    pass

# --- 復調Script CHOP + コールバック ---
cb = c.op("gps_decode_callbacks") or c.create(textDAT, "gps_decode_callbacks")
cb.nodeX, cb.nodeY = 200, 350
cb_path = os.path.join(HELI_GPS_LIB, "touchdesigner", "gps_decode_callbacks.py")
with open(cb_path, encoding="utf-8") as f:
    cb.text = f.read()

dec = c.op("gps_decode") or c.create(scriptCHOP, "gps_decode")
dec.nodeX, dec.nodeY = 200, 200
dec.par.callbacks = "gps_decode_callbacks"
dec.inputConnectors[0].connect(audio)

# --- テキスト描画 (フォント・サイズ・位置はこのTOPのパラメータでUI調整) ---
text = c.op("overlay_text") or c.create(textTOP, "overlay_text")
text.nodeX, text.nodeY = 450, 200
text.par.resolutionw = 1920
text.par.resolutionh = 1080
text.par.text = "ヘリGPS待機中"
for name, val in [
    ("fontsizex", 72),
    ("alignx", 1),        # center
    ("aligny", 0),        # bottom
    ("positiony", 60),    # 下から少し上げる(セーフエリア)
    ("fontcolorr", 1.0), ("fontcolorg", 1.0), ("fontcolorb", 1.0),
    ("fontalpha", 1.0),
    ("bgalpha", 0.0),     # 背景透明 → アルファがそのままKeyになる
]:
    try:
        setattr(text.par, name, val)
    except Exception as e:
        print(f"overlay_text.{name} 設定スキップ: {e}")
# 日本語フォント(入っているものを順に試す)
for f in ("Yu Gothic UI", "Yu Gothic", "BIZ UDPGothic", "Meiryo", "MS Gothic"):
    try:
        text.par.font = f
        if text.par.font.eval() == f:
            break
    except Exception:
        pass

# --- SDI出力 (Fill & Key) ---
out = c.op("sdi_out") or c.create(videodeviceoutTOP, "sdi_out")
out.nodeX, out.nodeY = 700, 200
out.inputConnectors[0].connect(text)
# 環境依存パラメータは候補名で設定を試み、失敗したら手動設定を案内
for names, val in [
    (("signalformat", "videoformat"), "1080i5994"),
    (("keyer", "keyermode", "keying"), "external"),
]:
    done = False
    for n in names:
        try:
            setattr(out.par, n, val)
            done = True
            break
        except Exception:
            pass
    if not done:
        print(f"sdi_out: {names} は手動で設定してください (値: {val})")

# --- toxファイルとして保存(以後はこのtoxをドラッグ&ドロップで再利用可能) ---
tox_path = os.path.join(HELI_GPS_LIB, "touchdesigner", "HELI_GPS.tox")
try:
    c.save(tox_path)
    print(f"toxを保存しました: {tox_path}")
except Exception as e:
    print(f"tox保存に失敗(手動で保存してください): {e}")

print("HELI_GPS ネットワークを構築しました。README_TD.md の手順で"
      "デバイス選択とキーヤー設定を行ってください。")
