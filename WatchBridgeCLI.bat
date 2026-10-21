@echo off
rem WatchBridge command line from the source package. Example: WatchBridgeCLI scan
setlocal
set "HERE=%~dp0"
if not exist "%HERE%.venv\Scripts\python.exe" (
  py -3 -m venv "%HERE%.venv"
  if errorlevel 1 goto failed
)
"%HERE%.venv\Scripts\python.exe" -c "import requests, plexapi, websocket" >nul 2>&1
if errorlevel 1 (
  "%HERE%.venv\Scripts\python.exe" -m pip install -r "%HERE%requirements.txt" >&2
  if errorlevel 1 goto failed
)
"%HERE%.venv\Scripts\python.exe" "%HERE%cli.py" %*
exit /b %errorlevel%
:failed
echo WatchBridge could not install its dependencies. Install Python 3.10 or newer with Python Launcher. >&2
exit /b 1
