"""小雪看视频/听语音：把群里的视频文件和语音消息变成她能读的文字。

- 语音（Record）：本地 faster-whisper 转写，替换成「（语音消息）…」再进模型
- 视频（Video / 视频文件）：ffmpeg 抽 9 帧拼图 → 视觉模型描述；同时抽音频转写
- 群聊默认只处理 @/引用她的消息；私聊全部处理
- 只做短中视频：超过上限只取前段音频，避免一条消息卡太久
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, File, Plain, Record, Reply, Video
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import (
    build_sheet,
    extract_audio,
    extract_frames,
    is_audio_name,
    is_video_name,
    probe_duration,
    sheet_rows,
    video_block,
    voice_block,
)

NAME = "astrbot_plugin_snow_media"


class SnowMedia(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._asr_lock = asyncio.Semaphore(1)

    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _ffmpeg(self) -> str:
        raw = str(self.conf.get("ffmpeg") or "").strip()
        if raw and os.path.isfile(raw):
            return raw
        found = shutil.which("ffmpeg")
        if found:
            return found
        bundled = str(
            Path.home()
            / ".astrbot_launcher"
            / "components"
            / "ffmpeg"
            / "bin"
            / "ffmpeg.exe"
        )
        return bundled if os.path.isfile(bundled) else ""

    def _ffprobe(self) -> str:
        raw = str(self.conf.get("ffprobe") or "").strip()
        if raw and os.path.isfile(raw):
            return raw
        ffmpeg = self._ffmpeg()
        if ffmpeg:
            candidate = str(Path(ffmpeg).with_name("ffprobe.exe"))
            if os.path.isfile(candidate):
                return candidate
        return shutil.which("ffprobe") or ""

    def _asr_python(self) -> str:
        raw = str(self.conf.get("asr_python") or "").strip()
        if raw:
            return raw
        if getattr(sys, "frozen", False):
            return ""
        return sys.executable

    def _vision_provider(self):
        pid = str(self.conf.get("vision_provider_id") or "").strip()
        if pid:
            try:
                provider = self.context.get_provider_by_id(pid)
                if provider is not None:
                    return provider
            except Exception:
                pass
        try:
            return self.context.get_using_provider()
        except Exception:
            return None

    @staticmethod
    def _addressed(event: AstrMessageEvent) -> bool:
        if event.is_private_chat():
            return True
        if bool(getattr(event, "is_at_or_wake_command", False)):
            return True
        self_id = str(event.get_self_id() or "")
        for comp in getattr(event.message_obj, "message", None) or []:
            if isinstance(comp, At) and str(getattr(comp, "qq", "")) == self_id:
                return True
            if isinstance(comp, Reply) and str(getattr(comp, "sender_id", "")) == self_id:
                return True
        return False

    def _mode_ok(self, event: AstrMessageEvent, kind: str) -> bool:
        if event.is_private_chat():
            return True
        mode = str(self.conf.get(f"{kind}_group_mode") or "addressed").lower()
        if mode == "off":
            return False
        if mode == "all":
            return True
        return self._addressed(event)

    async def _transcribe(self, wav: str, timeout: int) -> str:
        py = self._asr_python()
        if not py:
            raise RuntimeError("未配置 ASR Python（asr_python）")
        if not Path(py).exists():
            raise RuntimeError(f"ASR Python 不存在：{py}")
        script = Path(__file__).with_name("asr_worker.py")
        cmd = [
            py,
            str(script),
            "--wav",
            wav,
            "--model",
            str(self.conf.get("asr_model") or "small"),
            "--threads",
            str(max(1, int(self.conf.get("asr_threads") or 2))),
            "--compute-type",
            str(self.conf.get("asr_compute_type") or "int8"),
        ]
        language = str(self.conf.get("asr_language") or "").strip()
        if language:
            cmd += ["--language", language]
        prompt = str(self.conf.get("asr_initial_prompt") or "").strip()
        if prompt:
            cmd += ["--initial-prompt", prompt]
        root = str(self.conf.get("asr_download_root") or "").strip()
        if root:
            cmd += ["--download-root", root]
        async with self._asr_lock:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(), timeout=max(20, int(timeout))
                )
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    pass
                raise RuntimeError("语音识别超时")
        payload = {}
        for line in reversed(
            [x for x in out.decode("utf-8", "replace").splitlines() if x.strip()]
        ):
            try:
                payload = json.loads(line)
                break
            except Exception:
                continue
        if not payload.get("ok"):
            raise RuntimeError(
                str(payload.get("error") or err.decode("utf-8", "replace")[-200:] or "识别失败")
            )
        return str(payload.get("text") or "").strip()

    async def _describe(self, sheet: str) -> str:
        provider = self._vision_provider()
        if provider is None:
            return ""
        prompt = (
            "这是一个视频按时间顺序抽取的 9 个画面（左上到右下，带时间标签）。\n"
            "请描述视频里发生了什么：场景、人物或物体、画面里的文字、动作和情绪。\n"
            "用中文，4-8 句；只描述看得见的内容，看不清的不要编造；"
            "不要提“拼图”“截图”“视觉模型”这些词。"
        )
        try:
            result = await asyncio.wait_for(
                provider.text_chat(prompt=prompt, image_urls=[sheet]), timeout=60
            )
        except Exception as exc:
            logger.info(f"[{NAME}] 视频画面理解失败：{exc}")
            return ""
        return str(getattr(result, "completion_text", "") or "").strip()

    async def _voice_text(self, record: Record) -> str:
        try:
            path = await record.convert_to_file_path()
        except Exception as exc:
            logger.info(f"[{NAME}] 语音文件读取失败：{exc}")
            return voice_block("", "")
        workdir = tempfile.mkdtemp(prefix="snow_voice_")
        try:
            wav = path
            if Path(path).suffix.lower() != ".wav":
                wav = extract_audio(
                    self._ffmpeg(), path, str(Path(workdir) / "voice.wav"), 0, 120
                )
            text = await self._transcribe(
                wav, max(30, int(self.conf.get("voice_timeout_seconds") or 90))
            )
            logger.info(f"[{NAME}] 语音转写：{text[:80]}")
            return voice_block(text)
        except Exception as exc:
            logger.info(f"[{NAME}] 语音识别失败：{exc}")
            return voice_block("", "")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _video_text(self, path: str, name: str = "") -> str:
        size_mb = os.path.getsize(path) / 1024 / 1024 if os.path.isfile(path) else 0
        max_mb = float(self.conf.get("video_max_mb") or 150)
        if size_mb > max_mb:
            return f"[视频文件] {name}，{size_mb:.0f}MB，太大了，我没看完"
        duration = probe_duration(self._ffprobe(), path)
        max_seconds = max(10, int(float(self.conf.get("video_max_seconds") or 600)))
        watch_seconds = min(duration or max_seconds, max_seconds)
        cols = max(2, min(5, int(self.conf.get("frame_cols") or 3)))
        rows = max(2, min(5, int(self.conf.get("frame_rows") or 3)))
        workdir = tempfile.mkdtemp(prefix="snow_video_")
        try:
            frames = extract_frames(
                self._ffmpeg(),
                path,
                workdir,
                watch_seconds,
                count=cols * rows,
                width=480,
            )
            visual = ""
            if frames:
                sheet = build_sheet(
                    frames,
                    str(Path(workdir) / "sheet.jpg"),
                    cols=cols,
                    rows=sheet_rows(len(frames), cols),
                )
                visual = await self._describe(sheet)
                if not visual:
                    visual = "（画面没识别出来）"
            transcript = ""
            audio_seconds = min(
                watch_seconds,
                max(5, int(self.conf.get("video_inline_seconds") or 120)),
            )
            try:
                wav = extract_audio(
                    self._ffmpeg(),
                    path,
                    str(Path(workdir) / "audio.wav"),
                    audio_seconds,
                )
                transcript = await self._transcribe(
                    wav,
                    max(60, int(self.conf.get("video_asr_timeout_seconds") or 300)),
                )
            except Exception as exc:
                logger.info(f"[{NAME}] 视频音频转写失败：{exc}")
            block = video_block(
                name or Path(path).name,
                duration,
                visual,
                transcript,
                truncated=bool(duration and duration > audio_seconds),
            )
            logger.info(
                f"[{NAME}] 视频理解完成：{name}（{duration:.0f}s，"
                f"帧 {len(frames)}，转写 {len(transcript)} 字）"
            )
            return block
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _file_path(self, comp: File) -> str:
        try:
            return await comp.get_file()
        except Exception:
            return ""

    @filter.event_message_type(
        filter.EventMessageType.ALL, priority=(1 << 31) - 10
    )
    async def handle_media(self, event: AstrMessageEvent):
        if not self._enabled():
            return
        comps = list(getattr(event.message_obj, "message", None) or [])
        if not comps:
            return
        additions: list[str] = []
        changed = False
        videos_done = 0
        max_videos = max(1, int(self.conf.get("max_videos_per_message") or 1))
        for index, comp in enumerate(comps):
            try:
                if isinstance(comp, Record) and bool(
                    self.conf.get("voice_enabled", True)
                ) and self._mode_ok(event, "voice"):
                    text = await self._voice_text(comp)
                    comps[index] = Plain(text)
                    additions.append(text)
                    changed = True
                elif isinstance(comp, Video) and bool(
                    self.conf.get("video_enabled", True)
                ) and self._mode_ok(event, "video"):
                    if videos_done >= max_videos:
                        continue
                    videos_done += 1
                    path = await comp.convert_to_file_path()
                    text = await self._video_text(path, Path(path).name)
                    comps[index] = Plain(text)
                    additions.append(text)
                    changed = True
                elif isinstance(comp, File) and bool(
                    self.conf.get("video_enabled", True)
                ) and self._mode_ok(event, "video"):
                    name = str(getattr(comp, "name", "") or "")
                    if is_video_name(name) or is_video_name(getattr(comp, "url", "")):
                        if videos_done >= max_videos:
                            continue
                        videos_done += 1
                        path = await self._file_path(comp)
                        if path:
                            text = await self._video_text(path, name)
                            comps[index] = Plain(text)
                            additions.append(text)
                            changed = True
                    elif is_audio_name(name) and bool(
                        self.conf.get("audio_file_enabled", True)
                    ) and self._mode_ok(event, "voice"):
                        path = await self._file_path(comp)
                        if path:
                            workdir = tempfile.mkdtemp(prefix="snow_audio_")
                            try:
                                wav = extract_audio(
                                    self._ffmpeg(),
                                    path,
                                    str(Path(workdir) / "audio.wav"),
                                    0,
                                    120,
                                )
                                text = await self._transcribe(wav, 120)
                            finally:
                                shutil.rmtree(workdir, ignore_errors=True)
                            block = voice_block(text, name)
                            comps[index] = Plain(block)
                            additions.append(block)
                            changed = True
            except Exception as exc:
                logger.warning(f"[{NAME}] 媒体处理失败：{exc}")
        if not changed:
            return
        event.message_obj.message = comps
        base = str(event.message_str or "").strip()
        merged = "\n\n".join([part for part in [base, *additions] if part])
        event.message_str = merged
        event.message_obj.message_str = merged
