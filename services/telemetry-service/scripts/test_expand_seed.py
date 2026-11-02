"""一次性脚本 — 拿现在线上 query_suggest 的 prompt 跑一个 seed,看扩展结果。

不接 DB、不调 backend、不走聚类(避免拖 sentence-transformers + torch),
只拿 LLM 那一路输出。直接用 telemetry-service 的 query_suggest 模块,确保
prompt 跟生产一致。

用法:
    DEEPSEEK_API_KEY=sk-xxx python3 services/telemetry-service/scripts/test_expand_seed.py \\
        "企业跨境/TMT投资、海外并购的北京律师" \\
        --target "金诚同达" --service-geo "北京" --count 50

不传 seed 时跑默认 seed(用户原话)。output 分两段:
    1. LLM 原始 + 过滤后候选,按 score 降序
    2. 同 token-bag jaccard 聚成的句式骨架分组(粗略,本地 token 化)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TS_ROOT = REPO_ROOT / "services" / "telemetry-service"
sys.path.insert(0, str(TS_ROOT))

from app.query_suggest import (  # noqa: E402
    DeepSeekError, suggest_queries,
)


DEFAULT_SEED = "企业跨境/TMT投资、海外并购的北京律师"


_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]*|[一-鿿]")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text or ""))


def _group_by_jaccard(items: list[dict], threshold: float = 0.65) -> list[list[dict]]:
    """简易句式骨架聚类:token 集合 jaccard ≥ threshold 归一组。

    输入按 score 降序,组首即代表。返回 [[item, ...], ...]。
    """
    groups: list[list[dict]] = []
    group_tokens: list[set[str]] = []
    for it in items:
        tks = _tokens(it["text"])
        placed = False
        if tks:
            for gi, gtk in enumerate(group_tokens):
                if not gtk:
                    continue
                union = tks | gtk
                if union and len(tks & gtk) / len(union) >= threshold:
                    groups[gi].append(it)
                    placed = True
                    break
        if not placed:
            groups.append([it])
            group_tokens.append(tks)
    return groups


async def _run(seed: str, count: int, target: str, aliases: list[str],
               industry: str, service_geo: str, profile_cases: list[str]) -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("ERROR: DEEPSEEK_API_KEY 没设。export 一下再跑。", file=sys.stderr)
        sys.exit(2)

    print("=" * 78)
    print(f"seed         : {seed}")
    print(f"count        : {count}")
    print(f"target       : {target or '(none)'}")
    print(f"aliases      : {aliases or '(none)'}")
    print(f"industry     : {industry or '(none)'}")
    print(f"service_geo  : {service_geo or '(none)'}")
    print(f"profile_cases: {len(profile_cases)} 条")
    print("=" * 78)

    try:
        candidates, _clusters = await suggest_queries(
            seed, count,
            target=target, aliases=aliases, industry=industry,
            service_geo=service_geo, profile_cases=profile_cases,
            include_autocomplete=False,
            include_clusters=False,  # 避免拉 sentence-transformers
        )
    except DeepSeekError as e:
        print(f"\nDeepSeek 失败:[{e.code}] {e.message}", file=sys.stderr)
        sys.exit(1)

    if not candidates:
        print("\n空结果(候选全被过滤或 LLM 返回为空)。", file=sys.stderr)
        sys.exit(1)

    # ─── 1. 候选清单(按 score 降序)
    print(f"\n──── 候选清单 · 共 {len(candidates)} 条(按 score 降序)────")
    src_counter: Counter[str] = Counter()
    for i, c in enumerate(candidates, 1):
        srcs = ",".join(c.get("sources", []))
        src_counter.update(c.get("sources", []))
        print(f"{i:3d}. [{c['score']:>3d}] {c['text']}   ({srcs})")

    print("\n──── source 统计 ────")
    for src, n in src_counter.most_common():
        print(f"  {src}: {n}")

    # ─── 2. 简易句式骨架聚类(本地 token jaccard)
    print(f"\n──── 句式骨架聚类(jaccard ≥ 0.65) ────")
    groups = _group_by_jaccard(candidates, threshold=0.65)
    groups.sort(key=len, reverse=True)
    for gi, g in enumerate(groups, 1):
        if len(g) == 1:
            continue
        print(f"\n[组 {gi}] {len(g)} 条,代表:{g[0]['text']}")
        for it in g[:6]:
            print(f"    [{it['score']:>3d}] {it['text']}")
        if len(g) > 6:
            print(f"    … 还有 {len(g) - 6} 条")
    singletons = [g[0] for g in groups if len(g) == 1]
    if singletons:
        print(f"\n[单体] {len(singletons)} 条,不与任何组共享 ≥65% token")

    # ─── 3. JSON 落地(方便后续比对)
    out_dir = REPO_ROOT / "tmp"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"expand_seed_{abs(hash(seed)) % 10_000_000}.json"
    out_path.write_text(
        json.dumps(
            {"seed": seed, "count": count, "target": target,
             "candidates": candidates},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nJSON 落地:{out_path}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("seed", nargs="?", default=DEFAULT_SEED, help="种子文本")
    p.add_argument("--count", type=int, default=50, help="生成候选数(5-300)")
    p.add_argument("--target", default="", help="被检测品牌(LLM 会绕开点名)")
    p.add_argument("--aliases", default="", help="逗号分隔的品牌别名")
    p.add_argument("--industry", default="", help="行业")
    p.add_argument("--service-geo", default="", help="服务地域(锁地点)")
    p.add_argument("--profile-cases", default="",
                   help="真实经办案例,| 分隔,例:阿里港股上市|美的收购库卡")
    args = p.parse_args()

    aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]
    profile_cases = [c.strip() for c in args.profile_cases.split("|") if c.strip()]

    asyncio.run(_run(args.seed, args.count, args.target, aliases,
                     args.industry, args.service_geo, profile_cases))


if __name__ == "__main__":
    main()
