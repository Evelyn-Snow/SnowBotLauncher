# 小雪引用回复

让她自己判断**要不要引用、该回哪一句**，而不是每条消息都引用，也不是靠用户下命令。

## 行为

每个进入会话的消息先记进本地小历史（带 QQ `message_id`、发送者、时间、文本）。
模型觉得下面任一情况时，会调用 `quote_reply` 工具搜索前文：

- 当前话题混乱，对方同时说了几件事
- 要回的那句在很前面，直接说会指代不清
- 需要把一句旧话重新拉回来对齐

工具会在当前会话的历史里按原话片段/关键词/描述搜索最相关的一条，并且要求：

- 目标至少相隔 `min_message_distance` 条消息，**或**
- 目标至少相隔 `min_time_distance_minutes` 分钟

太近的目标会被拒绝（“不需要引用，直接回答”），不会为了引用而引用。

命中后，只在她这一轮回复的消息链最前面加一个 `Reply`，QQ 显示为引用回复。

## 频率限制

- 同一会话两次引用至少间隔 `cooldown_minutes`（默认 30 分钟）
- 每小时最多 `max_per_hour`（默认 2 次）
- 每天最多 `max_per_day`（默认 6 次）
- 普通聊天提示词明确要求“不要引用、不要频繁用”

## 搜索

- 只搜当前会话最近 `lookback_minutes`（默认 720 分钟）/ `lookback_messages`（默认 200 条）
- 支持原话片段、关键词、「引号里的原话」、消息 id
- 匹配分低于 `search_threshold` 会拒绝，宁可不引用也不引错

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| enabled | true | 总开关 |
| lookback_minutes | 720 | 搜索前文的时间范围 |
| lookback_messages | 200 | 最多回看条数 |
| min_message_distance | 4 | 至少相隔几条消息 |
| min_time_distance_minutes | 10 | 至少相隔几分钟 |
| search_threshold | 0.2 | 匹配阈值 |
| cooldown_minutes | 30 | 两次引用最小间隔 |
| max_per_hour | 2 | 每小时上限 |
| max_per_day | 6 | 每天上限 |
| history_per_session | 300 | 每会话保留前文条数 |
| intent_ttl_seconds | 300 | 引用意图有效期 |

## 注意

- 历史只在本地 `plugin_data` 里，不外部发送。
- 群聊里如果消息本身没有唤醒她，工具也不会被调用；需要 @ 她或回复她。
- 引用目标来自她能看到的会话前文；她没见过的消息（入群前、被平台截断）搜不到。
