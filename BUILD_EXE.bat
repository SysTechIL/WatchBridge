@echo off
setlocal
cd /d "%~dp0"
echo Building WatchBridge for Windows. Personal settings and reports are not bundled.
if not exist ".build-venv\Scripts\python.exe" (
  py -3 -m venv .build-venv
  if errorlevel 1 goto failed
)
".build-venv\Scripts\python.exe" -m pip install -r requirements.txt "pyinstaller>=6.10,<7"
if errorlevel 1 goto failed
rem Window app; also runs scheduled and real-time background work without a console window.
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name WatchBridge --icon "assets\watchbridge.ico" --add-data "assets;assets" --collect-all plexapi --hidden-import websocket watchbridge.py
if errorlevel 1 goto failed
rem Command line for terminals and scripts; it starts WatchBridge.exe for the window.
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --console --name WatchBridgeCLI --icon "assets\watchbridge.ico" --collect-all plexapi --hidden-import websocket --exclude-module tkinter --exclude-module watchbridge cli.py
if errorlevel 1 goto failed
copy /y README_USER.txt dist\README_USER.txt >nul
powershell.exe -NoProfile -Command "Compress-Archive -Path 'dist\WatchBridge.exe','dist\WatchBridgeCLI.exe','dist\README_USER.txt' -DestinationPath 'dist\WatchBridge-Windows.zip' -Force"
if errorlevel 1 goto failed
echo.
echo READY: dist\WatchBridge-Windows.zip
echo Share this ZIP. Recipients do not need Python.
pause
exit /b 0
:failed
echo.
echo Build failed. Review the error above. Build on Windows using Python 3.10 or newer.
pause
exit /b 1
