# QQ 机器人控制台

AstrBot + NapCat 的 Windows 桌面统一控制台：一键启停、状态监控、WebUI/Token 快捷入口、实时日志、后台挂起、开机自启。

基于 PySide6（Qt）实现，打包后为独立 exe，无需安装 Python。

## 功能

- **统一启停**：一键启动/停止 AstrBot 与 NapCat，显示 PID、运行时长
- **状态监控**：AstrBot 面板、OneBot 反向 WS（6199）、NapCat WebUI、QQ 账号、连接状态
- **快捷入口**：直接打开 AstrBot WebUI / NapCat WebUI，Token 显示与一键复制
- **实时日志**：AstrBot 与 NapCat 双标签页日志实时跟随
- **后台挂起**：关闭窗口或点「后台挂起」隐藏到系统托盘，服务不中断；托盘菜单可恢复、启停、退出
- **设置页**：路径、端口、关闭到托盘、启动最小化、开机自启（计划任务）、启动后自动拉起服务
- **健壮性**：单实例锁、自动提权（NapCat 需要管理员权限）

## 环境要求

- Windows 10/11 x64
- AstrBot（源码 + venv）与 NapCat Shell 已部署在本机
- 默认路径（可在设置页修改）：
  - AstrBot：`C:\Users\Administrator\AstrBot`
  - AstrBot Python：`C:\Users\Administrator\AstrBot\.venv\Scripts\python.exe`
  - NapCat：`C:\NapCat\NapCat.Shell`

## 开发运行

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## 打包

```bat
build.bat
```

构建流程：

1. PyInstaller 打包为 `dist\QQBotLauncher\QQBotLauncher.exe`（onedir，管理员清单）
2. Inno Setup 编译出 `installer\output\QQBotLauncher-Setup-1.0.0.exe`

需要 Inno Setup 6（`ISCC.exe`），默认查找 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`。

## 说明

- 控制台需要管理员权限：NapCat 需要向 QQ 注入引导模块；安装包中的 exe 已内嵌 `requireAdministrator` 清单。
- 「停止 NapCat」会结束 QQ 进程（界面有确认提示）。
- AstrBot 的日志仅在其由本控制台启动时被捕获（`logs/astrbot.log`）；NapCat 日志读取 `NapCat.Shell\logs\*.log`。
- 机器人要正常回复，需先在 AstrBot WebUI 中配置大模型服务商并设为默认。
