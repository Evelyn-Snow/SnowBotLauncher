"""Bot 好友申请：自动通过「看起来是真人的」好友申请，其余留待人工。

判定在 library.evaluate 里：等级够高 / 有会员 / 是老号（短 QQ 号）三者之一就通过，
黑名单拒绝，其余挂起（不处理，保留在 QQ 的待处理列表里）。
每天有自动通过上限，防止被批量小号刷；通过后会私聊告知主人。

实现注意：AstrBot 会把 OneBot 的 request 事件转成 FRIEND_MESSAGE 交给插件，
原始事件在 event.message_obj.raw_message 里，靠 post_type/request_type 区分。
"""

from __future__ import annotations

from datetime import date

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    DECISION_ACCEPT,
    DECISION_REJECT,
    DailyCounter,
    describe,
    evaluate,
    extract_level,
    find_doubt_request,
    is_friend_request,
    is_friend_request_notice,
    is_vip,
    parse_qq_list,
)

NAME = "astrbot_plugin_snow_friend"


class SnowFriend(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._counter = DailyCounter(int(config.get("max_accept_per_day", 5) or 5))

    # ---------------- 配置 ----------------
    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _cfg(self, key, default):
        return self.conf.get(key, default)

    def _owner_umo(self) -> str:
        configured = str(self._cfg("owner_session", "") or "").strip()
        if configured:
            return configured
        try:
            cfg = self.context.get_config()
            admins = cfg.get("admins_id") or []
            platform_id = ""
            for p in cfg.get("platform", []) or []:
                if isinstance(p, dict) and p.get("type") == "aiocqhttp":
                    platform_id = str(p.get("id") or "")
                    break
            if admins and platform_id:
                return f"{platform_id}:FriendMessage:{admins[0]}"
        except Exception:
            pass
        return ""

    # ---------------- 协议端 ----------------
    def _client(self, event: AstrMessageEvent):
        bot = getattr(event, "bot", None)
        if bot is not None:
            return bot
        try:
            for inst in self.context.platform_manager.get_insts():
                if hasattr(inst, "get_client"):
                    return inst.get_client()
        except Exception:
            pass
        return None

    async def _stranger_info(self, client, qq: str) -> dict:
        """查申请者资料（等级、会员、昵称）。失败返回空 dict，不阻塞判定。"""
        try:
            data = await client.call_action("get_stranger_info", user_id=int(qq))
        except Exception as exc:
            logger.info(f"[{NAME}] 查询 {qq} 资料失败：{exc}")
            return {}
        if not isinstance(data, dict):
            return {}
        level_keys = sorted(
            k for k in data
            if k.lower() in ("qqlevel", "qq_level", "level", "vip_level", "vipflag", "vip_flag")
        )
        logger.info(
            f"[{NAME}] {qq} 资料：昵称={data.get('nickname') or '未知'} "
            f"等级={extract_level(data)} 会员={is_vip(data)} 相关字段={level_keys}"
        )
        return data

    @staticmethod
    async def _set_request(client, flag: str, approve: bool, comment: str = "") -> bool:
        try:
            await client.call_action(
                "set_friend_add_request", flag=flag, approve=bool(approve), remark=comment
            )
            return True
        except Exception as exc:
            logger.warning(f"[{NAME}] 处理好友申请失败：{exc}")
            return False

    # ---------------- 主流程 ----------------
    @filter.event_message_type(
        filter.EventMessageType.PRIVATE_MESSAGE, priority=(1 << 31) - 1
    )
    async def on_friend_request(self, event: AstrMessageEvent):
        """拦截加好友申请：判定资格后自动同意/拒绝/挂起。"""
        if not self._enabled():
            return
        message_obj = getattr(event, "message_obj", None)
        raw = getattr(message_obj, "raw_message", None)
        if not is_friend_request(raw):
            return
        # 这是申请事件，不是消息：处理完必须停掉，别让空消息进 LLM
        event.stop_event()

        qq = str(raw.get("user_id") or "").strip()
        if not qq:
            sender = getattr(message_obj, "sender", None)
            qq = str(getattr(sender, "user_id", "") or "").strip()
        flag = str(raw.get("flag") or "")
        comment = str(raw.get("comment") or "").strip()[:100]
        if not qq or not flag:
            logger.warning(f"[{NAME}] 好友申请缺少 user_id/flag，跳过：{raw}")
            return

        client = self._client(event)
        if client is None:
            logger.warning(f"[{NAME}] 没有可用的协议端，好友申请 {qq} 未处理")
            return

        info = await self._stranger_info(client, qq)
        decision, reason = self._evaluate(qq, info)
        today = date.today().isoformat()

        if decision == DECISION_ACCEPT:
            if not self._counter.allow(today):
                logger.info(
                    f"[{NAME}] 今日自动通过已达上限（{self._counter.limit}），"
                    f"{qq} 转入待处理（{reason}）"
                )
                decision = "pending"
                reason = "今日自动通过额度已用完"
            else:
                ok = await self._set_request(client, flag, True)
                if ok:
                    self._counter.record(today)
                    logger.info(f"[{NAME}] 已同意好友申请 {qq}（{reason}）")
                    await self._notify_owner(
                        f"同意了好友申请：{qq}（{describe(info)}，{reason}）"
                        + (f"\n附言：{comment}" if comment else "")
                    )
                    return
                logger.warning(f"[{NAME}] 同意 {qq} 失败，转人工处理")

        if decision == DECISION_REJECT and bool(self._cfg("reject_blacklisted", True)):
            ok = await self._set_request(
                client, flag, False, str(self._cfg("reject_comment", "") or "")
            )
            logger.info(f"[{NAME}] 已拒绝好友申请 {qq}（{reason}）" + ("" if ok else "（拒绝失败）"))
            return

        logger.info(f"[{NAME}] 好友申请 {qq} 保持待处理：{reason}（{describe(info)}）")

    def _evaluate(self, qq: str, info: dict):
        return evaluate(
            qq,
            info=info,
            min_level=int(self._cfg("min_qq_level", 16)),
            accept_vip=bool(self._cfg("accept_vip", True)),
            max_qq_len=int(self._cfg("max_qq_len", 9)),
            whitelist=parse_qq_list(self._cfg("whitelist", "")),
            blacklist=parse_qq_list(self._cfg("blacklist", "")),
        )

    @filter.event_message_type(
        filter.EventMessageType.PRIVATE_MESSAGE, priority=(1 << 31) - 1
    )
    async def on_doubt_friend_request(self, event: AstrMessageEvent):
        """处理 QQ 降级成「可疑好友申请」的请求。

        这类申请没有 OneBot request 事件和 flag，只会以私聊系统消息
        「请求添加你为好友」出现；NapCat 提供了可疑申请列表和专用处理接口，
        但该接口只能同意、不能拒绝，所以黑名单/不达标的只能通知主人手动处理。
        """
        if not self._enabled():
            return
        text = str(event.message_str or "").strip()
        if not is_friend_request_notice(text):
            return
        qq = str(event.get_sender_id() or "").strip()
        if not qq:
            return
        client = self._client(event)
        if client is None:
            return
        try:
            items = await client.call_action("get_doubt_friends_add_request", count=50)
        except Exception as exc:
            logger.info(f"[{NAME}] 读取可疑好友申请失败：{exc}")
            if text in ("请求添加你为好友", "请求加你为好友"):
                event.stop_event()
            return
        item = find_doubt_request(items, qq)
        if not item:
            # 普通 request 事件会走另一个 handler；这句系统原话本身不该进 LLM
            if text in ("请求添加你为好友", "请求加你为好友"):
                event.stop_event()
            return
        # 这是申请系统消息，不能让它进 LLM 闲聊
        event.stop_event()
        flag = str(item.get("flag") or "")
        if not flag:
            logger.warning(f"[{NAME}] 可疑好友申请 {qq} 缺少 flag，无法处理")
            return
        info = await self._stranger_info(client, qq)
        decision, reason = self._evaluate(qq, info)
        today = date.today().isoformat()
        if decision != DECISION_ACCEPT:
            hint = "建议手动拒绝" if decision == DECISION_REJECT else "只能手动在 QQ 里同意"
            logger.info(
                f"[{NAME}] 可疑好友申请 {qq} 保持待处理：{reason}（{describe(info)}）"
            )
            await self._notify_owner(
                f"可疑好友申请：{qq}（{describe(info)}）没有自动通过：{reason}；{hint}"
            )
            return
        if not self._counter.allow(today):
            logger.info(
                f"[{NAME}] 今日自动通过已达上限（{self._counter.limit}），"
                f"可疑申请 {qq} 转人工"
            )
            return
        try:
            await client.call_action(
                "set_doubt_friends_add_request", flag=flag, approve=True
            )
        except Exception as exc:
            logger.warning(f"[{NAME}] 同意可疑好友申请 {qq} 失败：{exc}")
            return
        self._counter.record(today)
        logger.info(f"[{NAME}] 已同意可疑好友申请 {qq}（{reason}）")
        await self._notify_owner(
            f"同意了好友申请：{qq}（{describe(info)}，{reason}）"
        )

    async def _notify_owner(self, text: str) -> None:
        if not bool(self._cfg("notify_owner", True)):
            return
        umo = self._owner_umo()
        if not umo:
            return
        try:
            delivered = await self.context.send_message(
                umo, MessageChain(chain=[Plain(text)])
            )
            if delivered is False:
                logger.info(f"[{NAME}] 通知未送达（QQ 可能未登录）：{umo}")
        except Exception as exc:
            logger.warning(f"[{NAME}] 通知主人失败：{exc}")

    # ---------------- 状态 ----------------
    async def initialize(self) -> None:
        logger.info(
            f"[{NAME}] 已启用，判定线：等级≥{self._cfg('min_qq_level', 16)}、"
            f"会员={'算' if self._cfg('accept_vip', True) else '不算'}、"
            f"老号≤{self._cfg('max_qq_len', 9)}位、每日上限 {self._counter.limit}"
        )
