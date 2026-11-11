# 小雪状态

让她按虚拟日程和心情，自己更新 QQ 签名与在线状态。

- 读当天虚拟时间线，知道她现在在做什么（写论文、上课、吃饭、睡前…），并带上最近一条真实经历
- 每隔 4–8 小时（可调）生成一句不超过 24 字的签名并写入 QQ 资料
- 在线状态跟着活动走：写论文→肝作业、上课/自习→学习中、睡觉→睡觉中、追剧→追剧中、散步→悠哉哉…
- 静默时段（默认 23–8 点）不更新，避免半夜改资料
- 需要协议端支持 `set_qq_profile` / `set_online_status`（NapCat、SnowLuma 均支持）

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| enabled | true | 总开关 |
| signature_enabled | true | 自动改签名 |
| status_enabled | true | 自动改在线状态 |
| min_interval_hours / max_interval_hours | 4 / 8 | 更新间隔范围 |
| quiet_hours | 23-8 | 静默时段 |
| max_chars | 24 | 签名长度上限 |

QQ 空间说说由 `astrbot_plugin_qzone` 负责（默认每天 23:30 左右自动发一条）；本插件只管签名和在线状态。
