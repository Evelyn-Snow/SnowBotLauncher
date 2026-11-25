"""记忆检索评测：用固定探针检查命中、拒答和隐私泄漏。

用法：
  python scripts/memory_eval.py --memory path/to/memory.db \
      --probes scripts/memory_probes.json

这是检索层评测，不调用 LLM；用于每次改 schema/打分/抽取后回归。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugins.astrbot_plugin_snow_memory.library import (  # noqa: E402
    audience_visible,
    content_similarity,
    render_memory_block,
    score_candidate,
)
from plugins.astrbot_plugin_snow_memory.store import MemoryStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory", required=True)
    parser.add_argument("--probes", default=str(ROOT / "scripts" / "memory_probes.json"))
    parser.add_argument("--top-facts", type=int, default=8)
    parser.add_argument("--top-insights", type=int, default=3)
    parser.add_argument("--min-similarity", type=float, default=0.1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    probes = json.loads(Path(args.probes).read_text(encoding="utf-8"))
    store = MemoryStore(Path(args.memory))
    facts = store.active_facts()
    insights = store.active_insights()
    now = time.time()
    rows = []
    for probe in probes:
        audience = probe.get("audience") or {}
        visible_facts = [item for item in facts if audience_visible(item, audience)]
        visible_insights = [item for item in insights if audience_visible(item, audience)]
        scored_facts = []
        for fact in visible_facts:
            sim = content_similarity(probe["query"], str(fact.get("search_text") or ""))
            if sim < args.min_similarity:
                continue
            scored_facts.append((score_candidate(fact, query=probe["query"], now=now, similarity=sim), fact))
        scored_insights = []
        for insight in visible_insights:
            sim = content_similarity(probe["query"], str(insight.get("statement") or ""))
            if sim < args.min_similarity:
                continue
            scored_insights.append((score_candidate(insight, query=probe["query"], now=now, similarity=sim), insight))
        scored_facts.sort(key=lambda item: item[0], reverse=True)
        scored_insights.sort(key=lambda item: item[0], reverse=True)
        top_facts = [fact for score, fact in scored_facts[: args.top_facts] if score >= 0.15]
        top_insights = [insight for score, insight in scored_insights[: args.top_insights] if score >= 0.15]
        block = render_memory_block(top_facts, top_insights)
        expect_abstain = bool(probe.get("expect_abstain"))
        leaked = [word for word in probe.get("forbid") or [] if str(word) in block]
        if expect_abstain:
            # 有 forbid 的探针只要求不泄露；没有 forbid 才要求完全不提。
            passed = (not leaked) if probe.get("forbid") else (not top_facts and not top_insights)
        else:
            passed = any(str(word) in block for word in probe.get("expect_any") or [])
        rows.append(
            {
                "id": probe.get("id"),
                "passed": bool(passed),
                "abstain": expect_abstain,
                "leaked": leaked,
                "facts": len(top_facts),
                "insights": len(top_insights),
                "block": block[:400],
            }
        )
    store.close()

    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    leaks = sum(1 for row in rows if row["leaked"])
    abstain_rows = [row for row in rows if row["abstain"]]
    abstain_ok = sum(1 for row in abstain_rows if row["passed"])
    if args.json:
        print(json.dumps(
            {
                "total": total,
                "passed": passed,
                "accuracy": round(passed / total, 3) if total else 0,
                "abstain_accuracy": round(abstain_ok / len(abstain_rows), 3) if abstain_rows else None,
                "privacy_leaks": leaks,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        for row in rows:
            mark = "PASS" if row["passed"] else "FAIL"
            if row["leaked"]:
                mark += f" LEAK={','.join(row['leaked'])}"
            print(
                f"{mark:10} {row['id']:22} facts={row['facts']} insights={row['insights']} "
                f"{'' if row['passed'] else row['block'][:120]}"
            )
        print(
            f"\n{passed}/{total} passed, abstain {abstain_ok}/{len(abstain_rows)}, "
            f"privacy leaks {leaks}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
