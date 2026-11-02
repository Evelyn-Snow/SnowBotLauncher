"""把已有画像批量改写成第一人称（一次性迁移工具）。

画像插件从 v0.2.2 起用「她自己的口吻、第一人称」写印象笔记，但旧档案还是
第三人称的客观档案。这个脚本读 AstrBot 配置里的聊天模型，把现有 .md 档案
逐份改写成第一人称：只改叙述口吻，事实、判断、细节保持原样；frontmatter
（昵称、曾用名、互动次数、道德评分）原封不动。

用法：
    python scripts/rewrite_profiles_first_person.py --profiles-dir "C:\\Evelyn_Snow\\画像" --dry-run
    python scripts/rewrite_profiles_first_person.py --profiles-dir "C:\\Evelyn_Snow\\画像"

默认从启动器配置找到 AstrBot 目录，再读 data/cmd_config.json 里的聊天提供商；
也可以用 --config 直接指定 cmd_config.json。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.astrbot_plugin_snow_profile.library import (  # noqa: E402
    build_moral_section,
    moral_section,
    parse_profile,
    render_profile,
)

SYSTEM_PROMPT = (
    "你在帮一个聊天机器人改写它自己的私人笔记。把下面这份第三人称档案改成第一人称，用她自己的口吻写：\n"
    "- 这是她私下记的印象，可以带一点情绪和判断（亲近、警惕、觉得对方有意思都行），但事实、细节一条都不能变；\n"
    "- 原文里「对方」「TA」「用户」指聊天对象，改写后用「他/她」或对方昵称；\n"
    "- 原文里「助手」「机器人」指她自己，改写后用「我」；\n"
    "- 描述对方性格、说话、兴趣的句子，主语仍然是对方，绝不能改成「我」"
    "（例如「对方爱吃盖浇饭」不能写成「我爱吃盖浇饭」）；\n"
    "- 每句话的主语写清楚，别让人分不清是谁做的事；\n"
    "- 用 ## 小节组织（我眼里的TA、TA说话的样子、我们常聊什么、跟TA相处要注意什么、最近的事）："
    "我眼里的TA 只写身份、关系和总体印象，说话风格归 TA说话的样子，同一件事不要在两个小节里重复；\n"
    "- 不要输出 frontmatter、不要代码块、不要解释。"
)


def default_config_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "SnowBotLauncher" / "config.json"
    try:
        cfg = json.loads(base.read_text(encoding="utf-8-sig"))
        astrbot_dir = Path(str(cfg.get("astrbot_dir") or ""))
        return astrbot_dir / "data" / "cmd_config.json"
    except Exception:
        return Path("data/cmd_config.json")


def _first_key(value) -> str:
    """AstrBot 的 key 可能是字符串，也可能是多把钥匙的列表。"""
    if isinstance(value, (list, tuple)):
        return next((str(k).strip() for k in value if str(k).strip()), "")
    return str(value or "").strip()


def pick_chat_source(cfg: dict) -> tuple[str, str, str]:
    """返回 (api_base, api_key, model)；只读取，不打印密钥。"""
    sources = {str(s.get("id")): s for s in cfg.get("provider_sources") or [] if isinstance(s, dict)}
    providers = [p for p in cfg.get("provider") or [] if isinstance(p, dict)]
    for provider in providers:
        if provider.get("provider_type") not in (None, "chat_completion"):
            continue
        source = sources.get(str(provider.get("provider_source_id") or ""))
        if not source or not _first_key(source.get("key")):
            continue
        if str(source.get("provider") or "") not in ("deepseek", "openai", "azure", "zhipu", "moonshot"):
            continue
        return (
            str(source.get("api_base") or "").rstrip("/"),
            _first_key(source.get("key")),
            str(provider.get("model") or "deepseek-chat"),
        )
    raise SystemExit("没找到可用的聊天提供商（需要 api_base + key + 聊天模型）")


def rewrite(api_base: str, api_key: str, model: str, body: str, timeout: int = 120) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"档案正文：\n\n{body}"},
        ],
        "temperature": 0.7,
        "max_tokens": 1200,
    }
    req = urllib.request.Request(
        api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    content = data["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
    return content.strip()


def check(text: str) -> str:
    """返回不合格原因；空串表示可以写入。"""
    if text.count("## ") < 2:
        return "缺少 ## 小节"
    for bad in ("该用户", "助手", "用户画像"):
        if bad in text:
            return f"仍含第三人称词「{bad}」"
    if len(text) > 1500:
        return "输出过长"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles-dir", required=True)
    parser.add_argument("--config", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg_path = Path(args.config) if args.config else default_config_path()
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise SystemExit(f"读不到 AstrBot 配置 {cfg_path}：{exc}")
    api_base, api_key, model = pick_chat_source(cfg)
    print(f"使用模型 {model}（{api_base}）")

    files = sorted(Path(args.profiles_dir).glob("*.md"))
    if not files:
        raise SystemExit(f"{args.profiles_dir} 里没有画像文件")
    failed = 0
    for path in files:
        old = path.read_text(encoding="utf-8")
        parsed = parse_profile(old)
        body = parsed["body"]
        # 去掉旧档案的 H1（render_profile 会重新生成）
        body = re.sub(r"^#\s+[^\n]*\n*", "", body.strip(), count=1)
        moral = moral_section(old)
        if moral:
            idx = body.find("## 道德评价")
            if idx != -1:
                body = body[:idx].rstrip()
        if not body.strip():
            print(f"[跳过] {path.name}：正文为空")
            continue
        print(f"[改写] {path.name}（{len(body)} 字）…", end=" ", flush=True)
        try:
            new_body = rewrite(api_base, api_key, model, body)
        except Exception as exc:
            failed += 1
            print(f"失败：{exc}")
            continue
        why = check(new_body)
        if why:
            failed += 1
            print(f"不合格（{why}），保持原样")
            continue
        entries = [ln for ln in moral.splitlines() if ln.strip().startswith("- [")]
        if entries:
            new_body = new_body.rstrip() + "\n\n" + build_moral_section(
                parsed["moral_score"] if parsed["moral_score"] is not None else 75, entries
            )
        md = render_profile(
            parsed["qq"] or path.stem,
            parsed["name"],
            parsed["history"],
            new_body,
            time.time(),
            parsed["exchanges"],
            moral_score=parsed["moral_score"],
        )
        if args.dry_run:
            print("\n--- 预览 ---\n" + md + "\n--- 预览结束 ---")
            continue
        bak = path.with_suffix(".md.bak")
        if not bak.exists():
            bak.write_text(old, encoding="utf-8")
        path.write_text(md, encoding="utf-8")
        print("已写入")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
