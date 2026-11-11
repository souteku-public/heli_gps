@echo off
rem ============================================================
rem  Heli GPS super (GStreamer) - BURN-IN launcher
rem    - set GStreamer PATH automatically
rem    - start sender in BURN-IN mode
rem        (input video + audio  ->  super burned in  ->  1 SDI out)
rem    - start control UI (control_ui.py)
rem  No external keyer needed. Needs a full-duplex DeckLink and REF.
rem  For Fill/Key output instead, use start_heli_gst.bat.
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem --- settings (edit for your site) ---
set "CHANNEL=2"
set "MODE=1080i5994"
set "VMODE=1080i5994"
set "INDEV=0"
set "OUTDEV=0"
set "AVOFFSET=0"
rem COMPFORMAT = colour path used when compositing the super.
rem   auto  (default) keeps the input colour untouched: the pass-through
rem         picture comes out identical to what came in, super-white and
rem         all. Picks A422, or AYUV on older GStreamer.
rem   Change this only if asked to - an empty value lets GStreamer decide,
rem   which goes via RGB and clips white (235) and shifts colour.
set "COMPFORMAT=auto"
rem EXTRA: optional flags.
rem   By default the input stays 1080i - the picture is NOT touched.
rem   The super is marked interlaced so both compositor inputs match.
rem   --deinterlace
rem     Fallback only. Converts the input to progressive before
rem     compositing. Costs resolution on fast motion, so do not use it
rem     unless the default does not negotiate on your hardware.
set "EXTRA="
set "GST1=C:\Program Files\gstreamer\1.0\msvc_x86_64\bin"
set "GST2=C:\gstreamer\1.0\msvc_x86_64\bin"
rem -------------------------------------

call :setup_path || goto :err_gst
where python >nul 2>&1 || goto :err_py
python -c "import numpy, PIL" >nul 2>&1 || goto :err_deps

echo Starting sender (BURN-IN: input video+audio with super, single SDI out)...
start "HeliGPS Burn-in" cmd /k python -m gst_heli.app --source decklink --output decklink ^
    --output-mode burnin --osc-control --channel %CHANNEL% --mode %MODE% --vmode %VMODE% ^
    --in-device %INDEV% --out-device %OUTDEV% --av-offset-ms %AVOFFSET% ^
    --comp-format %COMPFORMAT% %EXTRA%

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
