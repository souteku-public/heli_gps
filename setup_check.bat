@echo off
rem ============================================================
rem  Heli GPS super - SETUP CHECK / INSTALL
rem    1) check Python
rem    2) install required packages (numpy, Pillow)
rem    3) run check_setup.py and show what is still missing
rem  Run this FIRST on a new PC.
rem ============================================================
setlocal
cd /d "%~dp0"
chcp 932 >nul 2>&1

echo ============================================================
echo   Heli GPS super - setup check
echo ============================================================
echo.

where python >nul 2>&1 || goto :err_py

echo [1/2] Installing required packages (numpy, Pillow)...
echo       command: python -m pip install -r requirements.txt
echo.
python -m pip install -r requirements.txt
if errorlevel 1 goto :err_pip
echo.

echo [2/2] Checking setup...
echo.
python check_setup.py
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo ------------------------------------------------------------
  echo   All good. Next: double-click start_heli_preview.bat
  echo ------------------------------------------------------------
) else (
  echo ------------------------------------------------------------
  echo   Some items are missing. See the list above.
  echo ------------------------------------------------------------
)
echo.
pause
endlocal
exit /b 0

:err_py
echo [ERROR] python not found.
echo.
echo   Install Python 3.10 or later from https://www.python.org/
echo   IMPORTANT: tick "Add python.exe to PATH" in the installer.
echo   Then run this file again.
echo.
pause
exit /b 1

:err_pip
echo.
echo [ERROR] pip install failed.
echo.
echo   - If this PC has no internet access, copy the wheel files in
echo     and run:  python -m pip install --no-index --find-links . numpy Pillow
echo   - If your site uses a proxy, set it first:
echo       set HTTPS_PROXY=http://proxy.example.co.jp:8080
echo     then run this file again.
echo.
pause
exit /b 1
