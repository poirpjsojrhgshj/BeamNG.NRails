@echo off
rem BeamNG.NRails Hub: install, start the server, start the game, settings. Double-click this file.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" hub.py
  exit /b 0
)
where pyw >nul 2>nul
if not errorlevel 1 (
  start "" pyw -3 hub.py
  exit /b 0
)
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw hub.py
  exit /b 0
)
echo Python 3.10+ is needed: https://www.python.org/downloads/ (tick "Add python.exe to PATH" and "tcl/tk").
pause
exit /b 1
