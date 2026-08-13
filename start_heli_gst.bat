@echo off
rem ============================================================
rem  Heli GPS super (GStreamer) - ON-AIR launcher
rem    - set GStreamer PATH automatically
rem    - start sender (SDI in -> Fill/Key out)
rem    - start control UI (control_ui.py)
rem  Place in heli_gps folder (same level as control_ui.py).
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem --- settings (edit for your site) ---
set "CHANNEL=2"
set "MODE=1080i5994"
set "KEYER=external"
set "INDEV=0"
set "OUTDEV=0"
set "EXTRA="
set "GST1=C:\Program Files\gstreamer\1.0\msvc_x86_64\bin"
set "GST2=C:\gstreamer\1.0\msvc_x86_64\bin"
rem -------------------------------------

call :setup_path || goto :err_gst
where python >nul 2>&1 || goto :err_py

echo Starting sender (console shows logs)...
start "HeliGPS Sender" cmd /k python -m gst_heli.app --source decklink --output decklink ^
    --osc-control --channel %CHANNEL% --mode %MODE% --keyer %KEYER% ^
    --in-device %INDEV% --out-device %OUTDEV% %EXTRA%

echo Starting control UI...
where pythonw >nul 2>&1 && ( start "" pythonw control_ui.py ) || ( start "" python control_ui.py )

endlocal
exit /b 0

:setup_path
where gst-launch-1.0 >nul 2>&1 && exit /b 0
if exist "%GST1%\gst-launch-1.0.exe" ( set "PATH=%GST1%;%PATH%" & exit /b 0 )
if exist "%GST2%\gst-launch-1.0.exe" ( set "PATH=%GST2%;%PATH%" & exit /b 0 )
exit /b 1

:err_gst
echo [ERROR] GStreamer (gst-launch-1.0) not found. Install Complete and set GST1/GST2.
pause
exit /b 1

:err_py
echo [ERROR] python not found. Install Python and add it to PATH.
pause
exit /b 1
