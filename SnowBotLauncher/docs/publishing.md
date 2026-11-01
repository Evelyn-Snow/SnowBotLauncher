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

机制：每个插件放一个**独立公开仓库**（命名 `astrbot_plugin_*`），推送到 GitHub 后提交到 AstrBot 插件市场。两条提审路径：

- **AstrBot Cloud 发布页（推荐）**：打开 <https://cloud.astrbot.app/publish>，填插件仓库地址即可自动解析提交；**同一账号同时最多 3 个在审**，8 个插件分 3+3+2 三批提。
- **GitHub Issue**：到 [AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot/issues/new/choose) 选 `[Plugin]` 模板，内容用 `plugin-releases\_submit\<插件名>-issue.md` 里的文本。

审核通过后收录进插件市场索引。

### 发布步骤（已全部准备就绪）

1. GitHub 上创建 8 个**空**公开仓库（名字与 `plugins/` 下目录一致，不要勾选自动生成 README/LICENSE）。
2. 逐个推送（仓库已在 `C:\Working_Files\AIMade\plugin-releases\<插件名>\` 准备好，含首次提交）：

   ```
   cd C:\Working_Files\AIMade\plugin-releases\astrbot_plugin_star_citizen
   git remote add origin https://github.com/Evelyn-Snow/astrbot_plugin_star_citizen.git
   git push -u origin main
   ```

3. 到 AstrBotDevs/AstrBot 提 `[Plugin]` Issue：提审文本已生成在 `plugin-releases\_submit\<插件名>-issue.md`，复制粘贴即可。
4. 源码改动后重新同步：`python scripts\sync_plugin_repos.py`（加 `--init` 只对新仓库生效，已有 .git 的目录只更新文件，自行 commit/push）。

审核要点（来自官方审核规则，全部已满足）：

- 代码符合 PEP 8（>99 字符长行已清理），`metadata.yaml` 字段完整（`author`/`repo` 已按 GitHub 账号 Evelyn-Snow 填写）。
- 插件数据用 `StarTools.get_data_dir()`（search_manners、obsidian_notes、snow_imagebox 未配置路径时均走此目录），不写 AstrBot 全局 data 目录。
- 配置键与 `_conf_schema.json` 一致（obsidian 的无用键 `max_search_results` 已移除）。
- 每个插件仓库带 `README.md`（功能 + 配置 + 依赖说明）、`LICENSE`（MIT）、`requirements.txt`（仅 bili_vision 需要 Pillow）。

## 三、各插件上架状态（2026-11-01 已全部就绪）

| 插件 | 版本 | 本次改动 |
|---|---|---|
| share_card | v0.1.2 | metadata 补 repo/author |
| search_manners | v0.1.1 | metadata 补 repo/author |
| snow_sleep | v0.1.1 | 改名「机器人作息」、去 emoji 日志、metadata |
| snow_continuity | v0.2.1 | **GCP 导入改为插件注册表动态定位**、README 声明依赖、metadata |
| star_citizen | v0.1.2 | metadata 补 repo/author |
| bili_vision | v0.1.2 | **requirements.txt（pillow）**、provider 默认值泛化+回退、README 依赖说明、metadata |
| snow_imagebox | v0.2.3 | library_path 空值回退 StarTools 数据目录、metadata |
| obsidian_notes | v0.3.1 | 移除无用 schema 键、README 重写（配置表）、metadata |

另有豆包语音插件（seed_audio_tts）是第三方作品，**不由本仓库或本团队上架**；启动器只在其被用户导入后自动打兼容补丁。

## 四、发布前已完成的准备工作

- 脱敏：插件配置示例与测试数据中的真实 QQ 号、用户名已替换为虚构值（`123456789`、`2345678901`、`demo_user`）。
- 许可证：根目录 `LICENSE`（MIT）。
- README：新增「免责声明」「许可证」章节。
- Git 历史扫描：全部 commit 无密码、API Key、Cookie、真实 QQ 号、实例 ID。
