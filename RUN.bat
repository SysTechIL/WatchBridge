@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import requests, plexapi, websocket" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" watchbridge.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo WatchBridge could not start. Install Python 3.10 or newer with Python Launcher.
echo Check the messages above. The first run needs Internet access for dependencies.
pause
exit /b 1
