@echo off
rem ヘリGPSスーパー 起動バッチ
rem   1) TouchDesigner で heli_telop.toe を開く
rem   2) Python制御UI(control_ui.py)を起動
rem
rem ★環境に合わせてパスを修正してください:
rem   - TDEXE : TouchDesigner本体のパス(バージョンでフォルダ名が変わります)
rem   - TOE   : プロジェクトファイル
rem   - LIB   : リポジトリの場所

set "TDEXE=C:\Program Files\Derivative\TouchDesigner\bin\TouchDesigner.exe"
set "TOE=C:\heli_gps\touchdesigner\heli_telop.toe"
set "LIB=C:\heli_gps"

start "" "%TDEXE%" "%TOE%"

rem 制御UIはリポジトリ直下で実行(nnn_decoderをimportするため)
cd /d "%LIB%"
start "" pythonw control_ui.py

exit
