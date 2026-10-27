@echo off
setlocal EnableExtensions

set PYTHONUTF8=1

cd /d "G:\vibe coding\mc-launcher" || goto :error

if not defined PYTHON set "PYTHON=python"

set "APP=G:\vibe coding\mc-launcher\mclauncher\mcl-gui.py"
set "ICON=G:\vibe coding\mc-launcher\mclauncher\gui\assets\app.ico"
set "DATA=G:\vibe coding\mc-launcher\mclauncher=mclauncher"

set "PLUGIN=--enable-plugin=pyside6"

set "JOBS=%NUMBER_OF_PROCESSORS%"
if not defined JOBS set "JOBS=4"

"%PYTHON%" -m nuitka ^
  --low-memory ^
  --mingw64 ^
  %PLUGIN% ^
  --standalone ^
  --onefile ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico="%ICON%" ^
  --include-package-data=qfluentwidgets ^
  --include-data-dir="%DATA%" ^
  --noinclude-qt-plugins=qtwebengine,qtwebenginecore,qtwebenginewidgets,qtwebenginequick ^
  --nofollow-import-to=PySide6.QtWebEngine,PySide6.QtWebEngineCore,PySide6.QtWebEngineWidgets,PySide6.QtWebEngineQuick ^
  --output-dir=dist ^
  --lto=yes ^
  --jobs=%JOBS% ^
  --remove-output ^
  "%APP%"

if errorlevel 1 goto :error

echo Build OK. Output: dist\
goto :eof

:error
echo Build failed.
exit /b 1