"""发文件：把她自己文件夹里的文章/图片发到当前会话。

只允许配置目录（默认插件数据目录 share/，线上可指向她的「写作」文件夹）；
路径必须落在目录内；文件名/路径含隐私关键词、文本内容命中账号或密钥特征的
文件一律拒绝，避免把画像、日记、配置或账号相关文件发出去。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    DEFAULT_DENY_KEYWORDS,
    DEFAULT_EXTS,
    ext_allowed,
    format_file_list,
    is_within,
    list_files,
    name_is_denied,
    parse_exts,
    parse_roots,
    safe_file_in_roots,
    scan_text_file,
)

NAME = "astrbot_plugin_snow_files"
HINT_MARK = "[我的文件]"

_SEND_HINT_RE = re.compile(r"(发我|发给我|发一下|文件|论文|你写的|写的东西|看看你写|分享一下)")
_MAX_HINT_FILES = 8


class SnowFiles(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._send_times: list[float] = []

    # ---------------- 配置 ----------------
    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _cfg(self, key: str, default):
        return self.conf.get(key, default)

    def _data_dir(self) -> Path:
        try:
            return Path(str(StarTools.get_data_dir(NAME)))
        except Exception:
            path = Path("data") / "plugin_data" / NAME
            path.mkdir(parents=True, exist_ok=True)
            return path

    def _roots(self) -> list[Path]:
        raw = str(self._cfg("allow_dirs", "") or "").strip()
        roots = parse_roots(raw) if raw else [self._data_dir() / "share"]
        result = []
        for root in roots:
            try:
                root.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            if root.is_dir():
                result.append(root)
        return result

    def _exts(self) -> set[str]:
        return parse_exts(str(self._cfg("allowed_ext", DEFAULT_EXTS) or DEFAULT_EXTS))

    def _keywords(self) -> tuple[str, ...]:
        raw = str(self._cfg("deny_keywords", "") or "").strip()
        if not raw:
            return DEFAULT_DENY_KEYWORDS
        items = tuple(
            item.strip()
            for item in re.split(r"[,，\r\n]+", raw)
            if item.strip()
        )
        return items or DEFAULT_DENY_KEYWORDS

    def _known_ids(self, event: AstrMessageEvent) -> set[str]:
        ids = {str(getattr(event, "get_self_id", lambda: "")() or "")}
        try:
            for admin in self.context.get_config().get("admins_id") or []:
                ids.add(str(admin))
        except Exception:
            pass
        return {item for item in ids if item.strip()}

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        sender = str(getattr(event, "get_sender_id", lambda: "")() or "")
        try:
            admins = {str(item) for item in self.context.get_config().get("admins_id") or []}
        except Exception:
            admins = set()
        return bool(sender) and sender in admins

    # ---------------- 校验 ----------------
    def _validate(self, path: Path, roots: list[Path], event: AstrMessageEvent) -> str:
        if not path.is_file():
            return "这不是一个文件"
        if not any(is_within(path, root) for root in roots):
            return "这个文件不在允许发送的目录里"
        if not ext_allowed(path, self._exts()):
            return "这种文件类型不允许发送"
        relative = next(
            (path.relative_to(root).as_posix() for root in roots if is_within(path, root)),
            path.name,
        )
        if name_is_denied(relative, self._keywords()):
            return "文件名或目录涉及隐私，不能发送"
        max_mb = max(1, int(self._cfg("max_mb", 20)))
        try:
            size = path.stat().st_size
        except OSError:
            return "读不到文件大小"
        if size > max_mb * 1024 * 1024:
            return f"文件超过 {max_mb}MB，不能发送"
        if bool(self._cfg("scan_text", True)):
            reason = scan_text_file(path, self._known_ids(event))
            if reason:
                return reason
        return ""

    def _rate_limited(self) -> bool:
        now = time.time()
        limit = max(1, int(self._cfg("max_per_hour", 3)))
        self._send_times = [ts for ts in self._send_times if now - ts < 3600]
        if len(self._send_times) >= limit:
            return True
        self._send_times.append(now)
        return False

    def _audit(self, event: AstrMessageEvent, path: Path, ok: bool, reason: str) -> None:
        try:
            record = {
                "ts": time.time(),
                "umo": str(getattr(event, "unified_msg_origin", "") or ""),
                "sender": str(getattr(event, "get_sender_id", lambda: "")() or ""),
                "file": str(path),
                "ok": ok,
                "reason": reason,
            }
            with open(self._data_dir() / "send_audit.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ---------------- 发送 ----------------
    async def _send(self, event: AstrMessageEvent, path: Path) -> str:
        umo = str(event.unified_msg_origin or "")
        bot = getattr(event, "bot", None)
        try:
            if ":GroupMessage:" in umo:
                group_id = str(getattr(event, "get_group_id", lambda: "")() or "")
                if not group_id:
                    return "拿不到群号，发不了"
                await bot.call_action(
                    "upload_group_file",
                    group_id=int(group_id),
                    file=str(path),
                    name=path.name,
                )
            else:
                user_id = str(getattr(event, "get_sender_id", lambda: "")() or "")
                if not user_id:
                    return "拿不到对方号码，发不了"
                await bot.call_action(
                    "upload_private_file",
                    user_id=int(user_id),
                    file=str(path),
                    name=path.name,
                )
            return ""
        except Exception as exc:
            logger.warning(f"[{NAME}] OneBot 发文件失败，尝试消息链：{exc}")
        try:
            sent = await self.context.send_message(
                umo,
                MessageChain(chain=[File(name=path.name, file=str(path))]),
            )
            return "" if sent else "文件没发出去"
        except Exception as exc:
            logger.warning(f"[{NAME}] 消息链发文件失败：{exc}")
            return f"发送失败：{str(exc)[:100]}"

    # ---------------- 工具 ----------------
    @filter.llm_tool(name="list_my_files")
    async def list_my_files(self, event: AstrMessageEvent, query: str = "") -> str:
        """列出她自己文件夹里可以发送的文件（文章、图片等）。

        当对方问“你写了什么/有什么文件”时调用；只列出允许发送的目录，已过滤隐私文件。

        Args:
            query(string): 可选，按文件名/目录关键词过滤
        """
        if not self._enabled():
            return "发文件功能未启用。"
        rows = list_files(
            self._roots(),
            self._exts(),
            self._keywords(),
            query=query,
            limit=int(self._cfg("list_limit", 50)),
        )
        return format_file_list(rows, limit=20)

    @filter.llm_tool(name="send_my_file")
    async def send_my_file(self, event: AstrMessageEvent, name: str) -> str:
        """把她自己文件夹里的文件发到当前会话。

        当对方说“把你写的论文发我/发我看看/把那个文件发过来”时调用。
        只能发配置目录里的文件；隐私文件、配置、画像、日记、含账号或密钥的文件会被拒绝。

        Args:
            name(string): 文件相对路径或文件名（例如「2026-11-10 人工智能与科研.md」）
        """
        if not self._enabled():
            return "发文件功能未启用。"
        roots = self._roots()
        path, error = safe_file_in_roots(name, roots)
        if path is None:
            return error
        reason = self._validate(path, roots, event)
        if reason:
            self._audit(event, path, False, reason)
            return f"这个文件不能发：{reason}"
        if self._rate_limited():
            self._audit(event, path, False, "rate_limited")
            return "今天发得有点多了，晚点再发吧"
        error = await self._send(event, path)
        self._audit(event, path, not error, error or "sent")
        if error:
            return error
        logger.info(f"[{NAME}] 已发送文件：{path.name}")
        return f"已发送「{path.name}」。不要再说“这就发”，直接告诉对方发了什么就行。"

    # ---------------- 提示 ----------------
    @filter.on_llm_request()
    async def hint_files(self, event: AstrMessageEvent, req):
        if not self._enabled() or not self._is_admin(event):
            return
        text = str(getattr(event, "message_str", "") or "")
        if not _SEND_HINT_RE.search(text):
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        if HINT_MARK in prompt:
            return
        rows = list_files(
            self._roots(),
            self._exts(),
            self._keywords(),
            limit=_MAX_HINT_FILES,
        )
        if not rows:
            return
        names = "、".join(row["name"] for row in rows)
        req.system_prompt = prompt + (
            f"\n\n{HINT_MARK} 你文件夹里现在有这些可以发的文件：{names}。"
            "如果对方要你发文件，先调用 send_my_file 真正发出去，再自然回应；"
            "不要只说“我发你”却什么都不做。只发对方要的那个，别一次发一堆。"
        )
