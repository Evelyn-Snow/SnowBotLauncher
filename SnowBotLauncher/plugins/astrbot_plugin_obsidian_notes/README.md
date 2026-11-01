# Bot Obsidian 笔记

把日记、笔记写进本机 Obsidian 仓库（普通 Markdown 目录），支持搜索和读取来补充记忆。

## 目录

```text
<Vault>\
├─ 日记\            # 全局日记（自动日记写在这里）
├─ 笔记\            # 全局共享笔记
├─ 日记\私聊-<QQ>\   # 会话模式下的个人日记
└─ 笔记\群聊-<群号>\ # 会话模式下的群专属笔记
```

## 会话作用域（v0.3.0）

- `note_scope_mode=session`：笔记按会话分目录（`笔记/私聊-<QQ>/`、`笔记/群聊-<群号>/`）；工具里选 global 才写共享区
- `diary_scope_mode=session`：手动日记写进 `日记/<会话>/日期.md`，全局日记不变
- `auto_diary_per_scope=true`：每个会话各有独立的频率限制并各自写会话日记；全局加权日记仍照常

搜索和列出会遍历整个仓库（含所有会话目录）；读取笔记时优先找当前会话的，找不到自动找全局。

## 语义记忆

LivingMemory 另有 legacy / session / user / global 四种记忆作用域模式，在 AstrBot 插件配置里切换；切换不迁移旧记忆，可用 `/lmem migrate-scope <target> apply` 迁移。
