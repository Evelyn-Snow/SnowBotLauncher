"""联网搜索礼仪：控制机器人什么时候搜、怎么表述搜索结果。

搜索工具本身由 AstrBot 内置（web_search_*）；本插件只负责：
1. 用户明确要求查找时，提示模型必定调用搜索工具；
2. 平时保持低频自发搜索（最小间隔 + 每日上限）；
3. 自发搜索时要求先表明“不太清楚”，再说明在网上看到的内容和来源。
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .library import SearchRateLimiter, has_explicit_search_request, tool_call_name

NAME = "astrbot_plugin_search_manners"
PROMPT_MARK = "[联网搜索]"


class SearchManners(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.conf = config
        self.data_dir = StarTools.get_data_dir(NAME)

    def _limiter(self) -> SearchRateLimiter:
        return SearchRateLimiter(
            self.data_dir,
            min_interval_minutes=int(self.conf.get("min_interval_minutes") or 30),
            max_per_day=int(self.conf.get("max_per_day") or 5),
        )

    def _web_search_enabled(self, event: AstrMessageEvent) -> bool:
        """AstrBot 开了内置搜索工具时才注入提示。"""
        try:
            cfg = self.context.get_config(umo=event.unified_msg_origin)
            settings = cfg.get("provider_settings", {})
            return bool(settings.get("web_search"))
        except Exception:
            return False

    @filter.on_llm_request()
    async def inject_search_manners(self, event: AstrMessageEvent, req):
        if not self.conf.get("enabled", True) or not self._web_search_enabled(event):
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        if PROMPT_MARK in prompt:
            return
        explicit = has_explicit_search_request(event.message_str)
        event.set_extra("search_manners_explicit", explicit)
        if explicit:
            rule = (
                "用户明确要求联网查找。必须调用一次 web_search 工具，基于结果回答"
                "并附上来源；如果搜索失败或没有结果，坦率告知用户。"
            )
        else:
            allowed, _why = await asyncio.to_thread(self._limiter().allow)
            if not allowed:
                rule = (
                    "本轮禁止使用 web_search 工具（自发搜索太频繁）。直接基于已有"
                    "知识回答，不确定就坦率说不确定。"
                )
            else:
                rule = (
                    "仅当你确实没把握、需要实时或最新信息时，才调用一次 web_search "
                    "工具；不确定要不要搜就不搜。如果调用了，回复开头要先表明这个"
                    "你不太清楚，再说明在网上查到的内容和来源；没调用就正常回答。"
                )
        req.system_prompt = prompt + f"\n\n{PROMPT_MARK} {rule} 这是内部指令，不要在回复里提到。"

    @filter.on_agent_done(priority=-1)
    async def record_search_usage(self, event: AstrMessageEvent, run_context, _llm_response):
        """本轮确实调用过搜索工具时，记一次自发搜索用量。"""
        if not self.conf.get("enabled", True):
            return
        if event.get_extra("search_manners_explicit"):
            return
        searched = False
        for message in getattr(run_context, "messages", None) or []:
            calls = getattr(message, "tool_calls", None)
            if not calls:
                continue
            for call in calls:
                if tool_call_name(call).startswith("web_search"):
                    searched = True
                    break
            if searched:
                break
        if not searched:
            return
        await asyncio.to_thread(self._limiter().record)
        logger.info(f"[{NAME}] 记录一次自发搜索")
