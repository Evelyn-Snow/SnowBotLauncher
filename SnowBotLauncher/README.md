# SnowBotLauncher

AstrBot + NapCat 的 Windows 桌面统一控制台，并内置可扩展的 **SnowBot 配置包** 系统：一键启停、状态监控、WebUI/Token 快捷入口、实时日志、后台挂起、开机自启、配置包导入与应用。

基于 PySide6（Qt）实现，打包后为独立 exe，无需安装 Python。**还没装过 AstrBot / NapCat 的新用户，请先看下方[前置准备](#前置准备astrbot-与-napcat)。**

## 功能

### 服务控制
- **统一启停**：一键启动/停止 AstrBot 与 NapCat，显示 PID、运行时长
- **状态监控**：AstrBot 面板、OneBot 反向 WS（6199）、NapCat WebUI、QQ 账号、连接状态
- **快捷入口**：直接打开 AstrBot WebUI / NapCat WebUI，Token 显示与一键复制
- **实时日志**：AstrBot 与 NapCat 双标签页日志实时跟随
- **后台挂起**：关闭窗口或点「后台挂起」隐藏到系统托盘，服务不中断；托盘菜单可恢复、启停、退出
- **设置页**：自动检测官方启动器实例、路径、端口、关闭到托盘、启动最小化、开机自启（计划任务）、启动后自动拉起服务
- **NapCat 快速登录**：启动时自动读取已保存的 QQ 账号并传入 `-q`，避免每次重新扫码
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
- **人格**：读取/新建/编辑/删除人格，设为默认；支持导入 `.md`、用系统编辑器打开、重新加载、另存为，并用 `{OWNER_QQ}` / `{OWNER_NAME}` / `{BOT_NAME}` 占位符自动填入所有者/机器人信息
- **所有者识别**：保存人格时可同步 AstrBot 管理员、主动聊天会话和自动签名会话
- **表情包**：meme_manager 资源广场索引、按 pack_id 下载、默认套装、多套同时使用、GitHub 加速地址
- **语音**：Edge TTS / 小米 MiMo 克隆 / 豆包 Seed Audio，保存前自动测试，触发概率可调
- **记忆**：本机 Ollama / 硅基流动 / 自定义 OpenAI 兼容 Embedding，自动接入 LivingMemory 插件
- **视觉**：导入/配置 OpenAI 兼容视觉模型（GLM-4V、Qwen-VL、SiliconFlow、Ollama）；默认让视觉模型直接参与带图片的整轮对话，结合人格与最近聊天理解画面，也可切换为只生成图片描述交给主模型；可勾选是否在图片轮次保留存图/记忆/笔记等工具调用；支持 JSON 导入和本机 Ollama 视觉模型检测
- **图库**：把聊天里收藏的图片/表情包存到可自定义的本地目录，之后按情绪、场景或描述再发出来；模型可自行判断是否值得收藏并打标签，默认两次自动收藏至少间隔 45 分钟、每天最多 8 张，也可随时手动要求保存；默认最多 300 张、保留 180 天，按使用次数和最后使用时间自动清理低频与远古图片，清理记录写入 `cleanup.log`
- **Obsidian 笔记/日记**：写入本机 Obsidian 仓库的 Markdown，支持按天日记、主题笔记、搜索和读取；自动日记覆盖所有者私聊、群聊和其他私聊，按所有者私聊 3 / 群聊 2 / 其他私聊 1 的权重侧重，默认 2 小时间隔、每天最多 3 条、每条最多 120 字、0–7 点静默；LivingMemory 继续负责语义记忆
- **存储路径**：在「增强配置 → 存储」统一修改记忆文件（Obsidian）和图片图库目录；语义记忆数据库由 LivingMemory 管理，可一键打开定位
- **群聊**：在「增强配置 → 群聊」集中管理读空气开关与生效群白名单、接话/连聊概率、戳一戳与反戳概率、@空消息回询、群聊记忆捕获；保存后自动重载插件
- **联网搜索**：在「增强配置 → 搜索」启用 AstrBot 内置搜索工具并配置搜索源（DeepSeek 搜索可复用聊天同款 Key）；明确说「搜索 / 查一下」必定联网并附来源，平时自发搜索保持低频（默认 30 分钟间隔、每天 5 次），并先表明不太清楚再引用网上内容
- 以上操作直接调用 AstrBot 后台接口；密码只在本次运行内存中使用，不落盘

### 本机扩展插件

以下插件源码在 `plugins/`，**随启动器安装包分发**，可在「增强配置 → 扩展插件」一键安装（优先从插件市场拉取，失败自动改用内置版本）；也已作为独立仓库发布到 AstrBot 插件市场，可直接在 AstrBot 插件市场搜索安装：

| 插件 | 作用 | 仓库 |
|---|---|---|
| `snow_sleep` | 小雪作息：默认 00:00–07:00 休息，不回复、不被动读群消息 | [astrbot_plugin_snow_sleep](https://github.com/Evelyn-Snow/astrbot_plugin_snow_sleep) |
| `snow_continuity` | 连续对话接话：互动后“你……”和图片确定性回复，不受读空气概率影响 | [astrbot_plugin_snow_continuity](https://github.com/Evelyn-Snow/astrbot_plugin_snow_continuity) |
| `search_manners` | 搜索礼仪：明确要求必搜并附来源，自发搜索限频 | [astrbot_plugin_search_manners](https://github.com/Evelyn-Snow/astrbot_plugin_search_manners) |
| `share_card` | 分享卡片转文字：QQ 的 B站/网页 Json 卡片变成模型可见文本 | [astrbot_plugin_share_card](https://github.com/Evelyn-Snow/astrbot_plugin_share_card) |
| `bili_vision` | B站视频画面理解：缩略图抽帧 + 视觉模型，不下载完整视频 | [astrbot_plugin_bili_vision](https://github.com/Evelyn-Snow/astrbot_plugin_bili_vision) |
| `snow_imagebox` | 图库：存图/表情包、打标签、按需发送、自动清理 | [astrbot_plugin_snow_imagebox](https://github.com/Evelyn-Snow/astrbot_plugin_snow_imagebox) |
| `obsidian_notes` | 日记/笔记：写入 Obsidian，支持会话作用域与自动日记 | [astrbot_plugin_obsidian_notes](https://github.com/Evelyn-Snow/astrbot_plugin_obsidian_notes) |
| `star_citizen` | 星际公民数据：飞船参数、商品价格、终端行情 | [astrbot_plugin_star_citizen](https://github.com/Evelyn-Snow/astrbot_plugin_star_citizen) |
| `snow_experience` | 真实经历：自主读公版书/查资料/读论文（每周限次），经历注入聊天与日记 | [astrbot_plugin_snow_experience](https://github.com/Evelyn-Snow/astrbot_plugin_snow_experience) |
| `snow_knowledge` | 知识库：把真实读过的书/资料/论文切片向量化，聊天时按话题检索引用 | [astrbot_plugin_snow_knowledge](https://github.com/Evelyn-Snow/astrbot_plugin_snow_knowledge) |
| `snow_guard` | 安全守卫：出网白名单、内网/元数据/短链拦截、外部内容注入防护 | [astrbot_plugin_snow_guard](https://github.com/Evelyn-Snow/astrbot_plugin_snow_guard) |
| `snow_balance` | 余额感知：对话/语音/视觉额度不足时用自己的口吻私聊主人（饿了/嗓子哑了/看不清） | [astrbot_plugin_snow_balance](https://github.com/Evelyn-Snow/astrbot_plugin_snow_balance) |
| `snow_friend` | 好友申请：等级够高/有会员/老号才自动通过，其余挂起并通知主人 | [astrbot_plugin_snow_friend](https://github.com/Evelyn-Snow/astrbot_plugin_snow_friend) |

插件发布流程见 [docs/publishing.md](docs/publishing.md)；配置包格式说明见 [docs/pack-schema.md](docs/pack-schema.md)。

## 项目结构

```text
main.py                      # 程序入口
snowbot/
├─ core/                     # 路径、配置、服务管理、人格文件、视觉配置
│  ├─ paths.py
│  ├─ config.py
│  ├─ services.py
│  ├─ persona_files.py
│  └─ vision_config.py
├─ astrbot/client.py         # AstrBot WebUI API 客户端
├─ packs/engine.py           # SnowBot 配置包引擎
└─ ui/
   ├─ theme.py               # 主题与图标
   ├─ widgets.py             # 通用组件
   ├─ main_window.py         # 主窗口、托盘、全局状态
   └─ pages/
      ├─ console.py          # 控制台
      ├─ packs.py            # 配置包
      ├─ enhance/            # 增强配置（人格/表情包/语音/记忆/视觉/存储）
      │  ├─ common.py        # 共享常量与 Qt 导入
      │  ├─ tab.py           # 页面外壳与连接
      │  ├─ persona.py
      │  ├─ meme.py
      │  ├─ voice.py
      │  ├─ memory.py
      │  ├─ vision.py
      │  └─ storage.py
      ├─ settings.py
      └─ about.py
plugins/                     # 可选的本机 AstrBot 插件源码
├─ astrbot_plugin_obsidian_notes/
└─ astrbot_plugin_snow_imagebox/
tests/                       # 不依赖运行中服务的回归测试
scripts/                     # 开发辅助脚本
```

## 前置准备（AstrBot 与 NapCat）

**SnowBotLauncher 只是统一控制台，不负责下载安装 AstrBot 和 NapCat 本体。** 首次使用请按下面四步把环境装好、打通一次，之后日常启停都可以在启动器里完成。

### 你需要准备

| 组件 | 作用 | 获取 |
|---|---|---|
| QQ NT 桌面版 | NapCat 依赖 QQ 本体运行 | [QQ 官网](https://im.qq.com/pcqq/index.shtml) |
| AstrBot | 机器人核心：接入大模型、插件、WebUI | [文档](https://docs.astrbot.app/) · [GitHub](https://github.com/AstrBotDevs/AstrBot) |
| NapCat | QQ 协议端：把 QQ 消息接入 AstrBot | [文档](https://napneko.github.io/) · [GitHub](https://github.com/NapNeko/NapCatQQ) |

> 建议：QQ 登录后关闭「自动更新」，QQ 大版本升级可能导致 NapCat 短暂不适配；用小号跑机器人，降低风控影响。

> 系统要求：Windows 10/11 x64；NapCat 版本需与 QQ 版本匹配（QQ 升级后及时更新 NapCat）。

### 第 1 步 · 安装 AstrBot

推荐用官方启动器（与本项目自动检测的目录结构一致）：

1. 打开 [AstrBot 文档](https://docs.astrbot.app/) 的安装页，下载 **AstrBot Launcher**（Windows 版）。
2. 用启动器安装一个实例，默认装在 `%USERPROFILE%\.astrbot_launcher\instances\<id>\`，记住面板端口（默认 `6185`）。
3. 装好后无需在启动器里手动填路径——SnowBotLauncher 会自动检测最新实例（`core` 目录 + 实例内 `venv\Scripts\python.exe`）。

也可以源码方式部署：`git clone` AstrBot 后自建 venv 装依赖；这种目录可在启动器「设置」页手动选择，或点「自动检测官方启动器实例」。

### 第 2 步 · 安装 NapCat

1. 先安装并登录一次 QQ NT 桌面版。
2. 按 [NapCat 安装文档](https://napneko.github.io/guide/start-install) 用 **NapCatInstaller**（Windows）安装 **NapCat.Shell**，或到 [Releases](https://github.com/NapNeko/NapCatQQ/releases) 下载 zip 解压。
3. 启动器默认找 `C:\NapCat\NapCat.Shell`（需包含 `launcher.bat`）；装在别处时在启动器「设置」页指定目录。

### 第 3 步 · 打通 AstrBot ↔ NapCat（一次性）

1. 启动 AstrBot，浏览器打开面板 `http://127.0.0.1:6185`，默认账号 `astrbot / astrbot`，**首次登录后请改密码**。
2. WebUI → 「消息平台」→ 新增平台，类型选 **aiocqhttp**，端口保持默认 `6199`。
3. 启动 NapCat 并登录机器人 QQ（NapCat WebUI 默认 `http://127.0.0.1:6099`）。
4. NapCat 的「网络配置」里新增 **反向 WebSocket 连接**，地址填 `ws://127.0.0.1:6199/ws`。
5. AstrBot 消息平台页出现「在线」即打通；用另一个 QQ 给机器人发句私聊验证。

### 第 4 步 · 回到 SnowBotLauncher

1. 「设置」页确认 AstrBot 目录、NapCat 目录与三个端口（默认 `6185 / 6199 / 6099`）。
2. 「控制台」页点「一键启动全部」，AstrBot 与 NapCat 状态灯都变绿。
3. 「增强配置」页连接 AstrBot 后台，配置人格、语音、记忆等；或用「配置包」一键应用整套配置。
4. **配置大模型服务商并设为默认**（DeepSeek / 智谱等，AstrBot WebUI 或增强配置页均可），机器人才会开始回复。

## 数据目录

程序目录只放可执行文件；用户数据在：

```
%LOCALAPPDATA%\SnowBotLauncher\
├─ config.json       # 控制台设置
├─ logs\             # AstrBot / NapCat 控制台日志
├─ packs\            # 配置包
├─ presets\          # 变量预设（不含密码与密钥）
├─ personas\         # 本地 Markdown 人格文件
└─ backups\          # 应用配置包前的自动备份
```

安装版以管理员运行，配置和日志不写 Program Files，升级/卸载不会被文件锁影响。

## 开发运行

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

也可以直接运行 `scripts\run_dev.bat`（无控制台）或 `scripts\run_dev_console.bat`（带控制台）。

## 打包

```bat
build.bat
```

构建流程：

1. PyInstaller 从 `main.py` 打包为 `dist\SnowBotLauncher\SnowBotLauncher.exe`（onedir，管理员清单，附带 examples/docs）
2. Inno Setup 编译出 `installer\output\SnowBotLauncher-Setup-1.5.41.exe`

需要 Inno Setup 6（`ISCC.exe`），默认查找 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`。

## 安装

运行生成好的安装包：

```
installer\output\SnowBotLauncher-Setup-1.5.41.exe
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

## 免责声明

- 本项目是 AstrBot / NapCat 的第三方管理工具，与 AstrBot、NapCat、腾讯 QQ、Bilibili、UEX Corp 均无 affiliation。
- 通过 NapCat 运行机器人属于非官方客户端接入，存在账号风控风险，请自行评估并承担；建议使用小号。
- B 站视频理解、UEX 星际公民数据等插件使用的是对应平台的公开/非官方接口，平台策略变化可能导致功能失效。
- 本项目仅供学习交流，请勿用于任何违反当地法律法规或平台服务条款的用途。

## 许可证

[MIT](LICENSE)。`plugins/` 与 `snowbot/` 下的代码均可自由使用与修改；第三方插件（如豆包语音插件）不在本仓库分发，请从其原始来源获取。
