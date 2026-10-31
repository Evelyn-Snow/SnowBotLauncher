# SnowBotLauncher

AstrBot + NapCat 的 Windows 桌面统一控制台，并内置可扩展的 **SnowBot 配置包** 系统：一键启停、状态监控、WebUI/Token 快捷入口、实时日志、后台挂起、开机自启、配置包导入与应用。

基于 PySide6（Qt）实现，打包后为独立 exe，无需安装 Python。

## 功能

### 服务控制
- **统一启停**：一键启动/停止 AstrBot 与 NapCat，显示 PID、运行时长
- **状态监控**：AstrBot 面板、OneBot 反向 WS（6199）、NapCat WebUI、QQ 账号、连接状态
- **快捷入口**：直接打开 AstrBot WebUI / NapCat WebUI，Token 显示与一键复制
- **实时日志**：AstrBot 与 NapCat 双标签页日志实时跟随
- **后台挂起**：关闭窗口或点「后台挂起」隐藏到系统托盘，服务不中断；托盘菜单可恢复、启停、退出
- **设置页**：路径、端口、关闭到托盘、启动最小化、开机自启（计划任务）、启动后自动拉起服务
- **健壮性**：单实例锁、自动提权（NapCat 需要管理员权限）

### 配置包（SnowBot Pack）
- **清单驱动**：`pack.json` 描述人格、插件、模型、语音、表情包等配置
- **变量自定义**：文本 / 密码 / 下拉 / 布尔 / 多行，支持默认值、校验、条件显示
- **计划预览**：先登录 AstrBot 读取当前状态，生成将要执行的步骤，确认后再应用
- **备份还原**：应用前自动快照全局配置、人格、插件配置、提供商；可一键还原
- **可重复执行**：已安装的插件、已存在的人格会跳过或更新，失败项可单独重跑
- **扩展性**：支持插件市场/随包插件、任意 `/api/v1` 请求、Python 脚本步骤（需显式授权）
- **旧版兼容**：识别 dafeiyu 风格的 `settings/pack.json + tools/import_*.py`，自动转换为脚本步骤

### 增强配置
- **人格**：读取/新建/编辑/删除人格，设为默认，直接导入 Markdown
- **表情包**：meme_manager 资源广场索引、按 pack_id 下载、默认套装、多套同时使用、GitHub 加速地址
- **语音**：Edge TTS / 小米 MiMo 克隆 / 豆包 Seed Audio，保存前自动测试，触发概率可调
- **记忆**：本机 Ollama / 硅基流动 / 自定义 OpenAI 兼容 Embedding，自动接入 LivingMemory 插件
- 以上操作直接调用 AstrBot 后台接口；密码只在本次运行内存中使用，不落盘

格式说明见 [docs/pack-schema.md](docs/pack-schema.md)。

## 项目结构

```text
main.py                      # 程序入口
snowbot/
├─ core/                     # 路径、配置、服务管理
│  ├─ paths.py
│  ├─ config.py
│  └─ services.py
├─ astrbot/client.py         # AstrBot WebUI API 客户端
├─ packs/engine.py           # SnowBot 配置包引擎
└─ ui/
   ├─ theme.py               # 主题与图标
   ├─ widgets.py             # 通用组件
   ├─ main_window.py         # 主窗口、托盘、全局状态
   └─ pages/                 # 控制台 / 配置包 / 增强配置 / 设置 / 说明
```

## 环境要求

- Windows 10/11 x64
- AstrBot（源码 + venv）与 NapCat Shell 已部署在本机
- 默认路径（可在设置页修改）：
  - AstrBot：`C:\Users\Administrator\AstrBot`
  - AstrBot Python：`C:\Users\Administrator\AstrBot\.venv\Scripts\python.exe`
  - NapCat：`C:\NapCat\NapCat.Shell`

## 数据目录

程序目录只放可执行文件；用户数据在：

```
%LOCALAPPDATA%\SnowBotLauncher\
├─ config.json       # 控制台设置
├─ logs\             # AstrBot / NapCat 控制台日志
├─ packs\            # 配置包
├─ presets\          # 变量预设（不含密码与密钥）
└─ backups\          # 应用配置包前的自动备份
```

安装版以管理员运行，配置和日志不写 Program Files，升级/卸载不会被文件锁影响。

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

1. PyInstaller 从 `main.py` 打包为 `dist\SnowBotLauncher\SnowBotLauncher.exe`（onedir，管理员清单，附带 examples/docs）
2. Inno Setup 编译出 `installer\output\SnowBotLauncher-Setup-1.3.4.exe`

需要 Inno Setup 6（`ISCC.exe`），默认查找 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`。

## 安装

运行生成好的安装包：

```
installer\output\SnowBotLauncher-Setup-1.3.4.exe
```

- 默认安装到 `C:\Program Files\SnowBotLauncher`，创建开始菜单与桌面快捷方式
- 安装与运行都需要管理员权限（NapCat 需要向 QQ 注入引导模块）
- 卸载：Windows 设置 → 应用，或开始菜单中的「卸载 SnowBotLauncher」；用户数据目录保留，可按需手动删除
- 安装包未做代码签名，首次运行可能出现 SmartScreen 提示，选择「更多信息 → 仍要运行」即可

## 配置包快速上手

1. 打开「配置包」页，内置示例包 `示例：人格配置包`；也可点「导入配置包…」选择文件夹或 zip。
2. 填写变量与 AstrBot 后台账号密码（默认 `astrbot / astrbot`）。
3. 点「预览计划」确认步骤；点「应用配置」执行，失败会保留备份。
4. 需要回退时点「还原备份…」选择对应快照。

## 说明

- 控制台需要管理员权限：NapCat 需要向 QQ 注入引导模块；安装包中的 exe 已内嵌 `requireAdministrator` 清单。
- 「停止 NapCat」会结束 QQ 进程（界面有确认提示）。
- AstrBot 的日志仅在其由本控制台启动时被捕获（`%LOCALAPPDATA%\SnowBotLauncher\logs\astrbot.log`）；NapCat 日志读取 `NapCat.Shell\logs\*.log`。
- 机器人要正常回复，需先在 AstrBot WebUI 中配置大模型服务商并设为默认。
- 配置包脚本步骤会执行代码，只导入可信来源。
