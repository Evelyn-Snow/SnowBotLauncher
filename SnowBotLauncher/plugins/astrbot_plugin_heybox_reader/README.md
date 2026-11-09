# 小黑盒阅读

别人分享小黑盒帖子、视频或游戏卡片时，她先读再聊。

## 能读到什么

| 内容 | 来源 | 说明 |
|---|---|---|
| 帖子标题/摘要/封面 | QQ 分享卡片 | **始终可用**；即使接口被验证码拦住也能聊摘要 |
| 帖子正文/图片/视频 | 小黑盒接口 | 需要登录 Cookie，且接口仍可能要求腾讯验证码；成功时能读全文 |
| 视频画面/语音 | 帖子视频或卡片视频 | 抽 9 帧看画面；可选 faster-whisper 转写前 120 秒语音 |
| 游戏卡片 | 分享卡片 + Steam 公开接口 | 补类型、发售日期、价格、简介（Steam 上有的游戏） |

## 触发

- 消息里出现小黑盒链接（`xiaoheihe.cn`、`api.xiaoheihe.cn/.../web/share?link_id=`、`heybox://` 协议）时，自动提示她调用 `read_heybox`
- 也可以直接在聊天里问她「这个小黑盒帖子讲了什么」

## 已知限制

- **小黑盒帖子接口有腾讯验证码**：未登录/无 Cookie 时通常返回 `show_captcha`，只能读分享卡片里的摘要和封面。这是服务端反爬，不是插件故障
- 想读完整正文：在 `heybox_cookie` 里填浏览器登录后的 Cookie（可能仍会触发验证码，取决于风控）
- 游戏卡片依赖 Steam 商店接口；小黑盒独占游戏或未在 Steam 上架的游戏只能按卡片标题/摘要聊
- 只处理分享内容，不主动搜索小黑盒

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| enabled | true | 总开关 |
| vision_provider_id | 空 | 视觉模型 id；留空用当前对话模型 |
| heybox_cookie | 空 | 可选，登录 Cookie，用于尝试读取完整正文 |
| heybox_device_id | 空 | 可选，一般留空 |
| steam_enrich | true | 游戏卡片补充 Steam 信息 |
| max_images | 6 | 最多看几张图（1-9） |
| video_enabled / video_max_mb / video_max_seconds | true / 80 / 300 | 视频处理开关与上限 |
| video_inline_seconds | 120 | 最多转写前多少秒语音 |
| frame_count / grid_cols | 9 / 3 | 抽帧数与拼图列数 |
| asr_enabled / asr_python / asr_model / asr_threads / asr_compute_type | false / 空 / small / 2 / int8 | 语音转写（同 bili_vision） |
| asr_language / asr_initial_prompt / asr_download_root | 空 | 同 bili_vision |
| asr_timeout_seconds | 300 | 单次转写超时 |
| ffmpeg / ffprobe | 空 | 留空自动找 |
| request_timeout_seconds | 20 | 接口请求超时 |

## 依赖

- Pillow（拼图）
- ffmpeg / ffprobe（视频抽帧与音频）
- 可选 faster-whisper 环境（语音转写）
