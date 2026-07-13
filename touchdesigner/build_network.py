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

DEVICE = "UltraStudio HD Mini"   # ★機種名の一部(部分一致で探すので正確でなくてよい)


def _try(obj, name, *values):
    """パラメータへ候補値を順に設定(存在しない/失敗はスキップ)."""
    for v in values:
        try:
            setattr(obj.par, name, v)
            return True
        except Exception:
            pass
    return False


def _pick_device(par, substr):
    """メニュー候補から substr を含む項目を選ぶ(デバイス名にマシン固有IDが
    付く場合があるため完全一致でなく部分一致で拾う)."""
    try:
        for name in par.menuNames:
            if substr in name:
                par.val = name
                return name
    except Exception:
        pass
    return None


# --- 音声入力 (Blackmagic 8ch。ドライバは小文字 'blackmagic') ---
audio = c.create(audiodeviceinCHOP, "audio_in")
audio.nodeX, audio.nodeY = 0, 200
_try(audio, "driver", "blackmagic", "Blackmagic")
if not _pick_device(audio.par.device, DEVICE):
    print(f"audio_in: '{DEVICE}' を含むデバイスが見つかりません。手動選択してください")
_try(audio, "active", False)   # 一旦Off/Onでストリーム再オープン
_try(audio, "active", True)
# Blackmagicドライバは埋め込み全chを自動供給(チャンネル数設定は不要)

# --- 映像入力 (音声を流すために必須。表示はしないが常時クックさせる) ---
video = c.create(videodeviceinTOP, "video_in")
video.nodeX, video.nodeY = 0, 380
_try(video, "library", "Blackmagic")
_pick_device(video.par.device, DEVICE)

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
_pick_device(out.par.device, DEVICE)
# Fill&Key: Output Pixel Format = 8-bit + 8-bit Key (Alpha)
#   → SDI OUT 1本目=Fill(カラー)、2本目=Key(アルファ)
if not _try(out, "signalformat", "f1920x1080i-59.94hz", "1080i5994", "1080i59.94"):
    print("sdi_out: signalformat は手動で 1080i 59.94 に設定してください")
if not _try(out, "outputpixelformat", "fixed8key8"):
    print("sdi_out: Output Pixel Format を手動で「8-bit + 8-bit Key」に設定してください")

# --- gps_decodeのカスタムパラメータを生成(Setup Parameters相当)し値も設定 ---
# Script CHOPはコールバックのonSetupParametersを実行させるとカスタムPが出る。
# ビルドによりpulse名が異なる/効かないことがあるため複数試す。
for pname in ("setuppars", "setupparameters"):
    try:
        getattr(dec.par, pname).pulse()
        break
    except Exception:
        pass

# カスタムパラメータの値を明示設定(Setup直後は既定が入らないことがあるため)。
# パラメータがまだ無い場合はrun遅延で後から入れる。
def _set_decode_pars():
    d = op(dec.path)
    vals = {
        "Baud": "1200",
        "Audiochan": 2,          # EMBのCH3(0始まりで2)
        "Texttop": "overlay_text",
        "Textformat": "{address}上空",
        "Staletext": "",
        "Staletimeout": 5,
        "Addrlevel": "muni",
        "Geomode": "offline",
    }
    ok = True
    for k, v in vals.items():
        try:
            setattr(d.par, k, v)
        except Exception:
            ok = False
    return ok


if not _set_decode_pars():
    # パラメータ未生成なら次フレームで再試行(Setup Parametersの反映待ち)
    run("op('" + dec.path + "').parent().op('_setpars_once').run()", delayFrames=5)
    tmp = c.create(textDAT, "_setpars_once")
    tmp.text = (
        "def run():\n"
        "    d = op('" + dec.path + "')\n"
        "    for k,v in {'Baud':'1200','Audiochan':2,'Texttop':'overlay_text',"
        "'Textformat':'{address}上空','Staletext':'','Staletimeout':5,"
        "'Addrlevel':'muni','Geomode':'offline'}.items():\n"
        "        try: setattr(d.par,k,v)\n"
        "        except: pass\n"
        "    op('" + dec.path + "').parent().op('_setpars_once').destroy()\n"
    )
    print("gps_decode: カスタムパラメータを遅延設定します(Setup Parameters反映待ち)")

# --- 矢印キーで位置調整 (Keyboard In DAT + コールバック) ---
kb_cb = c.create(textDAT, "nudge_keys_callbacks")
kb_cb.nodeX, kb_cb.nodeY = 450, 380
with open(os.path.join(HELI_GPS_LIB, "touchdesigner", "nudge_keys_callbacks.py"),
          encoding="utf-8") as f:
    kb_cb.text = f.read()
kb = c.create(keyboardinDAT, "nudge_keys")
kb.nodeX, kb.nodeY = 450, 300
_try(kb, "callbacks", "nudge_keys_callbacks")
# 矢印キーだけ拾う(他アプリのショートカットと干渉しにくいよう限定)
_try(kb, "keys", "up down left right")

# --- コントロールUI(Controlsページ)を構築 ---
# HELI_GPSコンテナに操作用カスタムパラメータを追加し、
# gps_decode/overlay_text をバインドする。
try:
    ui_path = os.path.join(HELI_GPS_LIB, "touchdesigner", "setup_ui.py")
    with open(ui_path, encoding="utf-8") as f:
        ui_src = f.read()
    # 末尾の自動実行(setup_ui())を外し、TDグローバルが解決する現在の
    # 名前空間へ関数を定義してから、当コンテナを引数に呼ぶ
    exec(ui_src.replace("\nsetup_ui()\n", "\n"), globals())
    setup_ui(c)
except Exception as e:
    print(f"コントロールUIの構築をスキップ(手動でsetup_ui.pyを実行してください): {e}")

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
