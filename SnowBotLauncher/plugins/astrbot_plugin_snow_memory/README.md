# 全局记忆

全局学习、按听众读取。

## 它解决什么

现有记忆分散在画像、共享卡片、LivingMemory 摘要、真实经历和日记里，同一个事实有多份副本，却没有一套“事实的主数据”。这个插件把记忆重新分成四层：

- **事件账本**：所有会话、真实经历、日记/说说都只追加不改写，是唯一事实源；
- **事实**：`subject-predicate-object`，带 `valid_from/valid_to`（世界上何时为真）、`learned_at/invalidated_at`（系统何时知道/失效）、置信度、隐私级别和证据事件 ID；
- **洞察**：从多条事实归纳出的稳定认识，必须引用事实 ID，可版本化；
- **检索**：向量 + 关键词 + 时间/重要性打分，按当前听众过滤后注入。

## 全局学习 ≠ 全局复述

采集覆盖所有会话（私聊、群聊、真实经历），但每条事实带隐私级别：

| privacy | 含义 | 谁能在哪里看到 |
|---|---|---|
| 0 | 绝密 | 永远不注入 |
| 1 | 仅主人 | 主人私聊/主人相关会话 |
| 2 | 仅当事人 | 当事人所在的同一个会话；主人的事可以在主人面前提 |
| 3 | 同会话/同群 | 同一个群或同一个私聊 |
| 4 | 公开 | 任何会话 |

因此：A 朋友私聊说的秘密不会被搬进群；群里的私事不会飘到另一个群；主人私聊的事也不会进群。她可以“知道”，但不会“见谁都说”。

## 数据流

```
聊天每轮 / 真实经历
   → events（append-only）
   → 每 30 分钟增量抽取 facts（证据对不上就丢弃）
   → 事实够多时归纳 insights（必须引用事实 ID）
   → 聊天时按听众过滤 + 混合打分 → 注入少量事实/洞察
```

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| `capture_enabled` | true | 采集所有会话 |
| `include_groups` | true | 采集群聊（默认 privacy=3） |
| `include_webchat` | false | 网页测试台默认不采集，避免污染 |
| `extract_enabled` | true | 自动抽取事实 |
| `extract_batch_size` | 24 | 每批事件数 |
| `extract_interval_minutes` | 30 | 抽取检查间隔 |
| `retrieve_enabled` | true | 聊天时检索 |
| `shadow_mode` | false | 只抽取不注入，用来先看质量 |
| `insights_enabled` | true | Phase 2：归纳洞察 |
| `insight_min_facts` | 6 | 至少多少条事实才归纳 |
| `embedding_provider_id` | snowbot-memory | 本地 bge-m3 |
| `max_facts / max_insights` | 8 / 3 | 每轮最多注入 |
| `inject_limit_chars` | 900 | 注入字数上限 |

## 说明

- 数据库在插件数据目录 `memory.db`（SQLite + FTS5），不上传任何外部服务。
- 事实抽取用当前默认 LLM；向量用本地 embedding provider，不产生额外 API 费用。
- 证据校验是硬门槛：模型写的 `evidence` 必须在原始事件里连续出现，否则整条事实丢弃。
- 这是 Phase 1+2 的骨架：先跑事实层，洞察层可以单独关闭；画像渲染（Phase 2 后半）后续接入。
