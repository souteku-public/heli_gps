@echo off
rem ============================================================
rem  ヘリGPSスーパー(GStreamer版) 見た目プレビュー 一括起動
rem    - GStreamerのPATHを自動設定
rem    - プレビュー(入力映像+テロップをPC窓に合成表示)を起動
rem    - 制御UI(control_ui.py)を起動
rem  ※SDI出力はしない(REF不要)。本番送出とは同時実行不可。
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem --- 設定 ----------------------------------------------------
set "CHANNEL=2"
set "INDEV=0"
set "VMODE=1080i5994"   rem 入力フォーマット(auto不可: compositorのため固定)
set "PW=960"
set "PH=540"
set "GST1=C:\Program Files\gstreamer\1.0\msvc_x86_64\bin"
set "GST2=C:\gstreamer\1.0\msvc_x86_64\bin"
rem -------------------------------------------------------------

call :setup_path || goto :err_gst
where python >nul 2>&1 || goto :err_py

echo プレビューを起動します(入力映像にテロップを重ねてPC窓に表示)...
start "HeliGPS Preview" cmd /k python -m gst_heli.preview ^
    --osc-control --channel %CHANNEL% --in-device %INDEV% --vmode %VMODE% ^
    --preview-width %PW% --preview-height %PH%

echo 制御UIを起動します...
where pythonw >nul 2>&1 && ( start "" pythonw control_ui.py ) || ( start "" python control_ui.py )

endlocal
exit /b 0

:setup_path
where gst-launch-1.0 >nul 2>&1 && exit /b 0
if exist "%GST1%\gst-launch-1.0.exe" ( set "PATH=%GST1%;%PATH%" & exit /b 0 )
if exist "%GST2%\gst-launch-1.0.exe" ( set "PATH=%GST2%;%PATH%" & exit /b 0 )
exit /b 1

:err_gst
echo [エラー] GStreamer(gst-launch-1.0)が見つかりません。
echo   Complete構成でインストールし、binのパスを GST1/GST2 に設定してください。
pause
exit /b 1

:err_py
echo [エラー] python が見つかりません。PythonをPATH付きでインストールしてください。
pause
exit /b 1
