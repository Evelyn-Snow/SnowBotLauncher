# 发文件

让她把自己的文件（课程论文、随笔、图片等）发到私聊或群聊里。

## 能力

- `list_my_files`：列出允许目录里能发的文件（默认只列 20 个）
- `send_my_file`：按文件名/相对路径发送；私聊走 `upload_private_file`，群聊走 `upload_group_file`，失败回退消息链

## 安全边界

- **只发允许目录**：默认插件数据目录 `share/`；线上可配置为她自己的「写作」「分享」文件夹，不要配 `C:\Evelyn_Snow` 根目录
- **路径校验**：绝对路径也会检查是否落在允许目录内；`../`、目录穿越、符号链接外逃都会拒绝
- **扩展名白名单**：默认 md/txt/pdf/docx/pptx/xlsx/jpg/jpeg/png/gif/webp/zip
- **隐私关键词**：文件名或路径含「画像/关系/日记/记忆/配置/密码/密钥/token/account」等直接拒绝
- **内容扫描**：md/txt 前 512KB 命中管理员/机器人 QQ 号或密码、token、私钥特征就拒绝
- **大小与频率**：默认单文件 20MB、每小时最多 3 次；每次发送写审计日志 `send_audit.jsonl`

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| enabled | true | 总开关 |
| allow_dirs | 空 | 每行一个允许目录；留空 = 插件数据目录 share/ |
| allowed_ext | md,txt,pdf,... | 允许的后缀 |
| deny_keywords | 空 | 留空用内置隐私关键词 |
| max_mb | 20 | 单文件上限 |
| max_per_hour | 3 | 每小时发送次数上限 |
| list_limit | 50 | 列表上限 |
| scan_text | true | 扫描文本里的账号/密钥 |

## 依赖

无额外依赖；文件上传依赖协议端支持 `upload_private_file` / `upload_group_file`（NapCat、SnowLuma 均支持）。
