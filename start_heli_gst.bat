@echo off
rem ヘリGPSスーパー(GStreamer版) 一括起動バッチ
rem   1) 送出本体 gst_heli.app (SDI入力→Fill&Key出力) をコンソール付きで起動
rem   2) 制御UI control_ui.py を起動
rem
rem このbatは heli_gps 直下に置く前提(control_ui.py と同じ階層)。
rem 設定は下の変数を環境に合わせて調整してください。

setlocal
cd /d "%~dp0"

rem --- 設定 ---------------------------------------------------------------
set "CHANNEL=2"            rem GPS音声チャンネル(0始まり。EMBのCH3なら2)
set "MODE=1080i5994"       rem SDI信号フォーマット
set "KEYER=external"       rem external=Fill&Key / internal / off
set "INDEV=0"              rem 入力DeckLinkデバイス番号
set "OUTDEV=0"             rem 出力DeckLinkデバイス番号

rem GStreamerのbinがPATHに無い場合はここで指定(MSIの既定パス例)。
rem 既にPATHが通っていれば下2行は不要(remのままでOK)。
rem set "GST_BIN=C:\gstreamer\1.0\msvc_x86_64\bin"
rem set "PATH=%GST_BIN%;%PATH%"
rem -----------------------------------------------------------------------

rem 送出本体(コンソールを残す。異常時に原因が見えるよう /k)。
rem 本番で窓を出したくない場合は cmd /k を cmd /c に変える。
start "HeliGPS Sender" cmd /k python -m gst_heli.app ^
    --source decklink --output decklink --osc-control ^
    --channel %CHANNEL% --mode %MODE% --keyer %KEYER% ^
    --in-device %INDEV% --out-device %OUTDEV%

rem 制御UI(pythonw があればコンソールなしで、無ければ python で)
where pythonw >nul 2>&1 && ( start "" pythonw control_ui.py ) || ( start "" python control_ui.py )

endlocal
exit /b 0
