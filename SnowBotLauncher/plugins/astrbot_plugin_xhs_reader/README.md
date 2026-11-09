# 小红书阅读

别人分享小红书笔记时，她真的读过再聊——不是只看分享卡片上那句标题。

## 能力

- **识别**：消息里的 `xiaohongshu.com/explore/...`、`/discovery/item/...`、`xhslink.com` 短链都能认出来（QQ 分享卡片转成的文字里也认）
- **读懂图文笔记**：抓标题、正文、作者、标签；下载图片拼成对比图交给视觉模型描述画面
- **读懂视频笔记**：下载视频，按时间均匀抽 9 帧拼图描述画面；可选转写语音（faster-whisper，和 B站视频理解同一套配置）
- **自动预取**：消息里一出现笔记链接，就先把标题/正文/标签抓下来注入上下文（10 分钟缓存），不依赖模型主动调工具；图文/视频细节再按需调用
- **自然回应**：把笔记原文 + 画面 + 语音材料合成一段总结，她用自己的口吻接着聊；没看到的细节不许编

## 触发

- 消息里出现小红书链接时，自动提示她调用 `read_xiaohongshu`（没提问也先读）
- 也可以直接在聊天里问她「这个笔记讲了什么」

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| enabled | true | 总开关 |
| max_images | 6 | 图文笔记最多看几张（1-9） |
| vision_provider_id | 空 | 视觉模型 id；留空用当前对话模型 |
| video_enabled | true | 视频笔记抽画面 |
| video_max_mb | 80 | 视频大小上限 |
| video_max_seconds | 300 | 视频最长处理时长 |
| video_inline_seconds | 120 | 最多转写前多少秒语音 |
| frame_count | 9 | 视频抽帧数 |
| grid_cols | 3 | 拼图列数 |
| asr_enabled | false | 转写视频语音（需配 asr_python） |
| asr_python / asr_model / asr_threads / asr_compute_type | 空 / small / 2 / int8 | 同 bili_vision |
| asr_language / asr_initial_prompt / asr_download_root | 空 | 同 bili_vision |
| asr_timeout_seconds | 300 | 单次转写超时 |
| ffmpeg / ffprobe | 空 | 留空自动找启动器自带或 PATH |
| request_timeout_seconds | 30 | 抓笔记页超时 |

## 限制

- **安全守卫白名单**：snow_guard 默认已包含 xiaohongshu.com / xhslink.com / xhs.cn；如果你改过白名单，记得把这三个域名加回去，否则她会按安全规则拒绝打开
- **分享链接要完整**：小红书笔记需要 `xsec_token` 才能打开，从 App「分享」复制的链接才带；手打或过期的裸链接会失败
- 笔记已删除、设私密、仅粉丝可见时读不到
- 视频只转写前 `video_inline_seconds` 秒，超长视频只取前段
- 依赖 Pillow（拼图）；ASR 依赖单独的 faster-whisper 环境
