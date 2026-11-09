"""小黑盒分享阅读：帖子、视频和游戏卡片，能读多少读多少。

小黑盒帖子接口有腾讯验证码，服务端默认只能拿到 QQ 分享卡片里的标题/摘要/
封面；配置登录 Cookie 后可尝试读取完整正文。游戏卡片会补充 Steam 公开信息。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Json
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    HEYBOX_HOSTS,
    build_api_params,
    build_game_materials,
    build_grid,
    build_materials,
    build_summary_prompt,
    clean_html_text,
    extract_card_info,
    find_heybox_urls,
    looks_like_heybox,
    parse_game_id,
    parse_link_id,
    parse_tree_payload,
)

NAME = "astrbot_plugin_heybox_reader"
HINT_MARK = "[小黑盒内容]"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
STEAM_APP = "https://store.steampowered.com/api/appdetails"
STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/"


class HeyboxReader(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config

    # ---------------- 配置 ----------------
    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _cfg(self, key: str, default):
        return self.conf.get(key, default)

    async def _vision_provider(self, umo: str = ""):
        provider_id = str(self._cfg("vision_provider_id", "") or "").strip()
        if provider_id:
            try:
                provider = self.context.get_provider_by_id(provider_id)
                if provider is not None:
                    return provider
            except Exception:
                pass
        try:
            if umo:
                provider = await self.context.get_using_provider_async(umo=umo)
                if provider is not None:
                    return provider
            return await self.context.get_using_provider_async()
        except Exception:
            return None

    async def _chat_provider(self, umo: str = ""):
        try:
            return await self.context.get_using_provider_async(umo=umo)
        except Exception:
            return None

    def _ffmpeg(self) -> str:
        raw = str(self._cfg("ffmpeg", "") or "").strip()
        if raw and Path(raw).is_file():
            return raw
        candidates = [
            Path.home() / ".astrbot_launcher" / "components" / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path.home() / ".astrbot_launcher" / "components" / "ffmpeg" / "bin" / "ffmpeg",
        ]
        for path in candidates:
            if path.is_file():
                return str(path)
        return shutil.which("ffmpeg") or ""

    def _ffprobe(self) -> str:
        raw = str(self._cfg("ffprobe", "") or "").strip()
        if raw and Path(raw).is_file():
            return raw
        ffmpeg = self._ffmpeg()
        if ffmpeg:
            probe = Path(ffmpeg).with_name(Path(ffmpeg).stem.replace("ffmpeg", "ffprobe"))
            if probe.is_file():
                return str(probe)
        return shutil.which("ffprobe") or ""

    # ---------------- 抓取 ----------------
    def _card_info(self, event: AstrMessageEvent) -> dict:
        components = getattr(event.message_obj, "message", None) or []
        merged: dict = {}
        for comp in components:
            if not isinstance(comp, Json):
                continue
            info = extract_card_info(getattr(comp, "data", None))
            for key in ("title", "desc", "video", "url", "link_id", "steam_appid"):
                if info.get(key) and not merged.get(key):
                    merged[key] = info[key]
            for url in info.get("images") or []:
                merged.setdefault("images", [])
                if url not in merged["images"]:
                    merged["images"].append(url)
        return merged

    async def _fetch_tree(self, link_id: str) -> dict:
        if not link_id:
            return {}
        path = "/bbs/app/link/tree"
        params = build_api_params(
            path, link_id, str(self._cfg("heybox_device_id", "") or "")
        )
        cookie = str(self._cfg("heybox_cookie", "") or "").strip()
        headers = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"https://www.xiaoheihe.cn/bbs/post_share?link_id={link_id}",
            "Origin": "https://www.xiaoheihe.cn",
        }
        if cookie:
            headers["Cookie"] = cookie
        url = "https://api.xiaoheihe.cn" + path + "?" + urllib.parse.urlencode(params)
        timeout = aiohttp.ClientTimeout(total=float(self._cfg("request_timeout_seconds", 20)))
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                text = await resp.text(errors="ignore")
        try:
            payload = json.loads(text)
        except Exception:
            return {}
        status = str((payload or {}).get("status") or "")
        if status == "show_captcha":
            logger.info(f"[{NAME}] 小黑盒要求验证码，退回分享卡片内容（link_id={link_id}）")
            return {}
        if status and status != "ok":
            logger.info(f"[{NAME}] 小黑盒接口返回 {status}：{payload.get('msg')}")
            return {}
        info = parse_tree_payload(payload)
        if info:
            info["link_id"] = link_id
        return info

    async def _fetch_steam(self, info: dict) -> dict:
        if not bool(self._cfg("steam_enrich", True)):
            return {}
        appid = str(info.get("steam_appid") or "")
        name = str(info.get("title") or "").strip()
        is_game = bool(appid) or bool(parse_game_id(str(info.get("url") or "")))
        if not is_game and not name:
            return {}
        timeout = aiohttp.ClientTimeout(total=20)
        headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            if not appid and name:
                # 用卡片标题搜 Steam，取第一个结果
                try:
                    async with session.get(
                        STEAM_SEARCH,
                        params={"term": name[:60], "l": "schinese", "cc": "CN"},
                    ) as resp:
                        payload = await resp.json(content_type=None)
                    items = (payload or {}).get("items") or []
                    if items:
                        appid = str(items[0].get("id") or "")
                except Exception as exc:
                    logger.info(f"[{NAME}] Steam 搜索失败：{exc}")
            if not appid:
                return {}
            try:
                async with session.get(
                    STEAM_APP, params={"appids": appid, "l": "schinese", "cc": "CN"}
                ) as resp:
                    payload = await resp.json(content_type=None)
            except Exception as exc:
                logger.info(f"[{NAME}] Steam 详情失败：{exc}")
                return {}
        data = ((payload or {}).get(appid) or {}).get("data") or {}
        if not data:
            return {}
        price = data.get("price_overview") or {}
        return {
            "appid": appid,
            "name": data.get("name") or name,
            "description": clean_html_text(
                data.get("short_description") or data.get("detailed_description") or ""
            ),
            "genres": [
                str(item.get("description") or "")
                for item in data.get("genres") or []
                if isinstance(item, dict)
            ][:4],
            "release_date": (data.get("release_date") or {}).get("date") or "",
            "price": price.get("final_formatted") or ("免费" if data.get("is_free") else ""),
            "developers": data.get("developers") or [],
            "header_image": data.get("header_image") or "",
        }

    # ---------------- 媒体理解 ----------------
    async def _download(self, url: str, dest: Path, max_bytes: int) -> Path:
        timeout = aiohttp.ClientTimeout(total=180)
        headers = {"User-Agent": UA, "Referer": "https://www.xiaoheihe.cn/"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                size = 0
                with open(dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1 << 16):
                        size += len(chunk)
                        if size > max_bytes:
                            raise RuntimeError(f"文件超过 {max_bytes // (1024 * 1024)}MB")
                        f.write(chunk)
        return dest

    async def _describe_images(self, info: dict, workdir: Path, umo: str) -> str:
        provider = await self._vision_provider(umo)
        if provider is None:
            return ""
        limit = max(1, min(9, int(self._cfg("max_images", 6))))
        paths = []
        for index, url in enumerate(info.get("images") or []):
            if len(paths) >= limit:
                break
            try:
                paths.append(
                    str(
                        await self._download(
                            url, workdir / f"img_{index}.jpg", 12 * 1024 * 1024
                        )
                    )
                )
            except Exception as exc:
                logger.info(f"[{NAME}] 图片下载失败（跳过）：{exc}")
        if not paths:
            return ""
        sheet = await asyncio.to_thread(
            build_grid, paths, str(workdir / "sheet.jpg"),
            max(2, min(3, int(self._cfg("grid_cols", 3)))),
        )
        if not sheet:
            return ""
        prompt = (
            "这是小黑盒帖子里的图片（按编号顺序拼在一起）。\n"
            f"标题：{info.get('title') or '未知'}\n"
            f"摘要：{(info.get('desc') or '无')[:400]}\n"
            "请描述图片里有什么：画面内容、人物或物体、图片里的文字、整体氛围。"
            "用中文 3-6 句；只描述看得见的，不要编；不要提“拼图”“截图”“视觉模型”。"
        )
        try:
            result = await asyncio.wait_for(
                provider.text_chat(prompt=prompt, image_urls=[sheet]), timeout=90
            )
        except Exception as exc:
            logger.info(f"[{NAME}] 图片理解失败：{exc}")
            return ""
        return str(getattr(result, "completion_text", "") or "").strip()

    def _video_duration(self, path: Path) -> float:
        probe = self._ffprobe()
        if not probe:
            return 0.0
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return max(0.0, float((out.stdout or "0").strip() or 0))
        except Exception:
            return 0.0

    def _extract_frames(self, video: Path, workdir: Path, duration: float) -> list[str]:
        ffmpeg = self._ffmpeg()
        if not ffmpeg:
            return []
        frames = max(2, min(9, int(self._cfg("frame_count", 9))))
        span = max(1.0, duration or 1.0)
        paths = []
        for index in range(frames):
            at = span * (index + 0.5) / frames
            dest = workdir / f"frame_{index:02d}.jpg"
            try:
                subprocess.run(
                    [ffmpeg, "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(video),
                     "-frames:v", "1", "-vf", "scale=480:-2", str(dest)],
                    capture_output=True, timeout=45,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                continue
            if dest.is_file() and dest.stat().st_size > 0:
                paths.append(str(dest))
        return paths

    def _extract_audio(self, video: Path, workdir: Path) -> str:
        ffmpeg = self._ffmpeg()
        if not ffmpeg:
            return ""
        wav = workdir / "audio.wav"
        seconds = max(10, int(self._cfg("video_inline_seconds", 120)))
        try:
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-i", str(video), "-t", str(seconds),
                 "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(wav)],
                capture_output=True, timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return ""
        return str(wav) if wav.is_file() and wav.stat().st_size > 1000 else ""

    def _asr_python(self) -> str:
        raw = str(self._cfg("asr_python", "") or "").strip()
        if raw:
            return raw
        if getattr(sys, "frozen", False):
            return ""
        return sys.executable

    async def _transcribe(self, wav: str) -> str:
        python = self._asr_python()
        if not python:
            return ""
        worker = Path(__file__).with_name("asr_worker.py")
        cmd = [
            python, str(worker), "--wav", wav,
            "--model", str(self._cfg("asr_model", "small") or "small"),
            "--threads", str(int(self._cfg("asr_threads", 2) or 2)),
            "--compute-type", str(self._cfg("asr_compute_type", "int8") or "int8"),
        ]
        for key, flag in (
            ("asr_language", "--language"),
            ("asr_initial_prompt", "--initial-prompt"),
            ("asr_download_root", "--download-root"),
        ):
            value = str(self._cfg(key, "") or "").strip()
            if value:
                cmd += [flag, value]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=float(self._cfg("asr_timeout_seconds", 300))
            )
        except Exception as exc:
            logger.info(f"[{NAME}] 语音转写失败：{exc}")
            return ""
        segments = []
        for line in (stdout or b"").decode("utf-8", "ignore").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if item.get("type") == "segment" and str(item.get("text") or "").strip():
                segments.append(str(item["text"]).strip())
        return "".join(segments)[:6000]

    async def _describe_video(self, info: dict, workdir: Path, umo: str) -> tuple[str, str]:
        video_url = str(info.get("video") or "").strip()
        if not video_url or not bool(self._cfg("video_enabled", True)):
            return "", ""
        max_mb = max(5, int(self._cfg("video_max_mb", 80)))
        path = workdir / "post.mp4"
        try:
            await self._download(video_url, path, max_mb * 1024 * 1024)
        except Exception as exc:
            logger.info(f"[{NAME}] 视频下载失败：{exc}")
            return "", ""
        duration = await asyncio.to_thread(self._video_duration, path)
        provider = await self._vision_provider(umo)
        visual = ""
        frames = await asyncio.to_thread(self._extract_frames, path, workdir, duration)
        if frames and provider is not None:
            sheet = await asyncio.to_thread(
                build_grid, frames, str(workdir / "video_sheet.jpg"), 3
            )
            if sheet:
                try:
                    result = await asyncio.wait_for(
                        provider.text_chat(
                            prompt=(
                                "这是小黑盒视频按时间顺序抽取的画面（左上到右下）。\n"
                                f"标题：{info.get('title') or '未知'}\n"
                                "请描述视频讲了什么：场景、人物、画面文字、发生的事。"
                                "用中文 4-8 句，只描述看得见的，不要编。"
                            ),
                            image_urls=[sheet],
                        ),
                        timeout=90,
                    )
                    visual = str(getattr(result, "completion_text", "") or "").strip()
                except Exception as exc:
                    logger.info(f"[{NAME}] 视频画面理解失败：{exc}")
        transcript = ""
        if bool(self._cfg("asr_enabled", False)):
            wav = await asyncio.to_thread(self._extract_audio, path, workdir)
            if wav:
                transcript = await self._transcribe(wav)
        return visual, transcript

    async def _summarize(
        self, info: dict, visual: str, transcript: str, question: str, umo: str
    ) -> str:
        provider = await self._chat_provider(umo)
        if provider is None:
            return ""
        try:
            result = await asyncio.wait_for(
                provider.text_chat(
                    prompt=build_summary_prompt(info, visual, transcript, question)
                ),
                timeout=90,
            )
        except Exception as exc:
            logger.info(f"[{NAME}] 总结失败：{exc}")
            return ""
        return str(getattr(result, "completion_text", "") or "").strip()

    # ---------------- 对外能力 ----------------
    @filter.on_llm_request()
    async def hint_heybox_link(self, event: AstrMessageEvent, req):
        if not self._enabled():
            return
        text = str(getattr(event, "message_str", "") or "")
        if not looks_like_heybox(text):
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        if HINT_MARK in prompt:
            return
        req.system_prompt = prompt + (
            "\n\n" + HINT_MARK + " 这条消息包含小黑盒链接或分享卡片。"
            "只要看到小黑盒内容，就先调用 read_heybox 读一遍（对方没提问也调用），"
            "不要只凭标题猜内容，也不要用 analyze_webpage 分析。"
            "读完用你自己的口吻自然回应：说内容讲了什么、你看到/感受到了什么；"
            "如果只拿到分享摘要，就只说摘要里的东西，不要假装读到了全文。"
            "如果对方紧跟着只说「看看这个/看这个」，指的就是上一条，不要再问发了什么。"
        )

    @filter.llm_tool(name="read_heybox")
    async def read_heybox(
        self,
        event: AstrMessageEvent,
        url: str,
        question: str = "",
    ) -> str:
        """读取一个小黑盒分享内容：帖子/视频尽量抓正文和画面，游戏卡片补充 Steam 信息。
        只要用户分享小黑盒链接（xiaoheihe.cn、api.xiaoheihe.cn 分享链接、heybox:// 协议）就调用，
        即使没有明确提问也可以先读；读完再自然地回应。

        Args:
            url(string): 小黑盒链接（分享卡片里的链接、xhslink 形式的小黑盒短链或 heybox:// 协议）
            question(string): 用户关于这个内容的具体问题，可留空
        """
        if not self._enabled():
            return "小黑盒内容阅读未启用。"
        card = self._card_info(event)
        target = str(url or "").strip()
        if not target:
            target = str(card.get("url") or "")
        urls = find_heybox_urls(target) if target else []
        target = urls[0] if urls else target
        if target and not any(host in target.lower() for host in HEYBOX_HOSTS):
            return "这不像小黑盒链接。"
        link_id = parse_link_id(target) or str(card.get("link_id") or "")
        game_id = parse_game_id(target)
        if not target and not card.get("title") and not link_id and not game_id:
            return "没有找到小黑盒内容。"
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        started = time.time()
        workdir = Path(tempfile.mkdtemp(prefix="heybox_reader_"))
        try:
            api_info = await self._fetch_tree(link_id) if link_id else {}
            info = dict(card)
            for key, value in (api_info or {}).items():
                if value:
                    info[key] = value
            info.setdefault("url", target)
            info["link_id"] = link_id
            info["has_video"] = bool(info.get("video"))
            if game_id or card.get("steam_appid"):
                info["is_game"] = True
            steam = await self._fetch_steam(info)
            if steam:
                info["steam"] = steam
                info["is_game"] = True
                if not info.get("title"):
                    info["title"] = steam.get("name") or ""
                if not info.get("images") and steam.get("header_image"):
                    info["images"] = [steam["header_image"]]
            if not info.get("title") and not info.get("desc") and not steam:
                return (
                    "这个小黑盒内容没读出来：接口要求验证码，分享卡片里也没有正文。"
                    "可以在配置里填登录 Cookie 再试，或直接把内容截图发过来。"
                )
            visual = transcript = ""
            if info.get("has_video"):
                visual, transcript = await self._describe_video(info, workdir, umo)
            elif info.get("images"):
                visual = await self._describe_images(info, workdir, umo)
            material = build_game_materials(steam) if steam else build_materials(info)
            if not visual and not transcript:
                return material[:3000] or "只拿到了标题，没有可读的正文。"
            summary = await self._summarize(info, visual, transcript, question, umo)
            logger.info(
                f"[{NAME}] 读完：{info.get('title') or link_id or game_id}"
                f"（{time.time() - started:.1f}s，来源：{'接口' if api_info else '分享卡片'}）"
            )
            return summary or material[:3000]
        except Exception as exc:
            logger.warning(f"[{NAME}] 读取失败：{exc}")
            return f"这个小黑盒内容没读成：{str(exc)[:120]}"
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
