"""Runner — 对单个 topic 跑一遍 (engine × query),写库 + 维护 QueryHit + 异步 LLM 抽取.

外部依赖:browser-service `/search` (POST {engine, query})
失败粒度:engine × query 级别,单条挂了不影响其它,error 落到 response 行.

流程(v1 + v1.1):
  1. start_run() / initialize_pending_cells() / mark_cells_running()
  2. 并发跑 N×M 个 (engine, query)
  3. 单条结果 → detect_hit() → save_response(hit=...) → update_query_hit_after_response()
  4. finish_run()
  5. fire-and-forget 异步 LLM 抽取:对本次所有 Response 抽 competitors / citation_domains / answer_format
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .storage import (
    db_session, start_run, finish_run, save_response, parse_topic, parse_target,
    TopicORM, ResponseORM,
)
from .tracking import (
    detect_hit, initialize_pending_cells, mark_cells_running,
    update_query_hit_after_response,
)
from .llm import extract_response_insights
from .openrouter import call_openrouter, is_openrouter_engine
from .yuanbao_search import run_yuanbao, yuanbao_api_enabled
from .citation_match import (
    extract_publish_urls, match_citations_to_docs, merge_cited_by,
)
from sqlalchemy import text

log = logging.getLogger(__name__)

BROWSER_SERVICE_CN = os.environ.get("BROWSER_SERVICE_CN", "http://localhost:8091")
BROWSER_SERVICE_GLOBAL = os.environ.get("BROWSER_SERVICE_GLOBAL", "http://localhost:8092")
PER_QUERY_TIMEOUT = int(os.environ.get("TELEMETRY_PER_QUERY_TIMEOUT", "180"))
MAX_CONCURRENT = int(os.environ.get("TELEMETRY_MAX_CONCURRENT", "3"))
EXTRACT_AFTER_RUN = os.environ.get("TELEMETRY_EXTRACT_AFTER_RUN", "1") == "1"
# 单 query 完成后在 Semaphore 内 sleep [min,max] 秒,降低对引擎站点的击穿压力。
# 设 0 关闭。默认 2-5s,跟 MAX_CONCURRENT=5 配合每个引擎天然限流。
INTER_QUERY_DELAY_MIN = float(os.environ.get("TELEMETRY_INTER_QUERY_DELAY_MIN", "2"))
INTER_QUERY_DELAY_MAX = float(os.environ.get("TELEMETRY_INTER_QUERY_DELAY_MAX", "5"))

CN_ENGINES = {"deepseek", "doubao", "qwen", "wenxin", "yuanbao"}

ARK_BOT_URL = "https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions"


def _browser_url(engine: str) -> str:
    # per-engine 覆盖优先:把单个引擎指到独立 worker(不同出口 IP),绕开站点对某 IP
    # 的风控/封禁,而不影响其它引擎。如 BROWSER_SERVICE_DEEPSEEK=http://browser-worker.example.com:8092
    override = os.environ.get(f"BROWSER_SERVICE_{engine.upper()}")
    if override:
        return override
    return BROWSER_SERVICE_CN if engine in CN_ENGINES else BROWSER_SERVICE_GLOBAL


async def _call_doubao_api(client: httpx.AsyncClient, query: str) -> dict[str, Any]:
    """走 ARK Bot API(绑定 Doubao-1.5-pro-32k + 联网搜索)替代浏览器抓取。
    凭据缺失时返回 error 让上层 fallback 到 browser-service。
    """
    key = os.environ.get("ARK_API_KEY", "").strip()
    bot_id = os.environ.get("DOUBAO_BOT_ID", "").strip()
    if not key or not bot_id:
        return {"engine": "doubao", "query": query, "answer": "", "citations": [],
                "video_url": None, "source_url": None,
                "error": "ARK_API_KEY / DOUBAO_BOT_ID not set"}
    payload = {"model": bot_id, "messages": [{"role": "user", "content": query}]}
    try:
        r = await client.post(
            ARK_BOT_URL, json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=PER_QUERY_TIMEOUT,
        )
        if r.status_code != 200:
            return {"engine": "doubao", "query": query, "answer": "", "citations": [],
                    "video_url": None, "source_url": None,
                    "error": f"http_{r.status_code}: {r.text[:200]}"}
        data = r.json()
        if "error" in data:
            return {"engine": "doubao", "query": query, "answer": "", "citations": [],
                    "video_url": None, "source_url": None,
                    "error": f"ark_error: {data['error']}"}
        msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
        answer = msg.get("content", "") or ""
        refs = data.get("references") or msg.get("references") or []
        citations: list[dict] = []
        for i, ref in enumerate(refs):
            if not isinstance(ref, dict):
                continue
            url = ref.get("url") or ""
            if not url:
                continue
            citations.append({
                "url": url,
                "title": (ref.get("title") or "").strip(),
                "snippet": (ref.get("summary") or ref.get("snippet") or "").strip()[:500],
                "position": i + 1,
            })
        return {"engine": "doubao", "query": query, "answer": answer,
                "citations": citations, "video_url": None, "source_url": None,
                "error": None}
    except Exception as e:  # noqa: BLE001
        return {"engine": "doubao", "query": query, "answer": "", "citations": [],
                "video_url": None, "source_url": None,
                "error": f"exception: {e}"}


async def _call_browser(client: httpx.AsyncClient, engine: str, query: str) -> dict[str, Any]:
    """统一引擎调度入口:海外 5 引擎走 OpenRouter API,国内 5 引擎走 browser-service.

    D4(2026-05-18)起:CN 引擎优先 /search-hot(hot browser 复用,30% 加速).
    若 worker 返 501(engine 还没适配 hot protocol),自动降级到 /search.

    豆包(2026-05-26)若 ARK_API_KEY + DOUBAO_BOT_ID 都配置,走 ARK Bot API
    替代浏览器爬取;凭据缺失则继续走原浏览器路径(fallback 不破坏行为)。

    返回 shape:{engine, query, answer, citations, video_url, source_url, error}
    """
    if is_openrouter_engine(engine):
        return await call_openrouter(client, engine, query, timeout=PER_QUERY_TIMEOUT)
    if engine == "doubao" and os.environ.get("ARK_API_KEY") and os.environ.get("DOUBAO_BOT_ID"):
        return await _call_doubao_api(client, query)
    if engine == "yuanbao" and yuanbao_api_enabled():
        # 元宝走「元宝搜索 + deepseek 合成」API,不占浏览器账号(TENCENT_SEARCH_API_KEY 配了才启用)
        return await run_yuanbao(client, query, timeout=PER_QUERY_TIMEOUT)
    base = _browser_url(engine)
    body = {"engine": engine, "query": query}

    # Path 1: hot — D4 路径,工作的就用,501 才 fallback
    try:
        r = await client.post(f"{base}/search-hot", json=body, timeout=PER_QUERY_TIMEOUT)
        if r.status_code == 501:
            # Engine 没适配 hot protocol → 降到 /search
            log.info("engine=%s not hot-adapted (501), fallback to /search", engine)
        else:
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        log.warning("engine=%s /search-hot HTTP error: %s, fallback to /search", engine, e)

    # Path 2: cold(legacy)— /search-hot 失败 / 501 都走这里
    try:
        r = await client.post(f"{base}/search", json=body, timeout=PER_QUERY_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        return {"engine": engine, "query": query, "answer": "", "citations": [],
                "video_url": None, "source_url": None, "error": str(e)}


async def run_topic_once(
    topic: TopicORM,
    *,
    existing_run_id: int | None = None,
    pairs: Optional[set[tuple[str, str]]] = None,
    finalize: bool = True,
) -> None:
    """对一个 topic 把 (queries × engines) 全部跑完并落库.

    existing_run_id 非空时复用已建的 RunORM(由 /run-topic HTTP handler 同步建一行
    返回给调用方,这里只补 cell 初始化 + 实际跑批 + finish_run).

    pairs 非空时(scheduler drip 传入)本次只跑这些 (engine, query) 子集,且跳过
    内部的跨 run 去重 —— 周期级去重由 scheduler 负责.pairs=None 时跑全量(老行为).

    finalize=False 时(drip 多 tick 复用同一 run)本次只跑批、不 finish_run,由
    scheduler 在整个周期跑完后自己 finish_run.

    单 Response 落库时:detect_hit + update_query_hit_after_response 都在同一 session.
    Run 整体结束后:fire-and-forget LLM 抽取(EXTRACT_AFTER_RUN=1 时).
    """
    queries, engines = parse_topic(topic)
    target, aliases = parse_target(topic)
    topic_id = topic.id
    prompt_extension = (topic.prompt_extension or "").strip()
    if not queries or not engines:
        log.warning("topic %d empty, skip", topic_id)
        return

    # 跨 run 去重:同 topic 在 SKIP_RECENT_HOURS 小时内已经有成功 response 的
    # (engine, query) 组合本次跳过,避免重跑(2026-05-26 run 69 部分跑完后 abort
    # 重启 run 70 时,deepseek 已经写库的 15 条不应该再跑)。设 0 关闭去重。
    skip_hours = int(os.environ.get("TELEMETRY_SKIP_RECENT_HOURS", "24"))
    done_set: set[tuple[str, str]] = set()
    if pairs is None and skip_hours > 0:
        # cutoff 在 Python 算好再传参,避免方言差异(NOW()/::interval 是 Postgres 专用,
        # 在 SQLite / MySQL 上会报错)。created_at 存的是 naive UTC,这里也用 utcnow。
        cutoff = datetime.utcnow() - timedelta(hours=skip_hours)
        with db_session() as s:
            rows = s.execute(text(
                "SELECT DISTINCT engine, query FROM ai_telemetry_responses "
                "WHERE topic_id = :tid AND (error IS NULL OR error = '') "
                "  AND created_at >= :cutoff"
            ), {"tid": topic_id, "cutoff": cutoff}).all()
            done_set = {(r.engine, r.query) for r in rows}
        if done_set:
            log.info("topic %d skip-recent: %d (engine, query) 对在过去 %dh 已有成功 response", topic_id, len(done_set), skip_hours)

    with db_session() as s:
        if existing_run_id is not None:
            run_id = existing_run_id
        else:
            run = start_run(s, topic_id)
            run_id = run.id
        # 矩阵初始化(对新 query / engine 也要建 cell)
        # 这里 topic 是从外部 expunge 进来的副本,先 merge 再操作
        t_managed = s.merge(topic)
        initialize_pending_cells(s, t_managed)
        mark_cells_running(s, t_managed)

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    failures = 0
    response_ids: list[int] = []

    async with httpx.AsyncClient() as client:
        async def _one(engine: str, query: str) -> None:
            nonlocal failures
            # admin 配置的 prompt_extension 拼到 query 末尾发给引擎,但落库 / 矩阵 cell 仍按原 query 索引
            effective_query = f"{query}\n\n{prompt_extension}" if prompt_extension else query
            async with sem:
                result = await _call_browser(client, engine, effective_query)
                if INTER_QUERY_DELAY_MAX > 0:
                    await asyncio.sleep(random.uniform(INTER_QUERY_DELAY_MIN, INTER_QUERY_DELAY_MAX))
            answer = result.get("answer", "") or ""
            error = result.get("error")

            # 命中判定 — 失败的 response 不判定(answer 是空)
            hit, excerpt = (False, None)
            if not error:
                hit, excerpt = detect_hit(answer, target, aliases)

            with db_session() as s:
                r = save_response(
                    s, run_id=run_id, topic_id=topic_id, engine=engine, query=query,
                    answer=answer,
                    citations=result.get("citations") or [],
                    video_url=result.get("video_url"),
                    source_url=result.get("source_url"),
                    error=error,
                    hit=hit,
                    hit_excerpt=excerpt,
                )
                rid = r.id
                # 维护矩阵 cell
                if not error:
                    t_managed = s.get(TopicORM, topic_id)
                    if t_managed is not None:
                        update_query_hit_after_response(s, response=r, topic=t_managed)

            response_ids.append(rid)
            if error:
                failures += 1

        # query-major 顺序:第一波 5 个 task = 第一个 query × 5 个引擎,
        # 自然让 Sem 槽位均匀分摊到各引擎(每引擎单 hot context 内部串行,
        # 跨引擎才能真并行)。engine-major 会让一个引擎独占 Sem,其他全排队 —
        # 实测 2026-05-26 run 69 翻船过。
        # pairs 模式(drip):只跑 scheduler 指定的子集;否则跑全量减去 skip-recent。
        if pairs is not None:
            run_pairs = [(e, q) for q in queries for e in engines if (e, q) in pairs]
        else:
            run_pairs = [(e, q) for q in queries for e in engines if (e, q) not in done_set]
        tasks = [_one(e, q) for (e, q) in run_pairs]
        log.info("topic %d run %d: launching %d tasks (matrix=%d, pairs=%s, skipped=%d)",
                 topic_id, run_id, len(tasks), len(engines) * len(queries),
                 "yes" if pairs is not None else "no",
                 len(engines) * len(queries) - len(tasks))
        await asyncio.gather(*tasks)

    total = len(run_pairs)
    # total=0(本 tick 无可跑)→ 视为 success,不误判 failed
    status = "failed" if total > 0 and failures >= total else "success"
    if finalize:
        with db_session() as s:
            finish_run(s, run_id, status, error=None if failures == 0 else f"{failures}/{total} failed")
    log.info("topic %d run %d done: %d/%d ok (finalize=%s)", topic_id, run_id, total - failures, total, finalize)

    # v1.1 fire-and-forget LLM 抽取(不阻塞返回)
    if EXTRACT_AFTER_RUN and response_ids:
        asyncio.create_task(_extract_responses_bg(topic_id, target, aliases, response_ids))

    # v1.5 URL 级 ROI 命中:扫本批 responses 的 citations 跟 published doc 的投放
    # URL 做规范化匹配,命中则按 engine 分桶写 cited_by_json。这块完全独立于 LLM
    # 抽取,所以单独 fire-and-forget,失败不影响 LLM 抽取。
    if response_ids:
        asyncio.create_task(_update_cited_by_bg(topic_id, response_ids))


async def _extract_responses_bg(
    topic_id: int, target: str, aliases: list[str], response_ids: list[int],
) -> None:
    """v1.1 — 异步给每条新 Response 调 LLM 抽 competitors / answer_format / citation_domains."""
    try:
        await asyncio.sleep(0.1)
        for rid in response_ids:
            try:
                await asyncio.to_thread(_extract_one, target, rid)
            except Exception as e:  # noqa: BLE001
                log.warning("extract failed for response %d: %s", rid, e)
    except Exception as e:  # noqa: BLE001
        log.exception("extract bg task crashed: %s", e)


async def _update_cited_by_bg(topic_id: int, response_ids: list[int]) -> None:
    """v1.5 — 跑批后扫 responses 的 citations 跟 published doc 的投放 URL 做规范化匹配,
    命中则按 engine 分桶写 cited_by_json。整体一个 DB session,失败静默。"""
    try:
        await asyncio.sleep(0.5)  # 让 _extract_responses_bg 先跑起来
        await asyncio.to_thread(_update_cited_by_sync, topic_id, response_ids)
    except Exception as e:  # noqa: BLE001
        log.exception("cited_by bg task crashed: %s", e)


def _update_cited_by_sync(topic_id: int, response_ids: list[int]) -> None:
    """同步:扫所有 published doc 的 publish URL,跟本批 response 的 citations 匹配。"""
    with db_session() as s:
        doc_rows = s.execute(text(
            "SELECT id, publish_targets_json, cited_by_json FROM topic_generated_docs "
            "WHERE topic_id = :tid AND status = 'published'"
        ), {"tid": topic_id}).mappings().all()
        if not doc_rows:
            return
        doc_urls: dict[int, list[str]] = {}
        doc_cited: dict[int, str | None] = {}
        for row in doc_rows:
            urls = extract_publish_urls(row["publish_targets_json"])
            if urls:
                doc_urls[row["id"]] = urls
                doc_cited[row["id"]] = row["cited_by_json"]
        if not doc_urls:
            return

        # {doc_id: {engine: {response_id, ...}}}
        new_hits: dict[int, dict[str, set[int]]] = {}
        for rid in response_ids:
            r = s.get(ResponseORM, rid)
            if r is None or r.error:
                continue
            try:
                citations = json.loads(r.citations_json or "[]")
            except Exception:  # noqa: BLE001
                continue
            matched = match_citations_to_docs(citations, doc_urls)
            for doc_id in matched:
                new_hits.setdefault(doc_id, {}).setdefault(r.engine, set()).add(r.id)

        if not new_hits:
            return

        # 合并写回 cited_by_json
        for doc_id, by_engine in new_hits.items():
            cb = doc_cited.get(doc_id) or "{}"
            for engine, rids in by_engine.items():
                cb = merge_cited_by(cb, engine, rids)
            s.execute(text(
                "UPDATE topic_generated_docs SET cited_by_json = :cb WHERE id = :id"
            ), {"cb": cb, "id": doc_id})
        s.commit()
        log.info("topic %d cited_by updated: %d docs matched", topic_id, len(new_hits))


def _extract_one(target: str, response_id: int) -> None:
    """同步抽一条 — 在 thread 里跑,避免阻塞 asyncio loop."""
    with db_session() as s:
        r = s.get(ResponseORM, response_id)
        if r is None or r.error:
            return
        if r.competitors_json:
            return  # 已抽过
        citations: list[dict] = []
        try:
            citations = json.loads(r.citations_json or "[]")
        except Exception:  # noqa: BLE001
            pass
        result = extract_response_insights(
            target=target, query=r.query, engine=r.engine,
            answer=r.answer or "", citations=citations,
        )
        if not result:
            return
        comps = result.get("competitors") or []
        # citation_domains 兜底:LLM 没给 → 从 citations 自抽
        cd = result.get("citation_domains") or _domains_from_citations(citations)
        r.competitors_json = json.dumps(comps, ensure_ascii=False)
        r.citation_domains_json = json.dumps(cd, ensure_ascii=False)
        r.answer_format = result.get("answer_format") or None
        # mention_position 兜底:LLM 没给 → 用 hit_excerpt 在原文里的位置算 lead/body/tail
        r.mention_position = result.get("mention_position") or _fallback_position(r.answer, r.hit_excerpt)
        # brand_rank:LLM 给的整数(1-based);未命中或抽取失败 → 保持 NULL。
        # 未命中场景(r.hit=False)即使 LLM 误给数字也强制 NULL,保证语义一致。
        rank = result.get("brand_rank")
        if r.hit and isinstance(rank, int) and rank >= 1:
            r.brand_rank = rank
        else:
            r.brand_rank = None


def _fallback_position(answer: str | None, hit_excerpt: str | None) -> str | None:
    """LLM 不可用时,按 hit_excerpt 在答复全文里的字符位置粗判 lead/body/tail.

    用 excerpt 去 strip 两端「…」,在 answer 里 find 首字符位置;前 30% lead,
    后 30% tail,中间 body.无法匹配返回 None.
    """
    if not answer or not hit_excerpt:
        return None
    needle = hit_excerpt.strip("…").strip()
    if not needle or not answer:
        return None
    i = answer.find(needle[:20]) if len(needle) >= 20 else answer.find(needle)
    if i < 0:
        return None
    pct = i / max(1, len(answer))
    if pct < 0.30:
        return "lead"
    if pct > 0.70:
        return "tail"
    return "body"


def _domains_from_citations(citations: list[dict]) -> list[str]:
    """从 citations 抽顶级域名 — LLM 没拿到时的兜底."""
    out = []
    seen = set()
    for c in citations or []:
        d = (c.get("domain") or "").strip().lower()
        if not d and c.get("url"):
            try:
                d = (urlparse(c["url"]).hostname or "").lower()
            except Exception:  # noqa: BLE001
                pass
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


async def run_preview(queries: list[str], engines: list[str]) -> list[dict[str, Any]]:
    """/run-now 同步预览 — 不写库,直接返回结果给前端 modal."""
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    results: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        async def _one(engine: str, query: str) -> None:
            async with sem:
                r = await _call_browser(client, engine, query)
            results.append({
                "engine": engine,
                "query": query,
                "answer": r.get("answer", "") or "",
                "citations": r.get("citations") or [],
                "error": r.get("error"),
            })

        # query-major 顺序:第一波 5 个 task = 第一个 query × 5 个引擎,
        # 自然让 Sem 槽位均匀分摊到各引擎(每引擎单 hot context 内部串行,
        # 跨引擎才能真并行)。engine-major 会让一个引擎独占 Sem,其他全排队 —
        # 实测 2026-05-26 run 69 翻船过。
        tasks = [_one(e, q) for q in queries for e in engines]
        await asyncio.gather(*tasks)

    return results
