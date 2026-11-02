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
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --uac-admin --name SnowBotLauncher --icon app.ico --add-data "examples;examples" --add-data "docs;docs" main.py
if errorlevel 1 goto :err

echo [3/4] 检查 Inno Setup...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo 未找到 ISCC.exe，请先安装 Inno Setup 6：https://jrsoftware.org/isdl.php
    goto :err
)

echo [4/4] 生成安装包...
"%ISCC%" "installer\SnowBotLauncher.iss"
if errorlevel 1 goto :err

echo.
echo 构建完成：
echo   exe:     dist\SnowBotLauncher\SnowBotLauncher.exe
echo   setup:   installer\output\SnowBotLauncher-Setup-1.5.22.exe
pause
exit /b 0

:err
echo.
echo 构建失败，请查看上方错误信息。
pause
exit /b 1
