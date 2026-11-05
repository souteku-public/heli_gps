@echo off
rem ============================================================
rem  Heli GPS super (GStreamer) - PREVIEW launcher
rem    - set GStreamer PATH automatically
rem    - start preview (input video + super in a PC window)
rem    - start control UI (control_ui.py)
rem  No SDI output (no REF needed). Cannot run at the same
rem  time as the on-air sender (single input device).
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem --- settings ---
set "CHANNEL=2"
set "INDEV=0"
set "VMODE=1080i5994"
rem PW/PH = preview window size in px. 0 = auto (about 1/9 of the screen).
set "PW=0"
set "PH=0"
set "GST1=C:\Program Files\gstreamer\1.0\msvc_x86_64\bin"
set "GST2=C:\gstreamer\1.0\msvc_x86_64\bin"
rem ----------------

call :setup_path || goto :err_gst
where python >nul 2>&1 || goto :err_py
python -c "import numpy, PIL" >nul 2>&1 || goto :err_deps

echo Starting preview (input video + super in a window)...
start "HeliGPS Preview" cmd /k python -m gst_heli.preview ^
    --osc-control --channel %CHANNEL% --in-device %INDEV% --vmode %VMODE% ^
    --preview-width %PW% --preview-height %PH%

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
echo.
echo [ERROR] GStreamer (gst-launch-1.0) not found.
echo.
echo   Install the Windows (MSVC 64-bit) Runtime AND Development
echo   installers from https://gstreamer.freedesktop.org/download/
echo   Choose "Complete" - "Typical" does NOT include decklink.
echo   If it is installed elsewhere, edit GST1/GST2 at the top of this file.
echo.
echo   Run  setup_check.bat  to see what is missing.
echo.
pause
exit /b 1

:err_deps
echo.
echo [ERROR] Required Python packages are missing (numpy / Pillow).
echo.
echo   Run this once on this PC:
echo.
echo       setup_check.bat
echo.
echo   (or:  python -m pip install -r requirements.txt )
echo.
pause
exit /b 1

:err_py
echo.
echo [ERROR] python not found.
echo.
echo   Install Python 3.10 or later from https://www.python.org/
echo   IMPORTANT: tick "Add python.exe to PATH" in the installer.
echo   Then run  setup_check.bat  once.
echo.
pause
exit /b 1
