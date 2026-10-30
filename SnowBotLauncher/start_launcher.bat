@echo off
setlocal
net session >nul 2>&1
if %errorlevel%==0 goto :run
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b
:run
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "main.py"
