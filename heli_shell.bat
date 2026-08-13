@echo off
rem ============================================================
rem  Heli GPS work shell
rem    - cd to repo root
rem    - add GStreamer bin to PATH automatically
rem    - keep the prompt open for manual commands
rem  Place this in the heli_gps folder and double-click.
rem ============================================================
setlocal
cd /d "%~dp0"

set "GST1=C:\Program Files\gstreamer\1.0\msvc_x86_64\bin"
set "GST2=C:\gstreamer\1.0\msvc_x86_64\bin"
where gst-launch-1.0 >nul 2>&1 || (
    if exist "%GST1%\gst-launch-1.0.exe" ( set "PATH=%GST1%;%PATH%"
    ) else if exist "%GST2%\gst-launch-1.0.exe" ( set "PATH=%GST2%;%PATH%"
    ) else ( echo [WARN] GStreamer not found. Install the Complete package. )
)

echo(
echo ============================================================
echo  Heli GPS work shell   (cwd: %CD%)
echo ------------------------------------------------------------
echo  Common commands:
echo    Preview (check look):
echo      python -m gst_heli.preview --osc-control --channel 2 --vmode 1080i5994
echo    On-air (Fill/Key):
echo      python -m gst_heli.app --source decklink --output decklink --osc-control --channel 2
echo    Control UI:
echo      python control_ui.py
echo    Output test:
echo      python -m gst_heli.outtest --text "TEST"
echo    Devices / version:
echo      gst-device-monitor-1.0
echo      gst-launch-1.0 --version
echo ------------------------------------------------------------
echo  Type commands here. Type  exit  to close.
echo ============================================================
echo(

cmd /k
endlocal
