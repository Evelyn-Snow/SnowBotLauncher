# 像个人

不改造人格，只改“怎么回”和“回多长”。

## 它做什么

- **按语境选语气**：这轮是随口应一声（`short`）、先接情绪（`warm`）、正经回答（`answer`），还是普通聊天（`normal`）。选择会参考消息长短、是不是问题、有没有情绪词、最近几轮她是不是一直在长篇，以及这个会话累积的“精力”。
- **拆成自然气泡**：把回复按句子重新分组，通常 1~2 段，最多 3 段；交给 AstrBot 自带的分段回复逐条发送。每个气泡内部只保留最后一个句末标点，避免被二次切碎。
- **打破“关心+叮嘱”模板**：如果上一轮已经是两段式，下一轮会明确要求换结构；短回模式还会在句末截断，最多留一两句。
- **群聊低频接话**：没被 @/点名、对方只是“哈哈/嗯/好”时，按概率不接；私聊永远会回。

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 总开关 |
| `enabled_platforms` | `aiocqhttp,webchat` | 生效平台 |
| `short_reply_max_chars` | `45` | 短回模式最多保留字数 |
| `two_bubble_chance` | `0.35` | 普通聊天拆两段的概率 |
| `three_bubble_chance` | `0.1` | 普通聊天拆三段的概率 |
| `group_skip_low_content` | `true` | 群聊低信息消息偶尔不接 |
| `group_skip_chance` | `0.55` | 不接的概率 |
| `state_ttl_days` | `7` | 会话状态保留天数 |

## 依赖

- AstrBot 的 `platform_settings.segmented_reply.enable` 需要为 `true`，气泡才会逐条发送；关闭时只做短回截断，不拆分。
- 与 `meme_manager`、`snow_reply`、`snow_continuity` 的发出前钩子兼容：它在最后执行，只改文字，不动引用、表情包和语音。
