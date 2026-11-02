"""主题种子词 → 4 维场景扩展的核心 fan-out(从 api/ai_telemetry.py 的 /expand-queries 抽出)。

供 agent 工具复用(见 geo/agent/tools.py 的 expand_prompts);底层调已是 service 的
query_expander.expand_one_scene。**不写库**,只返回候选。

注:现有 /expand-queries 端点目前仍是内联同款逻辑;后续可重构为调用本函数(行为一致),
本次为避免影响在用端点未做此重构。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from geo.models.ai_telemetry import ALL_SCENES, MAX_EXPANSION_CANDIDATES
from geo.services.query_expander import DEFAULT_TIMEOUT, expand_one_scene


async def expand_topic_seed(
    topic: Any,
    seed: str,
    scenes: list[str] | None = None,
    count_per_scene: int | None = None,
) -> dict:
    """对一个种子词做 4 维(search/qa/intent/brand)扩展,返回:
        {"seed", "total_count", "scenes": {scene: {"queries":[...], "model", "error"}}}
    画像字段(service_geo / case_stories / core_credentials / brand_diff_tags /
    core_service_overview)从 topic.profile_json 按场景差异化注入,与端点一致。
    """
    seed = (seed or "").strip()
    if not seed:
        raise ValueError("seed 不能为空")

    scenes = [s for s in (scenes or list(ALL_SCENES)) if s in ALL_SCENES] or list(ALL_SCENES)
    cap = max(5, MAX_EXPANSION_CANDIDATES // len(ALL_SCENES))
    try:
        cps = int(count_per_scene) if count_per_scene else cap
    except (TypeError, ValueError):
        cps = cap
    cps = max(5, min(cps, cap))

    target = (topic.target or "").strip()
    industry = topic.industry or ""
    try:
        aliases = json.loads(topic.target_aliases_json or "[]")
    except Exception:  # noqa: BLE001
        aliases = []

    service_geo = ""
    entity_type = ""
    profile_cases: list[str] = []
    core_credentials: list[str] = []
    brand_diff_tags: list[str] = []
    core_service_overview = ""
    try:
        p = json.loads(topic.profile_json or "{}")
        if isinstance(p, dict):
            service_geo = str(p.get("service_geo") or "").strip()[:200]
            entity_type = str(p.get("entity_type") or "").strip()[:32]
            core_service_overview = str(p.get("core_service_overview") or "").strip()
            profile_cases = [str(s).strip()[:300] for s in (p.get("case_stories") or []) if str(s).strip()]
            core_credentials = [str(s).strip()[:300] for s in (p.get("core_credentials") or []) if str(s).strip()]
            brand_diff_tags = [str(s).strip()[:80] for s in (p.get("brand_diff_tags") or []) if str(s).strip()]
    except Exception:  # noqa: BLE001
        pass

    runnable: list[str] = []
    scene_results: dict[str, dict] = {}
    for s in scenes:
        if s == "brand" and not target:
            scene_results[s] = {"queries": [], "error": "brand 场景需要品牌名(target 为空)"}
        else:
            runnable.append(s)

    if runnable:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            tasks = [
                expand_one_scene(
                    scene=s, seed=seed, count=cps,
                    target=target, aliases=aliases, industry=industry, service_geo=service_geo,
                    entity_type=entity_type,
                    profile_cases=profile_cases, core_credentials=core_credentials,
                    brand_diff_tags=brand_diff_tags, core_service_overview=core_service_overview,
                    client=client,
                )
                for s in runnable
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        for s, res in zip(runnable, results):
            scene_results[s] = {"queries": [], "error": str(res)[:300]} if isinstance(res, Exception) else res

    total = sum(len((scene_results.get(s) or {}).get("queries") or []) for s in scenes)
    return {"seed": seed, "total_count": total, "scenes": scene_results}
