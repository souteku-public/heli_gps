# TouchDesigner ネットワーク自動構築スクリプト
#
# TDのTextport(Alt+T)で次の1行を実行するとネットワーク一式を自動生成する:
#   exec(open(r"C:\heli_gps\touchdesigner\build_network.py", encoding="utf-8").read())
#
# 生成物 (/project1/HELI_GPS):
#   audio_in   (Audio Device In CHOP)  … UltraStudioのEMB音声(Blackmagic,8ch)
#   video_in   (Video Device In TOP)   … ★Blackmagic音声を流すために必須
#   gps_decode (Script CHOP)           … GPS復調+住所変換
#   overlay_text (Text TOP 1920x1080)  … 表示文字
#   sdi_out    (Video Device Out TOP)  … 1080i Fill&Key出力
#   force_cook (Execute DAT)           … 毎フレーム強制クック(遅延評価対策)
#
# 既存の HELI_GPS があれば作り直すため一旦削除する(重複防止)。
# デバイス選択やREF入力など環境依存の最終確認は README_TD.md を参照。

import os

HELI_GPS_LIB = r"C:\heli_gps"   # ★リポジトリの場所に合わせて変更

# --- 既存のHELI_GPSを全て削除(重複防止) ---
for path in ("/project1/HELI_GPS", "/HELI_GPS"):
    old = op(path)
    if old is not None:
        old.destroy()

root = op("/project1")
if root is None:
    root = op("/").create(baseCOMP, "project1")

c = root.create(containerCOMP, "HELI_GPS")

DEVICE = "UltraStudio HD Mini"   # ★機種名。デバイス欄のプルダウン表記に合わせる


def _try(obj, name, *values):
    """パラメータへ候補値を順に設定(存在しない/失敗はスキップ)."""
    for v in values:
        try:
            setattr(obj.par, name, v)
            return True
        except Exception:
            pass
    return False


# --- 音声入力 (Blackmagic 8ch) ---
audio = c.create(audiodeviceinCHOP, "audio_in")
audio.nodeX, audio.nodeY = 0, 200
_try(audio, "driver", "Blackmagic")
_try(audio, "device", DEVICE)
_try(audio, "numchannels", 8)
_try(audio, "active", True)

# --- 映像入力 (音声を流すために必須。表示はしないが常時クックさせる) ---
video = c.create(videodeviceinTOP, "video_in")
video.nodeX, video.nodeY = 0, 380
_try(video, "library", "Blackmagic")
_try(video, "device", DEVICE)

# --- 復調Script CHOP + コールバック ---
cb = c.create(textDAT, "gps_decode_callbacks")
cb.nodeX, cb.nodeY = 200, 350
cb_path = os.path.join(HELI_GPS_LIB, "touchdesigner", "gps_decode_callbacks.py")
with open(cb_path, encoding="utf-8") as f:
    cb.text = f.read()

dec = c.create(scriptCHOP, "gps_decode")
dec.nodeX, dec.nodeY = 200, 200
dec.par.callbacks = "gps_decode_callbacks"
dec.inputConnectors[0].connect(audio)

# TDのノードは参照されないと評価されない(遅延クック)ため、
# gps_decodeとvideo_inを毎フレーム強制クックする。
# force=True必須(参照されないチェーンはdirty判定でも空振りするため)。
fc = c.create(executeDAT, "force_cook")
fc.nodeX, fc.nodeY = 200, 50
fc.par.framestart = True
fc.text = (
    "def onFrameStart(frame):\n"
    "    op('video_in').cook(force=True)   # SDIストリーム保持→音声供給\n"
    "    op('gps_decode').cook(force=True)  # 復調+テキスト更新\n"
    "    return\n"
)

# --- テキスト描画 (フォント・サイズ・位置はこのTOPのパラメータでUI調整) ---
text = c.create(textTOP, "overlay_text")
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
    _try(text, name, val)
# 日本語フォント(入っているものを順に試す)
for f in ("Yu Gothic UI", "Yu Gothic", "BIZ UDPGothic", "Meiryo", "MS Gothic"):
    try:
        text.par.font = f
        if text.par.font.eval() == f:
            break
    except Exception:
        pass

# --- SDI出力 (Fill & Key) ---
out = c.create(videodeviceoutTOP, "sdi_out")
out.nodeX, out.nodeY = 700, 200
out.inputConnectors[0].connect(text)
_try(out, "library", "Blackmagic")
_try(out, "device", DEVICE)
# Fill&Key: Output Pixel Format = 8-bit + 8-bit Key (Alpha)
#   → SDI OUT 1本目=Fill(カラー)、2本目=Key(アルファ)
if not _try(out, "signalformat", "1080i5994", "1080i59.94", "1080i2997"):
    print("sdi_out: signalformat は手動で 1080i 59.94 に設定してください")
if not _try(out, "outputpixelformat", "fixed8key8"):
    print("sdi_out: Output Pixel Format を手動で「8-bit + 8-bit Key」に設定してください")

# --- gps_decodeのカスタムパラメータを生成(Setup Parameters相当) ---
# Script CHOPはコールバックのonSetupParametersを実行させるとカスタムPが出る
try:
    dec.par.setuppars.pulse()   # ビルドにより名称差異あり
except Exception:
    print("gps_decode: パラメータ画面のScriptタブで Setup Parameters を1回押してください")

# GPS音声チャンネル既定(0始まり。EMBのCH3ならindex=2)
try:
    dec.par.Audiochan = 2
except Exception:
    pass

# --- toxとして保存(以後はこのtoxをドラッグ&ドロップで再利用可能) ---
tox_path = os.path.join(HELI_GPS_LIB, "touchdesigner", "HELI_GPS.tox")
try:
    c.save(tox_path)
    print(f"toxを保存しました: {tox_path}")
except Exception as e:
    print(f"tox保存に失敗(手動で File > Save Component してください): {e}")

print("=== HELI_GPS 構築完了 ===")
print("次の確認: gps_decodeのHeli GPSタブで音声チャンネル、sdi_outでREF入力とKey設定。")
print("詳細は README_TD.md を参照。")
