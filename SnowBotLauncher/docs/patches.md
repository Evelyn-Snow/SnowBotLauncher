# 第三方插件补丁

## qzone：SnowLuma 定时发说说报 ApiNotAvailable

**现象**：`astrbot_plugin_qzone` 的 AutoPublish/AutoComment 日志里出现
`任务执行失败: ApiNotAvailable`，`/api/plug/astrbot_plugin_qzone/page/status`
显示 `login.bound=false`，说说一条都发不出去。

**原因**：qzone 在调度任务里调用 `get_cookies(domain="user.qzone.qq.com")`。
调度上下文没有 `event_ws`，SnowLuma/NapCat 的 CQHttp 对象在 WS 重连后可能：
1. 仍持有旧连接（`_wsr_api_clients` 为空），且 `_capture_page_client` 不会刷新；
2. 有多个连接时无法推断 `self_id`。

**补丁**：`scripts/patches/patch_qzone_snowluma.py`，对部署目录执行：

```bat
python scripts\patches\patch_qzone_snowluma.py ^
  "%USERPROFILE%\.astrbot_launcher\instances\<id>\core\data\plugins\astrbot_plugin_qzone"
```

改动两处：
- `core/qzone/session.py`：`get_cookies(..., self_id=...)` 显式传 Bot 账号；
- `main.py`：`_capture_page_client` 校验 CQHttp 对象是否还有 WS 连接，失效则重新绑定。

补丁可重复执行；升级 qzone 插件后需要重新打一次。
