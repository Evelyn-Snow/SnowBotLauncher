@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] 创建虚拟环境...
    python -m venv .venv
)

echo [1/4] 安装依赖...
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :err

echo [2/4] PyInstaller 打包 exe...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --uac-admin --name QQBotLauncher --icon app.ico app.py
if errorlevel 1 goto :err

echo [3/4] 检查 Inno Setup...
del /q "dist\QQBotLauncher\launcher_config.json" 2>nul
del /q "dist\QQBotLauncher\launcher.lock" 2>nul
rmdir /s /q "dist\QQBotLauncher\logs" 2>nul
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo 未找到 ISCC.exe，请先安装 Inno Setup 6：https://jrsoftware.org/isdl.php
    goto :err
)

echo [4/4] 生成安装包...
"%ISCC%" "installer\QQBotLauncher.iss"
if errorlevel 1 goto :err

echo.
echo 构建完成：
echo   exe:     dist\QQBotLauncher\QQBotLauncher.exe
echo   setup:   installer\output\QQBotLauncher-Setup-1.0.0.exe
pause
exit /b 0

:err
echo.
echo 构建失败，请查看上方错误信息。
pause
exit /b 1
