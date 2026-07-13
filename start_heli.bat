@echo off
rem ヘリGPSスーパー 起動バッチ
rem   1) heli_telop.toe を TouchDesigner で開く(ファイル関連付けで起動)
rem   2) Python制御UI(control_ui.py)を起動
rem
rem このbatは heli_gps 直下に置く前提。パスはbat自身の場所から自動算出するので
rem 置き場所を変えても編集不要(.toe名を変えた場合のみ下記TOENAMEを修正)。

setlocal
set "LIB=%~dp0"
set "TOENAME=heli_telop.toe"
set "TOE=%LIB%touchdesigner\%TOENAME%"

if not exist "%TOE%" (
    echo [エラー] プロジェクトファイルが見つかりません:
    echo    %TOE%
    echo touchdesigner フォルダ内の .toe 名を確認し、必要なら TOENAME を修正してください。
    pause
    exit /b 1
)

rem .toe を関連付けで開く(TDのバージョン/インストール先に依存しない)
start "" "%TOE%"

rem 制御UIはリポジトリ直下で実行(nnn_decoder を import するため)
cd /d "%LIB%"
rem pythonw があればコンソールなしで1つだけ起動、無ければ python で起動(排他)
where pythonw >nul 2>&1 && ( start "" pythonw control_ui.py ) || ( start "" python control_ui.py )

endlocal
exit /b 0
