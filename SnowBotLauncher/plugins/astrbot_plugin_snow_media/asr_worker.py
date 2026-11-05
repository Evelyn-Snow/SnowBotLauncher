"""独立 ASR worker：由 snow_media 用单独的 Python 环境调用。

只读 16k 单声道 wav，输出一行 JSON；模型和依赖不进入 AstrBot 主环境。
"""

from __future__ import annotations

import argparse
import json
import sys
import wave


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True)
    parser.add_argument("--model", default="small")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default="")
    parser.add_argument("--initial-prompt", default="")
    parser.add_argument("--download-root", default="")
    parser.add_argument("--check-speech", action="store_true")
    parser.add_argument("--min-speech-seconds", type=float, default=1.0)
    args = parser.parse_args()
    try:
        import numpy as np

        with wave.open(args.wav, "rb") as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            audio = audio.astype(np.float32) / 32768.0
        if args.check_speech:
            from faster_whisper.vad import VadOptions, get_speech_timestamps

            chunks = get_speech_timestamps(audio, VadOptions())
            seconds = sum(
                max(0.0, float(item.get("end", 0)) - float(item.get("start", 0)))
                for item in chunks
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "has_speech": seconds >= max(0.0, args.min_speech_seconds),
                        "speech_seconds": round(seconds, 2),
                        "duration": round(len(audio) / 16000.0, 2),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return 0
        from faster_whisper import WhisperModel

        kwargs = {}
        if args.download_root:
            kwargs["download_root"] = args.download_root
        model = WhisperModel(
            args.model,
            device="cpu",
            compute_type=args.compute_type,
            cpu_threads=max(1, args.threads),
            **kwargs,
        )
        segments, info = model.transcribe(
            audio,
            language=args.language or None,
            beam_size=1,
            vad_filter=True,
            initial_prompt=args.initial_prompt or None,
        )
        lines = []
        for seg in segments:
            text = str(seg.text or "").strip()
            if text:
                start = int(seg.start or 0)
                lines.append(f"[{start // 60:02d}:{start % 60:02d}] {text}")
        print(
            json.dumps(
                {
                    "ok": True,
                    "language": getattr(info, "language", "") or "",
                    "duration": float(getattr(info, "duration", 0) or 0),
                    "text": "\n".join(lines),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)[:300]}, ensure_ascii=False),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
