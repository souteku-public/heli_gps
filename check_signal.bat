@echo off
rem ============================================================
rem  Heli GPS super - SIGNAL CHECK (no SDI output)
rem    Captures the SDI INPUT only and reports GPS reception.
rem    Use this when the preview works but the on-air launchers
rem    do not receive GPS: it tells you whether the problem is
rem    on the INPUT side or the OUTPUT side.
rem
rem    GPS received here  -> input is fine, the problem is the
rem                          SDI OUTPUT (REF, duplex, device busy)
rem    GPS NOT received   -> input side (channel, VMODE, cabling)
rem
rem  Safe to run: no SDI output, no REF needed.
rem  Keep the on-air launchers CLOSED while running this
rem  (one DeckLink input cannot be opened twice).
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem --- must match your on-air batch files ---
set "CHANNEL=2"
set "VMODE=1080i5994"
set "INDEV=0"
set "CHANNELS=8"
set "GST1=C:\Program Files\gstreamer\1.0\msvc_x86_64\bin"
set "GST2=C:\gstreamer\1.0\msvc_x86_64\bin"
rem ------------------------------------------

call :setup_path || goto :err_gst
where python >nul 2>&1 || goto :err_py
python -c "import numpy, PIL" >nul 2>&1 || goto :err_deps

echo.
echo  Checking GPS reception from the SDI input (no output).
echo  Close this window or press Ctrl+C to stop.
echo.
python -m gst_heli.app --source decklink --audio-only ^
    --channel %CHANNEL% --vmode %VMODE% --in-device %INDEV% ^
    --channels %CHANNELS%

echo.
pause
endlocal
exit /b 0

:setup_path
where gst-launch-1.0 >nul 2>&1 && exit /b 0
if exist "%GST1%\gst-launch-1.0.exe" ( set "PATH=%GST1%;%PATH%" & exit /b 0 )
if exist "%GST2%\gst-launch-1.0.exe" ( set "PATH=%GST2%;%PATH%" & exit /b 0 )
exit /b 1

:err_deps
echo.
echo [ERROR] Required Python packages are missing (numpy / Pillow).
echo         Run setup_check.bat once on this PC.
echo.
pause
exit /b 1

:err_gst
echo.
echo [ERROR] GStreamer (gst-launch-1.0) not found. Run setup_check.bat.
echo.
pause
exit /b 1

:err_py
echo.
echo [ERROR] python not found. Run setup_check.bat.
echo.
pause
exit /b 1
