"""小红书笔记阅读：分享的图文/视频笔记，她能真的看内容再回话。

QQ 分享的小红书笔记是卡片或短链，模型只看到标题和一句摘要。本插件在消息里
发现笔记链接时提示她调用 read_xiaohongshu：抓取笔记页的标题/正文/标签，
下载图片交给视觉模型描述；视频笔记再抽画面、转写语音，最后用自己的口吻聊。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    XHS_HOSTS,
    build_grid,
    build_summary_prompt,
    find_note_urls,
    note_materials,
    parse_note_html,
)

NAME = "astrbot_plugin_xhs_reader"
HINT_MARK = "[小红书笔记]"
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class XhsReader(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config

    # ---------------- 配置与基础工具 ----------------
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
    async def _fetch_page(self, url: str) -> tuple[str, str]:
        """下载笔记页，返回 (最终地址, HTML)。"""
        timeout = aiohttp.ClientTimeout(total=float(self._cfg("request_timeout_seconds", 30)))
        headers = {
            "User-Agent": UA_MOBILE,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.xiaohongshu.com/",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                final_url = str(resp.url)
                if resp.status != 200:
                    raise RuntimeError(f"笔记页返回 HTTP {resp.status}")
                html = await resp.text(errors="ignore")
        if "404/" in final_url or "error_code=300031" in html:
            raise RuntimeError("笔记打不开（可能已删除、设私密或链接缺少 xsec_token）")
        return final_url, html

    async def _download(self, url: str, dest: Path, max_bytes: int) -> Path:
        timeout = aiohttp.ClientTimeout(total=180)
        headers = {
            "User-Agent": UA_DESKTOP,
            "Referer": "https://www.xiaohongshu.com/",
        }
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

    # ---------------- 图片与视频理解 ----------------
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
                suffix = ".gif" if url.lower().endswith(".gif") else ".jpg"
                paths.append(
                    str(
                        await self._download(
                            url, workdir / f"img_{index}{suffix}", 12 * 1024 * 1024
                        )
                    )
                )
            except Exception as exc:
                logger.info(f"[{NAME}] 图片下载失败（跳过）：{exc}")
        if not paths:
            return ""
        sheet = await asyncio.to_thread(
            build_grid,
            paths,
            str(workdir / "sheet.jpg"),
            max(2, min(3, int(self._cfg("grid_cols", 3)))),
        )
        if not sheet:
            return ""
        prompt = (
            "这是小红书图文笔记里的图片（按编号顺序拼在一起）。\n"
            f"笔记标题：{info.get('title') or '未知'}\n"
            f"正文：{(info.get('desc') or '无')[:500]}\n"
            "请描述图片里有什么：画面内容、人物或物体、图片里的文字，以及整体氛围。\n"
            "用中文，3-6 句；只描述看得见的，看不清的不要编；"
            "不要提“拼图”“截图”“视觉模型”。"
        )
        result = await asyncio.wait_for(
            provider.text_chat(prompt=prompt, image_urls=[sheet]), timeout=90
        )
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
            # 跳过片头片尾，均匀取样
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
            stdout, stderr = await asyncio.wait_for(
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
            if item.get("ok") is False:
                logger.info(f"[{NAME}] ASR 失败：{item.get('error')}")
        return "".join(segments)[:6000]

    async def _describe_video(self, info: dict, workdir: Path, umo: str) -> tuple[str, str]:
        video_url = str(info.get("video") or "").strip()
        if not video_url or not bool(self._cfg("video_enabled", True)):
            return "", ""
        max_mb = max(5, int(self._cfg("video_max_mb", 80)))
        path = workdir / "note.mp4"
        try:
            await self._download(video_url, path, max_mb * 1024 * 1024)
        except Exception as exc:
            logger.info(f"[{NAME}] 视频下载失败：{exc}")
            return "", ""
        duration = await asyncio.to_thread(self._video_duration, path)
        max_seconds = max(10, int(self._cfg("video_max_seconds", 300)))
        if duration and duration > max_seconds:
            logger.info(f"[{NAME}] 笔记视频 {duration:.0f}s 超过上限，仍取前段")
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
                                "这是小红书视频笔记按时间顺序抽取的画面（左上到右下）。\n"
                                f"标题：{info.get('title') or '未知'}\n"
                                f"正文：{(info.get('desc') or '无')[:300]}\n"
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
    async def hint_xhs_link(self, event: AstrMessageEvent, req):
        if not self._enabled():
            return
        text = str(getattr(event, "message_str", "") or "")
        if not find_note_urls(text):
            return
        prompt = str(getattr(req, "system_prompt", "") or "")
        if HINT_MARK in prompt:
            return
        req.system_prompt = prompt + (
            "\n\n" + HINT_MARK + " 这条消息包含小红书笔记链接（可能在分享卡片里）。"
            "只要看到小红书链接，就先调用 read_xiaohongshu 读一遍（对方没提问也调用），"
            "不要只凭标题猜内容，也不要用 analyze_webpage 分析小红书页面。"
            "读完用你自己的口吻自然回应：说笔记讲了什么、你看到/感受到了什么；"
            "不要罗列原文，不要提工具。"
            "如果对方紧跟着只说「看看这个/看这个」，指的就是上一条笔记，不要再问发了什么。"
        )

    @filter.llm_tool(name="read_xiaohongshu")
    async def read_xiaohongshu(
        self,
        event: AstrMessageEvent,
        url: str,
        question: str = "",
    ) -> str:
        """读取一个小红书笔记（图文或视频）：抓正文，看图片；视频笔记还会抽画面并转写语音。
        只要用户分享小红书链接（xiaohongshu.com/explore/...、/discovery/item/... 或 xhslink.com 短链）就调用，
        即使没有明确提问也可以先读；读完再自然地回应。

        Args:
            url(string): 小红书笔记链接
            question(string): 用户关于这个笔记的具体问题，可留空
        """
        if not self._enabled():
            return "小红书笔记阅读未启用。"
        urls = find_note_urls(url)
        target = urls[0] if urls else str(url or "").strip()
        if not any(host in target.lower() for host in XHS_HOSTS):
            return "这不像小红书笔记链接。"
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        started = time.time()
        workdir = Path(tempfile.mkdtemp(prefix="xhs_reader_"))
        try:
            final_url, html = await self._fetch_page(target)
            info = parse_note_html(html)
            if not info:
                return (
                    "这个小红书笔记读不出内容：可能已删除、设了私密，"
                    "或者分享链接缺少访问参数（需要在 App 里用「分享」复制完整链接）。"
                )
            info.setdefault("url", final_url)
            logger.info(
                f"[{NAME}] 读到笔记：{info.get('title') or info.get('note_id') or final_url}"
            )
            visual = transcript = ""
            if info.get("has_video"):
                visual, transcript = await self._describe_video(info, workdir, umo)
            else:
                visual = await self._describe_images(info, workdir, umo)
            material = note_materials(info)
            if not visual and not transcript:
                # 没有视觉/语音材料时，把正文直接交给模型，别让她空口猜
                return material[:3000] or "笔记只有标题，没有正文。"
            summary = await self._summarize(info, visual, transcript, question, umo)
            if not summary:
                return material[:3000]
            logger.info(
                f"[{NAME}] 笔记读完：{info.get('title') or final_url}"
                f"（{time.time() - started:.1f}s）"
            )
            return summary
        except Exception as exc:
            logger.warning(f"[{NAME}] 读取失败：{exc}")
            return f"这个小红书笔记没读成：{str(exc)[:120]}"
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
