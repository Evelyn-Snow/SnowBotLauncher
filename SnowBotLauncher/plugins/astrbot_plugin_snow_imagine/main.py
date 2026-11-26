"""小雪的生活画面：按场景生成二次元生活插画并发到聊天。

不是“角色海报生成器”：画面可以只拍桌面/书/食物/画纸，她可以只露手/背影，
也可以抓拍、动态模糊、跑出画面，或者和背景人群一起出现。只有明确要“看看你”
时才用正面半身构图。

角色一致性靠 character_ref.png + character.json 的固定锚点；场景先脱敏再送外部
图像服务，失败时不发送、也不让模型承诺“等会儿给你看”。
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Image
from astrbot.core.message.message_event_result import MessageChain

from .library import (
    COMPOSITION_LABELS,
    build_prompt,
    choose_composition,
    sanitize_scene,
)

NAME = "astrbot_plugin_snow_imagine"
HINT_MARK = "[生活画面]"


class SnowImagine(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._state: dict = {}
        self._spec: dict | None = None

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

    def _state_path(self) -> Path:
        return self._data_dir() / "state.json"

    def _load_state(self) -> dict:
        if self._state:
            return self._state
        try:
            self._state = json.loads(self._state_path().read_text(encoding="utf-8"))
            if not isinstance(self._state, dict):
                self._state = {}
        except Exception:
            self._state = {}
        return self._state

    def _save_state(self) -> None:
        path = self._state_path()
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except Exception as exc:
            logger.warning(f"[{NAME}] 状态保存失败：{exc}")

    def _character_spec(self) -> dict:
        if self._spec is not None:
            return self._spec
        path = Path(str(self._cfg("character_spec", "") or ""))
        try:
            self._spec = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(self._spec, dict):
                self._spec = {}
        except Exception:
            self._spec = {}
        return self._spec

    # ---------------- 权限 / 配额 ----------------
    def _is_owner(self, event: AstrMessageEvent) -> bool:
        try:
            if event.role == "admin":
                return True
        except Exception:
            pass
        sender = str(getattr(event, "get_sender_id", lambda: "")() or "")
        try:
            admins = {str(item) for item in self.context.get_config().get("admins_id") or []}
        except Exception:
            admins = set()
        return bool(sender and sender in admins)

    def _check_audience(self, event: AstrMessageEvent) -> tuple[bool, str]:
        if bool(self._cfg("owner_only", True)) and not self._is_owner(event):
            return False, "生活画面目前只对主人开放。"
        if not event.is_private_chat():
            if not bool(self._cfg("allow_groups", False)):
                return False, "群聊里暂时不发生活画面。"
            if not bool(getattr(event, "is_at_or_wake_command", False)):
                return False, "群里没被点名时不要主动发图。"
        return True, ""

    def _check_quota(self) -> tuple[bool, str]:
        state = self._load_state()
        today = time.strftime("%Y-%m-%d")
        if state.get("date") != today:
            state["date"] = today
            state["count"] = 0
        count = int(state.get("count") or 0)
        max_per_day = max(1, int(self._cfg("max_per_day", 2) or 2))
        if count >= max_per_day:
            return False, f"今天已经发过 {count} 张生活画面了，明天再拍。"
        try:
            cooldown_minutes = int(self._cfg("cooldown_minutes", 30))
        except (TypeError, ValueError):
            cooldown_minutes = 30
        cooldown = max(0, cooldown_minutes) * 60
        last_ts = float(state.get("last_ts") or 0)
        if last_ts and time.time() - last_ts < cooldown:
            return False, "刚发过没多久，等一会儿再拍。"
        return True, ""

    def _mark_sent(self) -> None:
        state = self._load_state()
        state["date"] = time.strftime("%Y-%m-%d")
        state["count"] = int(state.get("count") or 0) + 1
        state["last_ts"] = time.time()
        self._save_state()

    # ---------------- 图像 API ----------------
    def _api_key(self) -> str:
        path = str(self._cfg("api_key_file", "") or "").strip()
        if path:
            try:
                return Path(path).read_text(encoding="utf-8-sig").strip()
            except Exception:
                pass
        return str(os.environ.get("ARK_API_KEY") or "").strip()

    def _reference_data_uri(self) -> str:
        path = Path(str(self._cfg("character_ref", "") or ""))
        try:
            data = path.read_bytes()
            return "data:image/png;base64," + base64.b64encode(data).decode()
        except Exception:
            return ""

    def _output_path(self, composition: str) -> Path:
        root = Path(str(self._cfg("output_dir", "") or "generated"))
        month = time.strftime("%Y-%m")
        name = f"{time.strftime('%Y%m%d_%H%M%S')}_{composition}.png"
        path = root / month / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def _generate(self, prompt: str, composition: str) -> tuple[Path | None, str]:
        key = self._api_key()
        if not key:
            return None, "图像服务没有配置好（缺少 ARK API Key）。"
        body = {
            "model": str(self._cfg("model", "doubao-seedream-5-0-pro-260628")),
            "prompt": prompt,
            "size": str(self._cfg("size", "2k") or "2k"),
            "response_format": "url",
            "watermark": bool(self._cfg("watermark", False)),
        }
        if composition != "scene":
            ref = self._reference_data_uri()
            if ref:
                body["image"] = [ref]
        request = urllib.request.Request(
            str(self._cfg("base_url", "https://ark.cn-beijing.volces.com/api/v3")).rstrip("/")
            + "/images/generations",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=int(self._cfg("timeout_seconds", 240) or 240)
            ) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            logger.warning(f"[{NAME}] 图像 API HTTP {exc.code}: {detail}")
            return None, f"图像服务返回 {exc.code}，这次没拍成。"
        except Exception as exc:
            logger.warning(f"[{NAME}] 图像 API 失败：{exc}")
            return None, "图像服务连接失败，这次没拍成。"

        item = (data.get("data") or [{}])[0] if isinstance(data, dict) else {}
        url = str(item.get("url") or "")
        raw_b64 = str(item.get("b64_json") or "")
        out = self._output_path(composition)
        try:
            if url:
                with urllib.request.urlopen(url, timeout=120) as response:
                    raw = response.read()
            elif raw_b64:
                raw = base64.b64decode(raw_b64)
            else:
                return None, "图像服务没有返回图片。"
            out.write_bytes(raw)
        except Exception as exc:
            logger.warning(f"[{NAME}] 图片保存失败：{exc}")
            return None, "图片下载失败，这次没拍成。"
        meta = {
            "prompt": prompt,
            "composition": composition,
            "model": body["model"],
            "size": body["size"],
            "created_at": time.time(),
            "used_reference": bool(body.get("image")),
        }
        try:
            out.with_suffix(".json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
        return out, ""

    async def _send_image(self, event: AstrMessageEvent, path: Path) -> None:
        chain = MessageChain([Image.fromFileSystem(str(path))])
        if event.get_platform_name() in {"gewechat", "webchat"}:
            await event.send(chain)
        else:
            await self.context.send_message(event.unified_msg_origin, chain)

    # ---------------- LLM 工具 ----------------
    @filter.llm_tool(name="share_life_image")
    async def share_life_image(
        self,
        event: AstrMessageEvent,
        scene: str,
        composition: str = "auto",
        shot: str = "auto",
        expression: str = "auto",
        outfit: str = "auto",
        reason: str = "",
    ) -> str:
        """生成一张“我生活里的画面”并直接发到当前聊天。

        想给TA看自己正在做的事、桌上的东西、刚画的画、吃的饭、校园一角，
        或者想分享一个生活瞬间时调用。不要每句都发，也不要默认发自拍/正脸。
        画面可以是：只拍场景/物件（我不出镜）、只露手/背影/侧脸、抓拍动态模糊、
        跑出画面、和我朋友同学一起但他们在背景虚化；只有TA明确说“看看你/你的脸”
        时才用正面半身。

        Args:
            scene(string): 画面内容，例如“刚画完的速写和散在桌上的铅笔”“食堂热汤面”“图书馆窗边的书”
            composition(string): auto/scene/partial/candid/group/portrait；默认 auto
            shot(string): auto/rule_of_thirds/leading_lines/over_shoulder/pov/closeup/wide/low_angle/high_angle/framed/reflection/backlit/motion_blur/flash/film
            expression(string): auto/smile/sleepy/proud/shy/surprised/pouty/teary/thinking/laughing/worried/focused/soft/embarrassed/deadpan
            outfit(string): auto/daily_campus/library/home_study/snow_night/formal/rainy_day/sport/summer/winter/art/sleepwear
            reason(string): 为什么想分享这个画面，一句话
        """
        if not self._enabled():
            return "生活画面功能未启用。"
        ok, why = self._check_audience(event)
        if not ok:
            return why
        ok, why = self._check_quota()
        if not ok:
            return why
        cleaned = sanitize_scene(scene, int(self._cfg("max_scene_chars", 200) or 200))
        if not cleaned:
            return "这个画面不适合生成，换个日常一点的场景。"
        spec = self._character_spec()
        allow_portrait = bool(self._cfg("allow_portrait", True))
        chosen = choose_composition(
            cleaned,
            composition,
            allow_portrait=allow_portrait,
        )
        prompt = build_prompt(
            cleaned,
            composition=chosen,
            spec=spec,
            allow_other_people=bool(self._cfg("allow_other_people", True)),
            style=str(self._cfg("style", "") or ""),
            shot=shot,
            expression=expression,
            outfit=outfit,
        )
        path, error = await self._generate(prompt, chosen)
        if path is None:
            logger.info(f"[{NAME}] 生成失败（{chosen}）：{error}")
            return f"{error} 不要向TA承诺发图，自然收住就好。"
        try:
            await self._send_image(event, path)
        except Exception as exc:
            logger.warning(f"[{NAME}] 图片发送失败：{exc}")
            return "图生成好了但没发出去；不要承诺重发，先用一句话带过。"
        self._mark_sent()
        logger.info(
            f"[{NAME}] 已发送 {COMPOSITION_LABELS.get(chosen, chosen)}：{path.name}"
        )
        return (
            "画面已经发到当前聊天。用一句自然的话接住，不要描述图片内容，"
            "不要提生成、模型、提示词；不要再说“等会儿给你看”。"
        )

    @filter.on_llm_request()
    async def hint_life_image(self, event: AstrMessageEvent, req):
        if not self._enabled() or not bool(self._cfg("hint_enabled", True)):
            return
        ok, _ = self._check_audience(event)
        if not ok:
            return
        try:
            prompt = str(getattr(req, "system_prompt", "") or "")
        except Exception:
            prompt = ""
        if HINT_MARK in prompt:
            return
        hint = (
            f"{HINT_MARK} 想给TA看生活里的画面时，调用 share_life_image；"
            "构图可以是场景/局部/抓拍/人群，不必每次都出镜或正脸；"
            "取景可用三分法/引导线/过肩/POV/特写/广角/低角度/俯拍/窗框/逆光/动态模糊/直闪/胶片；"
            "表情和服装可以按场景选，不必每张都微笑+日常套；"
            "没生成成功就不要承诺发图；不要每句话都发。"
        )
        req.system_prompt = prompt + "\n\n" + hint

    async def terminate(self) -> None:
        self._save_state()
