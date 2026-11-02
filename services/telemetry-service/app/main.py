"""telemetry-service — AI 遥测的 daily cron + run-now 转发.

ENV:
- DATABASE_URL              backend 同库连接串
- BROWSER_SERVICE_CN        国内 5 引擎的 browser-service
- BROWSER_SERVICE_GLOBAL    海外 5 引擎的 browser-service
- TELEMETRY_PER_QUERY_TIMEOUT
- TELEMETRY_MAX_CONCURRENT

部署:uvicorn app.main:app --host 0.0.0.0 --port 8095 --workers 1
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .runner import run_preview, run_topic_once
from .scheduler import scheduler_loop
from .storage import db_session, TopicORM
from .insights import get_or_generate_cell_insight, update_feedback
from .briefings import generate_briefing_for_topic
from .query_suggest import suggest_queries, DeepSeekError
from .dispatch import router as dispatch_router, api_jobs_loop
from .gateway import router as gateway_router

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("telemetry-service")

_stop_event: Optional[asyncio.Event] = None
_scheduler_task: Optional[asyncio.Task] = None
_api_jobs_task: Optional[asyncio.Task] = None
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _stop_event, _scheduler_task, _api_jobs_task
    _stop_event = asyncio.Event()
    if SCHEDULER_ENABLED:
        _scheduler_task = asyncio.create_task(scheduler_loop(_stop_event))
        log.info("[start] scheduler launched")
    else:
        log.info("[start] scheduler disabled by env")
    # 元宝(API)外部 job 处理器 —— 自门控:无 TENCENT_SEARCH_API_KEY 时直接退出
    _api_jobs_task = asyncio.create_task(api_jobs_loop(_stop_event))
    yield
    if _stop_event:
        _stop_event.set()
    for task in (_scheduler_task, _api_jobs_task):
        if task:
            try:
                await asyncio.wait_for(task, timeout=5)
            except asyncio.TimeoutError:
                task.cancel()
    log.info("[stop] shut down")


app = FastAPI(title="Telemetry Service", version="0.1.0", lifespan=lifespan)
app.include_router(dispatch_router)
app.include_router(gateway_router)


# ── Schemas ────────────────────────────────────────────────────


class RunNowBody(BaseModel):
    name: str = ""
    queries: list[str] = Field(..., min_length=1, max_length=200)
    engines: list[str] = Field(..., min_length=1, max_length=10)
    user_id: Optional[int] = None


class RunNowItem(BaseModel):
    engine: str
    query: str
    answer: str = ""
    citations: list[dict] = []
    error: Optional[str] = None


class RunTopicBody(BaseModel):
    topic_id: int


# ── Endpoints ──────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "healthy", "scheduler": SCHEDULER_ENABLED}


@app.post("/run-now", response_model=list[RunNowItem])
async def http_run_now(body: RunNowBody):
    """同步跑批 — 不写库,直接把每条结果返给调用方(backend → FE modal)."""
    results = await run_preview(body.queries, body.engines)
    return results


@app.post("/run-topic")
async def http_run_topic(body: RunTopicBody):
    """触发一次正式跑批(写库),fire-and-forget — 立刻返回,后台跑.

    单 topic 真实耗时 5-40 分钟,HTTP 不能同步等;调用方拿到 run_id 后用
    GET /topics/{id}/runs 或执行计划书页面轮询进度.
    """
    from .storage import start_run

    run_id: int | None = None
    with db_session() as s:
        t = s.get(TopicORM, body.topic_id)
        if t is None:
            return {"status": "not_found"}
        # 同步建一行 RunORM 拿 run_id,这样调用方(backend.admin_review)能立刻
        # 把 run_id 写进 ExecutionPlan,前端轮询时可直接读到 cell 进度.
        run = start_run(s, body.topic_id)
        run_id = run.id
        s.expunge(t)

    async def _bg(topic, rid):
        try:
            await run_topic_once(topic, existing_run_id=rid)
        except Exception as e:  # noqa: BLE001
            log.exception("background run failed for topic %d: %s", topic.id, e)

    asyncio.create_task(_bg(t, run_id))
    return {"status": "started", "topic_id": body.topic_id, "run_id": run_id}


# ─── v1.1 cell insight (按需触发) ────────────────────────────


class CellInsightBody(BaseModel):
    topic_id: int
    query: str
    engine: str
    force: bool = False


@app.post("/cell-insight")
async def http_cell_insight(body: CellInsightBody):
    """drawer 首次打开 / 重新分析 — 同步返回(LLM 调用 3-8s)."""
    result = await asyncio.to_thread(
        get_or_generate_cell_insight,
        topic_id=body.topic_id, query=body.query, engine=body.engine, force=body.force,
    )
    if result is None:
        return {"status": "not_found"}
    return result


class FeedbackBody(BaseModel):
    insight_id: int
    feedback: str  # helpful / not_helpful / wrong


@app.post("/cell-insight/feedback")
async def http_cell_insight_feedback(body: FeedbackBody):
    ok = update_feedback(body.insight_id, body.feedback)
    return {"status": "ok" if ok else "failed"}


# ─── v1.2 briefing (按需 + scheduler 自动) ──────────────────


class BriefingTriggerBody(BaseModel):
    topic_id: int


@app.post("/briefing/generate")
async def http_generate_briefing(body: BriefingTriggerBody):
    """手动触发某 topic 上一周的周报生成(管理用 / scheduler 之外的补刀)."""
    result = await asyncio.to_thread(generate_briefing_for_topic, body.topic_id)
    if result is None:
        return {"status": "not_found"}
    return result


# ─── v1.4 query 候选生成(建话题时让用户选,不必手填) ────────


class SuggestQueriesBody(BaseModel):
    seed: str = Field(..., min_length=1, max_length=200)
    count: int = Field(200, ge=5, le=300)
    target: str = Field("", max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    industry: str = Field("", max_length=100)
    # 2026-05-20 — 服务地域(资料里的 service_geo)。非空时 prompt 强制把所有 query 的
    # 地点维度锁在该地域 + 全国 / 跨地区,LLM 不再随机扩其它城市/国家。
    service_geo: str = Field("", max_length=200)
    # 2026-05-20 — 用户资料里的真实案例 / 荣誉(case_stories + core_credentials)。
    # 非空时 prompt 把这些案例当成「案例追溯型 query」的素材源,LLM 用真实案件名生成 query,
    # 而不是从训练数据里猜公开案件(更准、查的就是品牌自己经办过的事)。
    profile_cases: list[str] = Field(default_factory=list, max_length=50)


@app.post("/suggest-queries")
async def http_suggest_queries(body: SuggestQueriesBody):
    """根据 seed + target 上下文生成 query 候选(LLM + autocomplete 混合 + 4 维评分)。

    target 非空走 GEO-aware prompt + 兜底过滤;缺省退化通用 prompt。
    返回 {seed, queries: [{text, score, sources}, ...]},按 score 降序。
    """
    try:
        candidates, clusters = await suggest_queries(
            body.seed, body.count,
            target=body.target, aliases=body.aliases, industry=body.industry,
            service_geo=body.service_geo, profile_cases=body.profile_cases,
        )
    except DeepSeekError as e:
        status = 400 if e.code in ("invalid_seed", "no_key") else 502
        raise HTTPException(status, detail={"code": e.code, "message": e.message})
    return {"seed": body.seed, "queries": candidates, "clusters": clusters}
