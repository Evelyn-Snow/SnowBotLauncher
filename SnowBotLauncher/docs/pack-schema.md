# SnowBot Pack 格式

SnowBotLauncher 的「配置包」由一个文件夹构成，核心是 `pack.json` 清单。设计参考了 dafeiyu-config-pack 的「清单驱动 + 后台 API + 可重复执行」，并增加了通用变量、条件步骤、备份回滚与脚本扩展。

```
my-pack/
├─ pack.json
├─ persona/xxx.md          # 可选，人格文本
├─ plugins/xxx/            # 可选，随包插件（文件夹或 zip）
└─ hooks/xxx.py            # 可选，脚本步骤
```

## 最小清单

```json
{
  "schema": "snowbot-pack/1",
  "id": "my-pack",
  "name": "我的配置包",
  "version": "1.0.0",
  "author": "you",
  "description": "说明",
  "tags": ["人格"],
  "variables": [],
  "steps": [
    {"type": "persona", "id": "示例", "file": "persona/example.md"}
  ]
}
```

`schema` 固定为 `snowbot-pack/1`；`id` 唯一；`steps` 决定执行内容。

## 变量

```json
{
  "key": "owner_qq",
  "label": "所有者 QQ",
  "type": "text",
  "required": true,
  "pattern": "\\d+",
  "default": "",
  "placeholder": "123456789",
  "description": "只允许数字"
}
```

支持的 `type`：

| 类型 | 控件 | 说明 |
|---|---|---|
| `text` | 单行输入 | 默认 |
| `password` | 密码输入 | 不写入预设文件；建议同时设 `"secret": true` |
| `select` | 下拉框 | `options`: `[{"value":"1","label":"选项一"}]` 或 `["1","2"]` |
| `bool` | 勾选框 | 默认值为布尔 |
| `multiline` | 多行文本 | 适合 JSON 片段 |

变量会注入到内置上下文：

| 名称 | 含义 |
|---|---|
| `${base_url}` | AstrBot 后台地址 |
| `${platform_id}` | OneBot v11 平台 ID |
| `${chat_provider_id}` | 当前对话模型 ID |
| `${owner_qq}` | 变量中同名值 |
| `${owner_session}` | `平台ID:FriendMessage:所有者QQ` |
| `${pack_dir}` / `${data_dir}` / `${backups_dir}` | 目录 |
| `${pack_id}` / `${pack_name}` / `${pack_version}` | 包信息 |

字符串中的 `${变量名}` 会在执行前替换。人格文件里的 `{OWNER_QQ}` 这类旧式占位符，可用步骤的 `replace` 映射处理。

## 条件步骤

每个步骤都可以写 `when`，支持变量名、常量、比较、`and/or/not/in`：

```json
{"type": "pip.install", "packages": ["edge-tts==7.3.1"], "when": "voice == '1'"}
```

## 步骤类型

### persona

写入/更新人格。

```json
{
  "type": "persona",
  "id": "${persona_name}",
  "file": "persona/example.md",
  "replace": {"{OWNER_QQ}": "${owner_qq}"},
  "extra": {"begin_dialogs": []}
}
```

`file` 相对于包目录；也可以用 `prompt` 直接写文本。

### config.set

批量修改 AstrBot 全局配置（点号路径）。

```json
{"type": "config.set", "values": {"platform_settings.segmented_reply.enable": true}}
```

### plugin.install

从插件市场或随包文件安装插件。

```json
{"type": "plugin.install", "market_id": "author/astrbot_plugin_xxx", "name": "astrbot_plugin_xxx"}
{"type": "plugin.install", "path": "plugins/my_plugin", "name": "my_plugin", "force": false}
```

### plugin.config / plugin.enable / plugin.reload

```json
{"type": "plugin.config", "plugin": "astrbot_plugin_xxx", "values": {"a.b": "${owner_session}"}}
{"type": "plugin.enable", "plugin": "astrbot_plugin_xxx", "enabled": true}
{"type": "plugin.reload", "plugin": "astrbot_plugin_xxx"}
```

插件未安装时，`plugin.config` 默认跳过；设 `"required": true` 则视为失败。

### provider.upsert / provider.test

写入或测试模型提供商（对话、嵌入、TTS 等）。

```json
{
  "type": "provider.upsert",
  "test": true,
  "disable_on_fail": true,
  "provider": {
    "id": "my-embedding",
    "type": "openai_embedding",
    "provider": "openai",
    "provider_type": "embedding",
    "enable": true,
    "embedding_api_base": "https://api.siliconflow.cn/v1",
    "embedding_api_key": "${siliconflow_key}",
    "embedding_model": "BAAI/bge-m3"
  }
}
```

### pip.install

```json
{"type": "pip.install", "packages": ["edge-tts==7.3.1"]}
```

### tool.permission

```json
{"type": "tool.permission", "tool": "set_signature", "permission": "admin"}
```

### http

直接调用 `/api/v1` 下的扩展接口，便于适配插件自己的 API。

```json
{"type": "http", "method": "POST", "path": "/plugins/extensions/meme_manager/community/install", "body": {"pack_id": "xxx"}, "timeout": 900}
```

### script

运行包内 Python 脚本（需要用户在界面勾选允许）。脚本使用 AstrBot 的 Python 解释器，工作目录为包目录。

```json
{
  "type": "script",
  "file": "tools/import_xxx.py",
  "args": ["--answers", "{answers_file}"],
  "answers": {"base_url": "${base_url}", "owner_qq": "${owner_qq}"},
  "python": "astrbot",
  "timeout": 3600
}
```

引擎会把 `answers` 写成临时 JSON（结束后删除），并通过 `{answers_file}` 传入。脚本环境变量包含：

- `SNOWBOT_PACK_DIR`
- `SNOWBOT_DATA_DIR`
- `SNOWBOT_ASTRBOT_URL`
- `SNOWBOT_PLATFORM_ID`

## 备份与还原

应用前会抓取全局配置、涉及的人格/插件配置/提供商，写入
`%LOCALAPPDATA%\SnowBotLauncher\backups\<包ID>-<时间>\snapshot.json`。
「还原备份」会用该快照覆盖对应配置；新安装的插件不会自动卸载。

## 旧版配置包

若导入的文件夹满足：

- 有 `settings/pack.json`
- 有 `tools/import_*.py`

SnowBotLauncher 会自动包装成 `legacy-*` 配置包：生成变量表和一个 `script` 步骤，调用原导入器并传入 `--answers`。大肥鱼配置包会得到所有者 QQ、记忆方式、语音方案等变量。

## 安全建议

- 只导入来源可信的配置包；`script` 步骤会执行代码。
- 密钥类变量用 `password` + `secret`，预设文件不会保存它们。
- 应用前先「预览计划」，确认步骤和条件符合预期。
