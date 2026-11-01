# 开源发布与插件上架指南

发布前的准备工作已在本仓库完成（见「已完成」一节），本文档记录剩余的发布步骤和插件市场提审要点。**注意：任何发布材料里都不要出现 AstrBot 后台密码、API Key、B站 Cookie、真实 QQ 号和本机实例路径。**

## 一、开源 SnowBotLauncher 到 GitHub

仓库已具备：MIT `LICENSE`、README 免责声明与许可证章节、`.gitignore`（排除 venv/build/dist/logs/安装包输出）、干净的 Git 历史（发布前已扫描，无任何密钥与个人信息）。

步骤：

1. 在 GitHub 上新建**空**仓库（不要勾选自动生成 README/LICENSE，避免与本地历史冲突），建议名 `SnowBotLauncher`。
2. 推送本地仓库：

   ```
   cd C:\Working_Files\AIMade\SnowBotLauncher
   git remote add origin https://github.com/<你的用户名>/SnowBotLauncher.git
   git push -u origin main
   ```

3. 建议在仓库页开启 Issues，并在 About 里写一句话简介（可复用 README 首段）。
4. 以后发布新版本时：改版本号（`snowbot/core/paths.py` 的 `APP_VERSION`、`installer/SnowBotLauncher.iss`、`build.bat`、README）→ 提交并打 tag（如 `v1.5.4`）→ 在 GitHub Releases 上传 `installer/output` 里的 Setup exe。

## 二、插件上架 AstrBot 插件市场

机制：每个插件放一个**独立公开仓库**（命名 `astrbot_plugin_*`，本仓库 `plugins/` 下的目录可直接作为仓库根），推送到 GitHub 后到 [AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot) 用 `[Plugin]` 模板提 Issue，附插件仓库地址；机器人自动审核通过后收录进插件市场索引。

审核要点（来自官方审核规则）：

- 代码符合 PEP 8，`metadata.yaml` 字段完整（注意 `author` 字段格式）。
- 插件数据必须用 `StarTools.get_data_dir()` 获取，不允许自行操作 AstrBot 全局数据目录。
- 指令参数解析、配置键名要与 `metadata.yaml` / `_conf_schema.json` 一致。
- 建议每个插件仓库带：`README.md`（功能、配置说明、截图）、`LICENSE`（MIT 即可）、`requirements.txt`（有第三方依赖时）。

## 三、各插件上架状态

| 插件 | 状态 | 上架前待办 |
|---|---|---|
| share_card | 基本就绪 | 补 README/LICENSE；确认无落盘需求说明 |
| search_manners | 就绪 | 已用 `StarTools.get_data_dir()`；补 README/LICENSE |
| snow_sleep | 基本就绪 | 补 README/LICENSE；说明豁免逻辑 |
| snow_continuity | 基本就绪 | 补 README/LICENSE |
| star_citizen | 基本就绪 | 补 README/LICENSE；README 注明数据来自 UEX 公开接口 |
| bili_vision | 小改 | 默认视觉 provider id `snowbot-caption` 泛化为可配置项；说明依赖用户自配视觉模型 |
| snow_imagebox | 要过审 | 图片存储路径改为走插件数据目录或明确声明为用户自定义路径 |
| obsidian_notes | 要过审 | 已用 `StarTools.get_data_dir()`；Obsidian 仓库路径必须保持为用户配置项，README 说明会写入用户指定的仓库 |

另有豆包语音插件（seed_audio_tts）是第三方作品，**不由本仓库或本团队上架**；启动器只在其被用户导入后自动打兼容补丁。

## 四、发布前已完成的准备工作

- 脱敏：插件配置示例与测试数据中的真实 QQ 号、用户名已替换为虚构值（`123456789`、`2345678901`、`demo_user`）。
- 许可证：根目录 `LICENSE`（MIT）。
- README：新增「免责声明」「许可证」章节。
- Git 历史扫描：全部 commit 无密码、API Key、Cookie、真实 QQ 号、实例 ID。
