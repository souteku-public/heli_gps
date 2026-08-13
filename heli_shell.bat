@echo off
rem ============================================================
rem  ヘリGPS 作業用シェル
rem    - リポジトリ直下へ移動
rem    - GStreamer の PATH を自動設定
rem    - そのままコマンド入力を受け付ける(開いたまま)
rem  heli_gps 直下に置いてダブルクリック。
rem ============================================================
setlocal
cd /d "%~dp0"

rem GStreamer bin の候補(先に見つかった方をPATHへ)
set "GST1=C:\Program Files\gstreamer\1.0\msvc_x86_64\bin"
set "GST2=C:\gstreamer\1.0\msvc_x86_64\bin"
where gst-launch-1.0 >nul 2>&1 || (
    if exist "%GST1%\gst-launch-1.0.exe" ( set "PATH=%GST1%;%PATH%"
    ) else if exist "%GST2%\gst-launch-1.0.exe" ( set "PATH=%GST2%;%PATH%"
    ) else ( echo [警告] GStreamer が見つかりません。Complete構成で入れてください。 )
)

echo(
echo ============================================================
echo  ヘリGPS 作業用シェル  (作業ディレクトリ: %CD%)
echo ------------------------------------------------------------
echo  よく使うコマンド:
echo    プレビュー(見た目確認):
echo      python -m gst_heli.preview --osc-control --channel 2 --vmode 1080i5994
echo    本番送出(Fill^&Key):
echo      python -m gst_heli.app --source decklink --output decklink --osc-control --channel 2
echo    制御UI:
echo      python control_ui.py
echo    出力テスト:
echo      python -m gst_heli.outtest --text "テスト 千葉県君津市上空"
echo    デバイス確認 / バージョン:
echo      gst-device-monitor-1.0
echo      gst-launch-1.0 --version
echo ------------------------------------------------------------
echo  この画面にそのままコマンドを入力できます。閉じるには exit
echo ============================================================
echo(

rem PATH等を引き継いだまま対話シェルを継続(開いたまま)
cmd /k
endlocal
