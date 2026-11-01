"""机器人自己的图片/表情包图库。

把聊天里值得留下的图片存到本机目录，之后按情绪或场景再发出来。
存储和清理逻辑在 library.py，本文件只负责 AstrBot 事件、工具和定时任务。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Image, Reply
from astrbot.core.message.message_event_result import MessageChain

from .library import AUTO_SAVE_SKIPPED, ImageLibrary, SaveRateLimiter

NAME = "astrbot_plugin_snow_imagebox"
DEFAULT_LIBRARY = "~/Documents/BotMemory/表情包"
PROMPT_MARK = "[图库]"
PRIVACY_WORDS = (
    "身份证", "证件", "护照", "银行卡", "密码", "验证码",
    "聊天记录", "截图", "隐私", "住址", "家庭地址", "手机号", "电话号码",
)
EXPLICIT_SAVE_WORDS = (
    "记住", "收藏", "存下", "保存", "存进", "存到", "收进",
    "以后用", "留着", "记下来", "存起来",
)


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class SnowImageBox(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._lib: ImageLibrary | None = None
        self._lib_root = ""
        self._limiter: SaveRateLimiter | None = None
        self._limiter_root = ""
        self._cleanup_task: asyncio.Task | None = None

    # ---------------- 基础 ----------------
    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _library(self) -> ImageLibrary:
        raw = str(self.conf.get("library_path") or DEFAULT_LIBRARY).strip()
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            path = Path.home() / "Documents" / "BotMemory" / path
        root = str(path.resolve())
        if self._lib is None or self._lib_root != root:
            self._lib = ImageLibrary(
                root,
                max_items=_to_int(self.conf.get("max_items"), 300),
                retention_days=_to_int(self.conf.get("retention_days"), 180),
                min_uses=_to_int(self.conf.get("min_uses"), 2),
                max_file_mb=_to_int(self.conf.get("max_file_mb"), 8),
                max_total_mb=_to_int(self.conf.get("max_total_mb"), 500),
            )
            self._lib_root = root
        return self._lib

    def _auto_limiter(self) -> SaveRateLimiter:
        root = str(self._library().root)
        if self._limiter is None or self._limiter_root != root:
            self._limiter = SaveRateLimiter(
                root,
                min_interval_minutes=max(
                    0, _to_int(self.conf.get("auto_save_min_interval_minutes"), 30)
                ),
                max_per_day=max(1, _to_int(self.conf.get("auto_save_max_per_day"), 10)),
            )
            self._limiter_root = root
        return self._limiter

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        owner = str(self.conf.get("owner_session") or "").strip()
        return bool((owner and event.unified_msg_origin == owner) or event.is_admin())

    @staticmethod
    def _explicit_save_request(event: AstrMessageEvent) -> bool:
        text = str(getattr(event, "message_str", "") or "")
        return any(word in text for word in EXPLICIT_SAVE_WORDS)

    def _can_save(self, event: AstrMessageEvent) -> bool:
        return self._is_owner(event) or bool(self.conf.get("allow_member_save", False))

    @staticmethod
    def _deny() -> str:
        return "只有所有者或管理员能让机器人收藏或删除图库里的图片。用你的口吻轻轻拒绝，不要提工具或路径。"

    @staticmethod
    def _has_images(event: AstrMessageEvent) -> bool:
        for comp in event.message_obj.message:
            if isinstance(comp, Image):
                return True
            if isinstance(comp, Reply):
                for sub in comp.chain or []:
                    if isinstance(sub, Image):
                        return True
        return False

    async def _image_paths(self, event: AstrMessageEvent) -> list[str]:
        """收集当前消息和引用消息里的图片，最多 4 张。"""
        images: list[Image] = []
        for comp in event.message_obj.message:
            if isinstance(comp, Image):
                images.append(comp)
            elif isinstance(comp, Reply):
                for sub in comp.chain or []:
                    if isinstance(sub, Image):
                        images.append(sub)
        paths: list[str] = []
        seen: set[str] = set()
        for image in images[:4]:
            try:
                path = await image.convert_to_file_path()
            except Exception as exc:
                logger.warning(f"[{NAME}] 读取图片失败: {exc}")
                continue
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
        return paths

    async def _send_image(self, event: AstrMessageEvent, path: Path) -> None:
        image = Image.fromFileSystem(str(path))
        chain = MessageChain([image])
        if event.get_platform_name() in {"gewechat", "webchat"}:
            await event.send(chain)
        else:
            await self.context.send_message(event.unified_msg_origin, chain)

    # ---------------- 生命周期 ----------------
    async def initialize(self) -> None:
        if not self._enabled():
            return
        try:
            self._library()
        except Exception as exc:
            logger.error(f"[{NAME}] 初始化图库失败: {exc}")
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def terminate(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        await asyncio.sleep(10)
        while True:
            try:
                summary = await asyncio.to_thread(self._library().cleanup)
                if summary.get("removed"):
                    logger.info(
                        f"[{NAME}] 自动清理 {summary['removed']} 张低频/过期图片，"
                        f"剩余 {summary['kept']} 张"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[{NAME}] 自动清理失败: {exc}")
            hours = max(1, _to_int(self.conf.get("cleanup_interval_hours"), 6))
            await asyncio.sleep(hours * 3600)

    # ---------------- 提示词 ----------------
    @filter.on_llm_request()
    async def inject_library_prompt(self, event: AstrMessageEvent, req):
        if not self._enabled() or not bool(self.conf.get("prompt_enabled", True)):
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        if PROMPT_MARK in prompt:
            return
        has_image = self._has_images(event)
        try:
            has_items = bool(self._library().items())
        except Exception:
            has_items = False
        if not has_image and not has_items:
            return
        lines = [
            PROMPT_MARK,
            "你有一个自己的图片/表情包图库，可以保存聊天里的图，之后在合适的时机再发出来。",
            "- 你可以自己判断要不要收藏：画面情绪或梗明确、以后聊天可能复用、且不是隐私内容时，"
            "才调用 save_image_to_library，automatic 填 true，description 写画面和情绪，"
            "tags 写 2-5 个短标签。不要每张图都存，同一情绪/画面已经有的不要重复存。",
            "- 用户明确说“记住/收藏/存下来/以后用”时，调用 save_image_to_library，"
            "automatic 填 false；这种情况不受自动收藏频率限制。",
            "- 自动收藏有频率限制。工具说“这次不收藏”就自然跳过，不要反复调用，"
            "也不要向用户解释限制或工具。",
            "- 想发表情包时，调用 list_saved_images 或用 send_saved_image 按情绪/场景搜索并发送；"
            "图库里没有合适的图就不要硬发，也不要说图库里有实际不存在的图。",
            "- 不保存隐私、证件、聊天记录截图、敏感内容；只为聊天表达服务，不主动收集别人的私密图片。",
        ]
        if has_image:
            lines.append("- 这条消息里带有图片；可以按上面的规则判断是否值得收藏。")
        lines.append(
            "- 调用工具拿到结果后，基于结果继续往下聊；"
            "不要原样重复工具调用前已经说过的话。"
        )
        if has_image and bool(self.conf.get("auto_save_owner_only", True)) and not self._is_owner(event):
            lines.append(
                "- 这个会话不是所有者，你自己不要主动收藏这里的图片；"
                "只有所有者明确让你保存时才调用保存工具。"
            )
        req.system_prompt = prompt + "\n\n" + "\n".join(lines)

    # ---------------- 工具 ----------------
    @filter.llm_tool(name="save_image_to_library")
    async def save_image_to_library(
        self,
        event: AstrMessageEvent,
        description: str,
        tags: str = "",
        source_note: str = "",
        automatic: bool = False,
    ) -> str:
        """把当前消息或引用消息里的图片保存进机器人自己的图库，供以后聊天使用。
        用户明确说“记住这张图”“收藏这个表情包”“存下来以后用”时调用，automatic 填 false。
        你也可以自己判断：画面情绪/梗明确、以后可能复用时调用，automatic 填 true。
        不要保存隐私、证件、聊天记录截图和敏感内容。

        Args:
            description(string): 画面内容、人物动作、文字和情绪，用一两句话描述，方便以后搜索
            tags(string): 2-5 个短标签，用逗号分隔，例如“生气,无语,表情包”
            source_note(string): 可选的来源备注，例如“所有者发的表情包”
            automatic(boolean): 你自己判断要收藏时填 true；用户明确要求保存时填 false
        """
        if not self._enabled():
            return "图库功能未启用。"
        explicit_request = self._explicit_save_request(event)
        if explicit_request:
            automatic = False
        elif not automatic:
            automatic = True
        if not self._can_save(event):
            if automatic:
                # 自发收藏碰到权限限制时静默跳过；“用你的口吻拒绝”这类话术
                # 只适用于用户明确要求的场景，否则模型会复读已经发过的内容。
                return AUTO_SAVE_SKIPPED
            return self._deny()
        if automatic:
            if not bool(self.conf.get("auto_save_enabled", True)):
                return "这次不自动收藏。不要向用户解释限制，也不要重试。"
            if not event.is_private_chat() and not bool(
                self.conf.get("auto_save_in_groups", False)
            ):
                return "群聊里这次不自动收藏。不要向用户解释限制，也不要重试。"
            if bool(self.conf.get("auto_save_owner_only", True)) and not self._is_owner(event):
                return "这次不自动收藏。不要向用户解释限制，也不要重试。"
            probe = f"{description} {tags} {getattr(event, 'message_str', '') or ''}"
            if any(word in probe for word in PRIVACY_WORDS):
                return "这张图可能涉及隐私，这次不自动收藏。不要向用户解释限制。"
            allowed, why = self._auto_limiter().allow()
            if not allowed:
                return f"这次不自动收藏：{why}。不要向用户解释限制，也不要重试。"
            probability = max(
                0, min(100, _to_int(self.conf.get("auto_save_probability"), 100))
            )
            if probability < 100 and random.random() * 100 >= probability:
                return "这次先不自动收藏。不要向用户解释限制，也不要重试。"

        paths = await self._image_paths(event)
        if not paths:
            return "这条消息里没有可以保存的图片。"
        limit = max(1, min(4, _to_int(self.conf.get("max_save_per_call"), 3)))
        saved: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        errors: list[str] = []
        source = "auto" if automatic else "chat"
        tag_text = tags
        if automatic and not str(tag_text or "").strip():
            tag_text = "自动收藏"
        note = str(source_note or "").strip()
        if automatic and not note:
            note = "自动收藏"
        lib = self._library()
        for path in paths[:limit]:
            try:
                item, status = await asyncio.to_thread(
                    lib.add_file,
                    path,
                    description,
                    tag_text,
                    source=source,
                )
            except Exception as exc:
                errors.append(str(exc))
                continue
            payload = {
                "id": item.get("id"),
                "description": item.get("description"),
                "tags": list(item.get("tags") or []),
            }
            (duplicates if status == "duplicate" else saved).append(payload)
        if automatic and saved:
            self._auto_limiter().record()
        return json.dumps(
            {
                "ok": bool(saved or duplicates),
                "automatic": bool(automatic),
                "saved": saved,
                "already_in_library": duplicates,
                "errors": errors,
                "note": "以后可以用 send_saved_image 按描述或标签发出来。",
                "source_note": note[:120],
            },
            ensure_ascii=False,
        )

    @filter.llm_tool(name="send_saved_image")
    async def send_saved_image(
        self,
        event: AstrMessageEvent,
        query: str = "",
        image_id: str = "",
    ) -> str:
        """从图库里挑一张图片/表情包发到当前聊天。
        按情绪、场景或画面描述搜索，例如“生气”“无语”“摸摸头”“开心”。
        图库里没有合适的图就不要发，也不要说图库里有不存在的图。

        Args:
            query(string): 情绪、场景或画面关键词，留空则随机发一张
            image_id(string): 已知图片 ID 时直接指定；通常留空用 query 搜索
        """
        if not self._enabled():
            return "图库功能未启用。"
        lib = self._library()
        if str(image_id or "").strip():
            item = lib.get(image_id)
            if not item:
                return "图库里没有这个 ID，不要硬发。"
        else:
            item = lib.pick(query)
        if not item:
            return "图库里没有找到匹配的图片。不要硬发，也不要说图库里存在这张图。"
        path = lib.file_path(item)
        if not path.is_file():
            lib.delete(str(item.get("id") or ""))
            return "这张图库图片的文件已经丢失，已从索引里移除。"
        try:
            await self._send_image(event, path)
        except Exception as exc:
            logger.error(f"[{NAME}] 发送图库图片失败: {exc}")
            return f"发送图库图片失败：{exc}"
        lib.record_use(str(item.get("id") or ""))
        return (
            f"已发送图库图片 id={item.get('id')}，"
            f"描述：{item.get('description')}，标签：{','.join(item.get('tags') or [])}"
        )

    @filter.llm_tool(name="list_saved_images")
    async def list_saved_images(
        self,
        event: AstrMessageEvent,
        query: str = "",
        limit: int = 10,
    ) -> str:
        """查看图库里有哪些图片/表情包，用来决定发哪一张。
        只返回编号、描述、标签和使用次数，不返回本机路径。

        Args:
            query(string): 可选的情绪/场景关键词；留空列出最近和常用的图
            limit(number): 最多返回多少条，1-30，默认 10
        """
        if not self._enabled():
            return "图库功能未启用。"
        items = self._library().search(query, limit=limit)
        return json.dumps(
            {"count": len(items), "items": items},
            ensure_ascii=False,
        )

    @filter.llm_tool(name="delete_saved_image")
    async def delete_saved_image(
        self,
        event: AstrMessageEvent,
        image_id: str,
    ) -> str:
        """从图库里删除一张图片，仅所有者/管理员可用。用于删掉误存、重复或不想保留的图。

        Args:
            image_id(string): 要删除的图片 ID，可从 list_saved_images 获取
        """
        if not self._enabled():
            return "图库功能未启用。"
        if not self._is_owner(event):
            return self._deny()
        image_id = str(image_id or "").strip()
        if not image_id:
            return "请提供要删除的图片 ID。"
        ok = self._library().delete(image_id)
        return "已删除。" if ok else "图库里没有这个 ID。"

    @filter.llm_tool(name="clean_image_library")
    async def clean_image_library(self, event: AstrMessageEvent) -> str:
        """立刻清理图库里的低频和远古图片，仅所有者/管理员可用。
        正常情况会自动定时清理；用户明确说“清理图库”时再调用。
        """
        if not self._enabled():
            return "图库功能未启用。"
        if not self._is_owner(event):
            return self._deny()
        summary = await asyncio.to_thread(self._library().cleanup)
        return json.dumps(summary, ensure_ascii=False)

    @filter.llm_tool(name="image_library_stats")
    async def image_library_stats(self, event: AstrMessageEvent) -> str:
        """查看图库统计：图片数量、占用空间、使用情况、清理上限，仅所有者/管理员可用。"""
        if not self._enabled():
            return "图库功能未启用。"
        if not self._is_owner(event):
            return self._deny()
        stats = self._library().stats()
        stats["auto_save"] = {
            "enabled": bool(self.conf.get("auto_save_enabled", True)),
            "probability": max(
                0, min(100, _to_int(self.conf.get("auto_save_probability"), 100))
            ),
            **self._auto_limiter().status(),
        }
        return json.dumps(stats, ensure_ascii=False)
