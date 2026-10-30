@echo off
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
".venv\Scripts\python.exe" "main.py"
echo.
echo Launcher exited with code %ERRORLEVEL%
pause
