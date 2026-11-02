"""DB session for telemetry-service.

读写同一 SQLAlchemy DB(backend 主库,目前是 SQLite,sentinel v2 后切 MySQL).
Schema 由 backend 的 geo/__init__.py 创建,这里只复用同一张表的连接.

这些 ORM 定义需要与 backend geo/models/ai_telemetry.py 保持字段一致.
选择独立声明而非共享 Base,是为了让 telemetry-service 可独立部署、不强依赖 backend 代码包.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine, event,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:////home/DEV/GEO/backend/data/geo_checker.db",
)

_connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

# SQLite 跟 geo-backend 共享同一个 db 文件 — backend 在 approve / cron 时持写锁,
# telemetry 这边也要并发写 runs / responses。这里设置:
#  - busy_timeout=30s:撞到瞬时锁就等,不要直接抛 OperationalError
#  - 复用 backend 已经开启的 WAL / synchronous=NORMAL(open 一下就行,backend 写过)
if "sqlite" in DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _sqlite_busy_timeout(dbapi_conn, _connection_record):
        if type(dbapi_conn).__module__ != "sqlite3":
            return
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()

Base = declarative_base()


class TopicORM(Base):
    __tablename__ = "ai_telemetry_topics"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    target = Column(String, nullable=False, default="")
    target_aliases_json = Column(Text, nullable=False, default="[]")
    queries_json = Column(Text, nullable=False, default="[]")
    engines_json = Column(Text, nullable=False, default="[]")
    enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String, nullable=True)
    prompt_extension = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RunORM(Base):
    __tablename__ = "ai_telemetry_runs"
    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="running")
    error = Column(Text, nullable=True)


class ResponseORM(Base):
    __tablename__ = "ai_telemetry_responses"
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("ai_telemetry_runs.id"), nullable=False, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id"), nullable=False, index=True)
    engine = Column(String, nullable=False)
    query = Column(Text, nullable=False)
    answer = Column(Text, nullable=False, default="")
    citations_json = Column(Text, nullable=False, default="[]")
    video_url = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # v1
    hit = Column(Boolean, nullable=False, default=False)
    hit_excerpt = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)
    # v1.1
    competitors_json = Column(Text, nullable=True)
    citation_domains_json = Column(Text, nullable=True)
    answer_format = Column(String, nullable=True)
    # v1.3 提及位置
    mention_position = Column(String, nullable=True)
    # v1.4 品牌排名(1-based,LLM 抽取)
    brand_rank = Column(Integer, nullable=True)


class QueryHitORM(Base):
    __tablename__ = "ai_telemetry_query_hits"
    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id"), nullable=False)
    query = Column(Text, nullable=False)
    engine = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    first_hit_at = Column(DateTime, nullable=True)
    first_hit_response_id = Column(Integer, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    total_runs = Column(Integer, nullable=False, default=0)
    total_hits = Column(Integer, nullable=False, default=0)


class CellInsightORM(Base):
    __tablename__ = "ai_telemetry_cell_insights"
    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id"), nullable=False)
    query = Column(Text, nullable=False)
    engine = Column(String, nullable=False)
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)
    verdict = Column(String, nullable=False)
    summary = Column(Text, nullable=False, default="")
    competitors_top3_json = Column(Text, nullable=False, default="[]")
    recommendations_json = Column(Text, nullable=False, default="[]")
    evidence_response_ids_json = Column(Text, nullable=False, default="[]")
    llm_model = Column(String, nullable=False, default="")
    prompt_version = Column(String, nullable=False, default="cell_v1")
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    feedback = Column(String, nullable=True)


class TopicBriefingORM(Base):
    __tablename__ = "ai_telemetry_topic_briefings"
    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id"), nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    body_md = Column(Text, nullable=False, default="")
    kpi_snapshot_json = Column(Text, nullable=False, default="{}")
    top_actions_json = Column(Text, nullable=False, default="[]")
    delivered_email_at = Column(DateTime, nullable=True)
    feedback_score = Column(Integer, nullable=True)
    llm_model = Column(String, nullable=False, default="")
    prompt_version = Column(String, nullable=False, default="briefing_v1")
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WorkerORM(Base):
    """browser-service worker 注册表(调度中心 pull 模型)。镜像 backend 同名表。"""
    __tablename__ = "browser_workers"
    id = Column(Integer, primary_key=True, index=True)
    worker_uid = Column(String, nullable=False, unique=True, index=True)
    hostname = Column(String, nullable=True)
    label = Column(String, nullable=True)
    region = Column(String, nullable=True)
    exit_ip = Column(String, nullable=True)
    engines_json = Column(Text, nullable=False, default="[]")
    max_concurrency = Column(Integer, nullable=False, default=3)
    status = Column(String, nullable=False, default="offline")
    enabled = Column(Boolean, nullable=False, default=True)
    version = Column(String, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    registered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    meta_json = Column(Text, nullable=True)


class DispatchTaskORM(Base):
    """待跑的 (engine, query) 任务队列。drip 入队 → worker claim → 跑 → 交结果。"""
    __tablename__ = "dispatch_tasks"
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("ai_telemetry_runs.id"), nullable=False, index=True)
    topic_id = Column(Integer, ForeignKey("ai_telemetry_topics.id"), nullable=False)
    engine = Column(String, nullable=False)
    query = Column(String(1024), nullable=False)
    priority = Column(Integer, nullable=False, default=1)        # 种子=0 扩展=1
    status = Column(String, nullable=False, default="queued")    # queued/claimed/done/failed
    claimed_by = Column(String, nullable=True, index=True)
    claimed_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)


class JobORM(Base):
    """域中性的浏览器任务队列(对外服务 P0)。

    与 dispatch_tasks 的区别:dispatch_tasks 焊死舆情域(run_id/topic_id,结果走
    detect_hit/save_response 落 ai_telemetry_responses);browser_jobs 不带任何业务
    语义,只有 (engine, query) → (answer, citations, ...),结果就地存本表。worker
    用同一 pull 模型领取,claim 时内部 dispatch_tasks 绝对优先、外部 jobs 填剩余槽。
    tenant_id / idempotency_key / callback_url 为多租户网关(P1)预留,P0 可空。
    """
    __tablename__ = "browser_jobs"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, nullable=True, index=True)        # 多租户预留,P0 可空
    engine = Column(String, nullable=False)
    query = Column(String(2048), nullable=False)
    priority = Column(Integer, nullable=False, default=10)        # 外部默认低于内部(种子0/扩展1)
    status = Column(String, nullable=False, default="queued")     # queued/claimed/done/failed
    claimed_by = Column(String, nullable=True, index=True)
    claimed_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=2)
    idempotency_key = Column(String, nullable=True, unique=True, index=True)
    callback_url = Column(String, nullable=True)                  # done 后 webhook(P2 firing)
    answer = Column(Text, nullable=True)
    citations_json = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class ApiTenantORM(Base):
    """对外服务的租户(多租户网关 P1)。一个租户一套配额 + 引擎白名单 + 计费档。"""
    __tablename__ = "api_tenants"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")    # active/suspended
    tier = Column(String, nullable=False, default="free")        # free/pro... 决定 job 优先级
    engines_json = Column(Text, nullable=False, default="[]")    # 引擎白名单,空=全放开
    daily_quota_json = Column(Text, nullable=False, default="{}")  # {engine: n};缺省走 default
    daily_quota_default = Column(Integer, nullable=False, default=20)
    credit_balance = Column(Integer, nullable=False, default=100)  # 预付额度(credits),成功 job 扣减
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UsageLedgerORM(Base):
    """计量计费账本(P2)。每个 job 终态写一行:成功 billable+扣额度,失败不计费。"""
    __tablename__ = "usage_ledger"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, nullable=False, index=True)
    engine = Column(String, nullable=False)
    billable = Column(Boolean, nullable=False, default=False)
    cost = Column(Integer, nullable=False, default=0)            # 扣的 credits
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ApiKeyORM(Base):
    """租户的 API Key。明文只在创建时返回一次,库里只存 sha256。"""
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("api_tenants.id"), nullable=False, index=True)
    key_prefix = Column(String, nullable=False)                  # sk-live-xxxx 前 12 位,便于识别
    key_hash = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")    # active/revoked
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


@contextmanager
def db_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ── helpers ────────────────────────────────────────────────────


def list_enabled_topics(s: Session) -> list[TopicORM]:
    return s.query(TopicORM).filter(TopicORM.enabled == True).all()  # noqa: E712


def start_run(s: Session, topic_id: int) -> RunORM:
    r = RunORM(topic_id=topic_id, started_at=datetime.utcnow(), status="running")
    s.add(r)
    s.flush()
    t = s.get(TopicORM, topic_id)
    if t:
        t.last_run_at = r.started_at
        t.last_run_status = "running"
    return r


def finish_run(s: Session, run_id: int, status: str, error: str | None = None) -> None:
    r = s.get(RunORM, run_id)
    if not r:
        return
    r.finished_at = datetime.utcnow()
    r.status = status
    r.error = error
    t = s.get(TopicORM, r.topic_id)
    if t:
        t.last_run_status = status


def save_response(
    s: Session, *, run_id: int, topic_id: int, engine: str, query: str,
    answer: str, citations: list[dict], video_url: str | None, error: str | None,
    hit: bool = False, hit_excerpt: str | None = None, source_url: str | None = None,
) -> ResponseORM:
    r = ResponseORM(
        run_id=run_id, topic_id=topic_id, engine=engine, query=query,
        answer=answer or "",
        citations_json=json.dumps(citations or [], ensure_ascii=False),
        video_url=video_url,
        error=error,
        hit=hit,
        hit_excerpt=hit_excerpt,
        source_url=source_url,
    )
    s.add(r)
    s.flush()  # 拿到 id 用于 QueryHit.first_hit_response_id
    return r


def parse_topic(t: TopicORM) -> tuple[list[str], list[str]]:
    queries_raw = json.loads(t.queries_json or "[]")
    queries: list[str] = []
    for q in queries_raw:
        if isinstance(q, dict):
            txt = q.get("text") or ""
            if txt:
                queries.append(txt)
        elif isinstance(q, str):
            queries.append(q)
    engines = json.loads(t.engines_json or "[]")
    return queries, engines


def seed_query_texts(t: TopicORM) -> set[str]:
    """queries_json 里 is_seed==true 的 query text 集合.

    用于 drip"先跑种子提示词,再跑扩展提示词"的优先级排序:
    种子是 admin 审核过的原始题,扩展是按 cluster 派生的长尾题(is_seed 缺省/false).
    """
    out: set[str] = set()
    for q in json.loads(t.queries_json or "[]"):
        if isinstance(q, dict) and q.get("is_seed") and q.get("text"):
            out.add(q["text"])
    return out


def parse_target(t: TopicORM) -> tuple[str, list[str]]:
    """返回 (target, aliases). target 为空时 fallback 到 topic.name."""
    target = (t.target or "").strip()
    aliases = json.loads(t.target_aliases_json or "[]")
    # 兼容老数据:target 为空 → 用 name 当 target
    if not target:
        target = (t.name or "").strip()
    return target, [a for a in aliases if a]


def query_created_at(t: TopicORM, query_text: str) -> datetime:
    """新 query 不回填 — 取 query 自己的 created_at,缺失则回退到 topic.created_at."""
    queries_raw = json.loads(t.queries_json or "[]")
    for q in queries_raw:
        if isinstance(q, dict) and q.get("text") == query_text:
            ts = q.get("created_at")
            if ts:
                try:
                    return datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    pass
    return t.created_at
