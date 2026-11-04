# 小雪看视频听语音

把群里的视频文件和语音消息变成她能读的文字。

## 语音消息

- QQ 语音（`Record`）用本地 faster-whisper 转写
- 替换成 `（语音消息）……` 再交给对话模型，她能像听语音一样接话
- 转写失败会变成「（语音消息）没听清内容」，不会假装听懂
- 群聊默认只处理 **@她 / 引用她** 的语音；私聊全部处理

## 视频文件

- 支持 QQ 视频消息（`Video`）和群文件里的 mp4/mov/mkv/webm 等
- ffmpeg 按时间抽 9 帧拼成一张带时间标签的图，交给视觉模型描述
- 同时抽音频转写；默认只转写前 2 分钟，画面仍按整段抽帧
- 超过 10 分钟或 150MB 的视频不处理，避免卡太久/占磁盘
- 群聊默认只处理 **@她 / 引用她** 的视频；私聊全部处理

## 依赖

- **Pillow**（拼图）
- ffmpeg / ffprobe（启动器自带或系统 PATH）
- 单独的 faster-whisper 环境（配置 `asr_python`）
- 一个能看图的模型（配置 `vision_provider_id`，留空用当前对话模型）

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| enabled | true | 总开关 |
| voice_enabled | true | 转写语音 |
| voice_group_mode | addressed | 群语音：addressed/all/off |
| video_enabled | true | 理解视频文件 |
| video_group_mode | addressed | 群视频：addressed/all/off |
| audio_file_enabled | true | 群文件音频也转写 |
| video_max_mb | 150 | 视频大小上限 |
| video_max_seconds | 600 | 最长处理时长 |
| video_inline_seconds | 120 | 最多转写前多少秒音频 |
| frame_cols / frame_rows | 3 / 3 | 画面拼图 |
| max_videos_per_message | 1 | 一条消息最多几个视频 |
| vision_provider_id | 空 | 视觉模型 id |
| ffmpeg / ffprobe | 空 | 留空自动找 |
| asr_python | 空 | 装了 faster-whisper 的解释器 |
| asr_model / asr_threads / asr_compute_type | small / 2 / int8 | ASR 参数 |
| asr_language / asr_initial_prompt / asr_download_root | 空 | 同 bili_vision |
| voice_timeout_seconds | 90 | 单条语音识别超时 |
| video_asr_timeout_seconds | 300 | 视频音频识别超时 |

## 说明

- 视频处理是同步的：短视频几十秒内出结果；长视频只取前段音频，避免一条消息卡几分钟。
- 临时音频/帧文件在处理完立即删除；源视频由 AstrBot 自己管理。
- 不主动下载群文件以外的链接；只处理消息里实际带的多媒体组件。
