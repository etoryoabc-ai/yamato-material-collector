@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys, tkinter; assert sys.version_info >= (3,10)" >nul 2>nul
  if not errorlevel 1 (
    py -3 launcher.py %*
    goto finished
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys, tkinter; assert sys.version_info >= (3,10)" >nul 2>nul
  if not errorlevel 1 (
    python launcher.py %*
    goto finished
  )
)
echo Python 3.10以降と tkinter が必要です。
echo https://www.python.org/downloads/windows/ からインストールしてください。
echo インストーラーで Add python.exe to PATH と Tcl/Tk を有効にしてください。
pause
exit /b 1
:finished
if errorlevel 1 (
  echo 起動または実行でエラーが発生しました。logs フォルダをご確認ください。
  pause
  exit /b 1
)
endlocal
