"""本地视频/语音处理的纯逻辑：格式判断、ffprobe/ffmpeg、拼图、文本块。

不依赖 AstrBot，可单独测试；ffmpeg/ffprobe 由调用方传路径。
"""

from __future__ import annotations

import math
import os
import re
import subprocess

VIDEO_SUFFIXES = (
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".flv",
    ".m4v",
    ".ts",
    ".wmv",
)
AUDIO_SUFFIXES = (
    ".mp3",
    ".wav",
    ".amr",
    ".silk",
    ".ogg",
    ".m4a",
    ".aac",
    ".flac",
    ".opus",
)


def _suffix(value: str) -> str:
    text = str(value or "").split("?", 1)[0]
    base = os.path.basename(text.replace("\\", "/"))
    _, ext = os.path.splitext(base)
    return ext.lower()


def is_video_name(value: str) -> bool:
    return _suffix(value) in VIDEO_SUFFIXES


def is_audio_name(value: str) -> bool:
    return _suffix(value) in AUDIO_SUFFIXES


def probe_duration(ffprobe: str, path: str, timeout: int = 30) -> float:
    if not ffprobe or not os.path.isfile(ffprobe):
        return 0.0
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(5, int(timeout)),
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return max(0.0, float((out.stdout or "0").strip() or 0))
    except Exception:
        return 0.0


def extract_frames(
    ffmpeg: str,
    src: str,
    outdir: str,
    duration: float,
    count: int = 9,
    width: int = 480,
    timeout: int = 120,
) -> list[dict]:
    """按时间均匀抽帧，返回 [{path, ts}]；单帧失败跳过。"""
    if not ffmpeg or not os.path.isfile(ffmpeg):
        raise RuntimeError("找不到 ffmpeg")
    os.makedirs(outdir, exist_ok=True)
    total = max(1, int(count))
    span = max(0.0, float(duration or 0))
    frames: list[dict] = []
    for index in range(total):
        if span > 0:
            ts = min(max(0.2, span * (index + 0.5) / total), max(0.2, span - 0.1))
        else:
            ts = index * 2.0
        dest = os.path.join(outdir, f"frame_{index:02d}.jpg")
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{ts:.3f}",
            "-i",
            src,
            "-frames:v",
            "1",
            "-vf",
            f"scale={max(160, int(width))}:-2",
            "-q:v",
            "4",
            dest,
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                timeout=max(5, int(timeout)),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            continue
        if os.path.isfile(dest) and os.path.getsize(dest) > 200:
            frames.append({"path": dest, "ts": ts})
    return frames


def _label(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def build_sheet(
    frames: list[dict],
    out_path: str,
    cols: int = 3,
    rows: int = 3,
    tile: tuple[int, int] = (426, 240),
) -> str:
    """把抽出来的单帧拼成带时间标签的 3x3 图。"""
    from PIL import Image, ImageDraw

    cols = max(1, min(5, int(cols)))
    rows = max(1, min(5, int(rows)))
    if not frames:
        raise ValueError("没有可用画面")
    width, height = tile
    sheet = Image.new("RGB", (cols * width, rows * height), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames[: cols * rows]):
        x = (index % cols) * width
        y = (index // cols) * height
        try:
            img = Image.open(frame["path"]).convert("RGB")
            img.thumbnail((width, height))
        except Exception:
            continue
        sheet.paste(img, (x, y))
        label = _label(float(frame.get("ts") or 0))
        draw.rectangle((x + 4, y + 4, x + 58, y + 24), fill=(0, 0, 0))
        draw.text((x + 8, y + 7), label, fill=(255, 255, 255))
    sheet.save(out_path, quality=88)
    return out_path


def extract_audio(
    ffmpeg: str,
    src: str,
    dest: str,
    max_seconds: int = 180,
    timeout: int = 180,
) -> str:
    """抽 16k 单声道 wav；max_seconds<=0 表示不截断。"""
    if not ffmpeg or not os.path.isfile(ffmpeg):
        raise RuntimeError("找不到 ffmpeg")
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        src,
    ]
    if max_seconds and max_seconds > 0:
        cmd += ["-t", str(int(max_seconds))]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-f", "wav", dest]
    subprocess.run(
        cmd,
        check=True,
        timeout=max(10, int(timeout)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1000:
        raise RuntimeError("音频为空")
    return dest


def video_block(
    name: str,
    duration: float,
    visual: str,
    transcript: str,
    *,
    truncated: bool = False,
) -> str:
    parts = [
        f"[视频文件] {name or '未命名'}，时长约 {int(max(0, duration))} 秒"
    ]
    if visual:
        parts.append("画面：" + visual.strip())
    if transcript:
        parts.append(
            ("音频转写（前段）：" if truncated else "音频转写：")
            + transcript.strip()
        )
    elif not visual:
        parts.append("没有读到可用画面，也没有听清音频")
    if truncated:
        parts.append("（视频较长，只听了前段音频）")
    return "\n".join(parts)


VOICE_STT_BACKENDS = ("auto", "qq", "local")


def normalize_voice_stt_backend(value: str) -> str:
    backend = str(value or "").strip().lower()
    return backend if backend in VOICE_STT_BACKENDS else "auto"


def voice_stt_order(value: str) -> tuple[str, ...]:
    """返回识别顺序：auto 先 QQ 再本地，其余只走选定的一种。"""
    backend = normalize_voice_stt_backend(value)
    return ("qq", "local") if backend == "auto" else (backend,)


def extract_ptt_text(payload) -> str:
    """兼容 OneBot 客户端包装：直接 {text} 或 {data: {text}}。"""
    if not isinstance(payload, dict):
        return ""
    text = payload.get("text")
    if not text and isinstance(payload.get("data"), dict):
        text = payload["data"].get("text")
    return str(text or "").strip()


def voice_block(text: str, name: str = "") -> str:
    body = strip_timestamps(text)
    head = "（语音消息）"
    if name:
        head = f"（语音消息：{name}）"
    return head + (body or "没听清内容")


def strip_timestamps(text: str) -> str:
    """语音转写不需要时间轴；去掉每行开头的 [mm:ss]。"""
    lines = []
    for line in str(text or "").splitlines():
        cleaned = re.sub(r"^\s*\[\d{2}:\d{2}\]\s*", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return " ".join(lines).strip()


def sheet_rows(count: int, cols: int = 3) -> int:
    return max(1, math.ceil(max(1, int(count)) / max(1, int(cols))))
