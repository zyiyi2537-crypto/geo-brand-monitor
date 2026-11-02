"""AI 遥测话题 API — CRUD + 立即试跑.

定时跑批由 telemetry-service 自己 cron 触发,本文件只管:
1. 用户的话题 CRUD
2. /run-now 同步转发到 telemetry-service 拿一次结果(modal 里"立即试跑")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
import mimetypes
import uuid
from pydantic import BaseModel
from sqlalchemy.orm import Session

from datetime import datetime, timedelta, timezone

from geo.api.auth import get_current_user
from geo.database import SessionLocal
from geo.models.ai_telemetry import (
    ALL_SCENES,
    AiTelemetryResponseORM, AiTelemetryRunORM, AiTelemetryTopicORM,
    AiTelemetryQueryHitORM, AiTelemetryCellInsightORM, AiTelemetryTopicBriefingORM,
    BrandProfile, BriefingAction, BriefingFeedbackPayload, BriefingOut,
    CellDrawerOut, CellEvidence, CellInsightOut, CellInsightRec, CompetitorMention,
    CompetitorShareEntry, ClusterBreakdownItem, DomainCount, EngineFirstHit,
    FeedbackPayload, GrowthQueryRow, GrowthSnapshot, GrowthReportOut,
    IntentBreakdownOut, KpiBlock, MAX_EXPANSION_CANDIDATES, MAX_SELECTED_QUERIES,
    OverviewOut, OwnedSplit, PROFILE_REQUIRED_FIELDS, PositionDist,
    PositionBreakdown, PositionBreakdownOut, GroupBreakdown, EngineSlice,
    IndustryBenchmarkOut,
    CompetitorSubstitutionItem, CompetitorSubstitutionOut,
    ProfileExtractOut, ProfileExtractPayload, QueryHitCell,
    ResponseOut, RunNowCitation,
    RunNowResult, RunOut, AdminRunOut, SeedPromptSubmitPayload,
    SelectedQueriesPayload, ShareOfVoiceOut,
    TopicGeneratedDocORM,
    TopicMediaOut, TopicMediaORM,
    TopicDraftPayload, TopicOut, TopicPayload, TrackingMatrixOut,
    TrendPoint, VALID_ENGINES,
)
from urllib.parse import urlparse as _urlparse
from geo.services.profile_extractor import (
    FileParseError, MAX_EXTRACTED_TEXT,
    extract_profile_from_text, file_bytes_to_text,
)
from geo.services.query_expander import (
    DEFAULT_TIMEOUT, expand_one_scene,
)
from geo.models.user import User
from geo_checker.analyzers.source_factor import classify_factor
from sqlalchemy import func

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-telemetry")

TELEMETRY_SERVICE_URL = os.environ.get("TELEMETRY_SERVICE_URL", "http://localhost:8095")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _validate_payload(payload: TopicPayload) -> None:
    bad = [e for e in payload.engines if e not in VALID_ENGINES]
    if bad:
        raise HTTPException(400, f"unknown engines: {bad}")
    # de-dup + strip — 同步把 query_cluster_ids / query_seeds / query_scene_types 按位置剔除/对齐
    cluster_ids_in = payload.query_cluster_ids if payload.query_cluster_ids else []
    seeds_in = payload.query_seeds if payload.query_seeds else []
    scenes_in = payload.query_scene_types if payload.query_scene_types else []
    cleaned_queries: list[str] = []
    cleaned_clusters: list[int] = []
    cleaned_seeds: list[str] = []
    cleaned_scenes: list[str] = []
    seen: set[str] = set()
    for i, q in enumerate(payload.queries):
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            cleaned_queries.append(q)
            if i < len(cluster_ids_in):
                cleaned_clusters.append(int(cluster_ids_in[i]))
            if i < len(seeds_in):
                cleaned_seeds.append((seeds_in[i] or "").strip()[:200])
            if i < len(scenes_in):
                sc = (scenes_in[i] or "").strip()
                cleaned_scenes.append(sc if sc in ALL_SCENES else "")
    if not cleaned_queries:
        raise HTTPException(400, "queries cannot be empty")
    payload.queries = cleaned_queries
    payload.query_cluster_ids = (
        cleaned_clusters if len(cleaned_clusters) == len(cleaned_queries) else None
    )
    payload.query_seeds = (
        cleaned_seeds if len(cleaned_seeds) == len(cleaned_queries) else None
    )
    payload.query_scene_types = (
        cleaned_scenes if len(cleaned_scenes) == len(cleaned_queries) else None
    )
    payload.engines = list(dict.fromkeys(payload.engines))
    # target / aliases cleanup
    payload.target = (payload.target or "").strip()
    aliases_clean: list[str] = []
    seen_a: set[str] = set()
    for a in (payload.target_aliases or []):
        a = a.strip()
        if a and a.lower() not in seen_a:
            seen_a.add(a.lower())
            aliases_clean.append(a)
    payload.target_aliases = aliases_clean


def _queries_with_meta(payload_queries: list[str], existing_raw: str | None,
                       cluster_ids: list[int] | None = None,
                       seeds: list[str] | None = None,
                       scene_types: list[str] | None = None,
                       *, new_status: str = "pending",
                       reviewer_id: int | None = None) -> str:
    """把 query 列表升级为 [{text, created_at, cluster_id?, status, ...}] 形态.

    Phase C 起每条 query 都带 `status`(pending/approved/rejected):
    - 已存在的 query:沿用原 status / created_at / cluster_id / submitted_at / approved_at
    - 新加的 query:默认 status="pending", submitted_at=now
      admin 替别人配主题时传 new_status="approved" 跳过审核
    - 校验:不允许删除 approved 的 query(由 caller `_validate_query_diff` 提前拦截)
    """
    now_iso = datetime.utcnow().isoformat()
    existing_by_text: dict[str, dict] = {}
    try:
        for q in json.loads(existing_raw or "[]"):
            if isinstance(q, dict) and q.get("text"):
                existing_by_text[q["text"]] = q
            elif isinstance(q, str):
                # 老版纯字符串 — 视为 topic 创建时即存在,补 approved 状态
                existing_by_text[q] = {
                    "text": q, "created_at": now_iso,
                    "status": "approved", "approved_at": now_iso,
                }
    except Exception:  # noqa: BLE001
        pass
    cluster_ok = isinstance(cluster_ids, list) and len(cluster_ids) == len(payload_queries)
    seeds_ok = isinstance(seeds, list) and len(seeds) == len(payload_queries)
    scenes_ok = isinstance(scene_types, list) and len(scene_types) == len(payload_queries)
    out = []
    seen_text: set[str] = set()
    for i, q in enumerate(payload_queries):
        # payload 内部去重 — 同一 text 只取首次出现,丢掉对应 cluster_id / seed
        if q in seen_text:
            continue
        seen_text.add(q)
        prev = existing_by_text.get(q)
        if prev is not None:
            item = dict(prev)
            item.setdefault("created_at", now_iso)
            item.setdefault("status", "approved")
        else:
            item = {
                "text": q,
                "created_at": now_iso,
                "status": new_status,
                "submitted_at": now_iso,
            }
            if new_status == "approved":
                item["approved_at"] = now_iso
                if reviewer_id is not None:
                    item["reviewer_id"] = reviewer_id
        cid: int | None = None
        if cluster_ok and isinstance(cluster_ids[i], int) and int(cluster_ids[i]) >= 0:
            cid = int(cluster_ids[i])
        elif isinstance(item.get("cluster_id"), int) and item["cluster_id"] >= 0:
            cid = int(item["cluster_id"])
        if cid is not None:
            item["cluster_id"] = cid
        # seed:payload 带就回填(空字符串不覆盖已有非空 seed,避免误清历史归属)。
        if seeds_ok:
            new_seed = (seeds[i] or "").strip()
            if new_seed and not item.get("seed"):
                item["seed"] = new_seed
        # scene_type:payload 带有效值就回填;已有非 search 标签不覆盖
        # (legacy 默认 search 不是用户真选的,允许被非 search 覆盖 — 与 selected-queries 同规则)。
        if scenes_ok:
            new_scene = (scene_types[i] or "").strip()
            if new_scene in ALL_SCENES:
                existing_scene = item.get("scene_type")
                if not existing_scene or existing_scene == "search":
                    item["scene_type"] = new_scene
        out.append(item)
    return json.dumps(out, ensure_ascii=False)


def _append_seed_prompts(existing_raw: str | None, texts: list[str] | None,
                          *, new_status: str = "pending",
                          reviewer_id: int | None = None) -> str:
    """把 payload.seed_drafts(若非空)逐条追加到 seed_prompts_json.

    幂等:文本已在列表里(不论状态)则跳过.
    texts 为 None / 空列表 / 全空字符串 则原样返回 existing.
    new_status 默认 "pending";admin 替别人配主题时传 "approved" 跳过审核.
    """
    raw = existing_raw or "[]"
    if not texts:
        return raw
    try:
        items = json.loads(raw)
    except Exception:  # noqa: BLE001
        items = []
    if not isinstance(items, list):
        items = []
    existing_texts = {s["text"] for s in items if isinstance(s, dict) and s.get("text")}
    now_iso = datetime.utcnow().isoformat()
    changed = False
    for raw_text in texts:
        cleaned = (raw_text or "").strip()
        if not cleaned or cleaned in existing_texts:
            continue
        item = {
            "text": cleaned,
            "status": new_status,
            "submitted_at": now_iso,
        }
        if new_status == "approved":
            item["approved_at"] = now_iso
            if reviewer_id is not None:
                item["reviewer_id"] = reviewer_id
        items.append(item)
        existing_texts.add(cleaned)
        changed = True
    return json.dumps(items, ensure_ascii=False) if changed else raw


def _validate_query_diff(payload_queries: list[str], existing_raw: str | None) -> None:
    """Phase C 只增不改:已 approved 的 query 不允许从 payload 中消失.

    text 是 query 的身份标识;如果用户把 approved query 改文案,等价于"删一个、加一个",
    这里阻止该操作 — 抛 422 with code=LOCKED_FIELD.
    """
    approved_texts: set[str] = set()
    try:
        for q in json.loads(existing_raw or "[]"):
            if isinstance(q, dict) and q.get("status") == "approved" and q.get("text"):
                approved_texts.add(q["text"])
    except Exception:  # noqa: BLE001
        return  # 解析失败就跳过,不阻塞 update
    payload_set = set(payload_queries)
    missing = approved_texts - payload_set
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "LOCKED_FIELD",
                "field": "queries",
                "message": "approved queries 不可删除或修改 text",
                "locked_items": sorted(missing),
            },
        )


def _get_topic_or_404(
    db: Session, topic_id: int, user_id: int, *, allow_admin_user: Optional[User] = None,
) -> AiTelemetryTopicORM:
    """常规调用 owner-only。
    传 allow_admin_user 时,若该用户 is_admin=True 则跳过 user_id 校验(admin 替别人改主题)。
    """
    t = db.get(AiTelemetryTopicORM, topic_id)
    if not t:
        raise HTTPException(404, "topic not found")
    if t.user_id != user_id:
        if not (allow_admin_user is not None and getattr(allow_admin_user, "is_admin", False)):
            raise HTTPException(404, "topic not found")
    return t


def _resolve_period(
    period: int, topic: AiTelemetryTopicORM, now: Optional[datetime] = None,
) -> tuple[int, datetime]:
    """解析时间窗口,返回 (period_days, period_start)。

    - period <= 0 → 全部历史:从 topic.created_at(无则兜底 10 年前)统计到现在,
      period_days 按实际跨度收敛(不会膨胀成上万天的 trend)。
    - period > 0  → 近 period 天(上限 90,沿用历史口径)。
    """
    now = now or datetime.utcnow()
    if period <= 0:
        start = topic.created_at or (now - timedelta(days=3650))
        days = max(1, (now - start).days + 1)
        return days, start
    days = max(1, min(period, 90))
    return days, now - timedelta(days=days)


# ─────────────────────────── CRUD ──────────────────────────────


# ─────── admin 跨用户管理(/workbench/accounts) ────────


def _require_admin(user: User) -> None:
    if not getattr(user, "is_admin", False):
        raise HTTPException(403, "admin only")


class AdminAccountSummary(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    # 客户在 ai_telemetry_topics.target 里填的品牌名(例:"洁卫森").
    # admin 画像列表优先显示这个 — 比 users.name(admin 内部备注)
    # 更能代表客户身份.取最早建的 topic.target,客户的"主品牌".
    brand_target: Optional[str] = None
    is_active: bool = True
    is_admin: bool = False
    topic_count: int
    has_prompt_extension: bool


@router.get("/admin/accounts", response_model=list[AdminAccountSummary])
def admin_list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    from geo.models.user import UserORM
    # 按 id desc 排:UserORM 没有 created_at 字段,id 自增,作为「创建时间」的代理.
    # admin 画像列表希望最新注册的客户排在最前面.
    users = db.query(UserORM).order_by(UserORM.id.desc()).all()
    out: list[AdminAccountSummary] = []
    for u in users:
        topics = (
            db.query(AiTelemetryTopicORM)
              .filter(AiTelemetryTopicORM.user_id == u.id)
              .order_by(AiTelemetryTopicORM.id.asc())
              .all()
        )
        has_ext = any((t.prompt_extension or "").strip() for t in topics)
        first_target = next(
            ((t.target or "").strip() for t in topics if (t.target or "").strip()),
            None,
        )
        out.append(AdminAccountSummary(
            id=u.id,
            email=u.email or "",
            name=getattr(u, "name", None),
            brand_target=first_target,
            is_active=getattr(u, "is_active", True),
            is_admin=bool(getattr(u, "is_admin", False)),
            topic_count=len(topics),
            has_prompt_extension=has_ext,
        ))
    return out


@router.get("/admin/users/{user_id}/topics", response_model=list[TopicOut])
def admin_list_user_topics(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    rows = (
        db.query(AiTelemetryTopicORM)
          .filter_by(user_id=user_id)
          .order_by(AiTelemetryTopicORM.created_at.desc())
          .all()
    )
    return [TopicOut.from_orm_row(r) for r in rows]


@router.get("/admin/runs", response_model=list[AdminRunOut])
def admin_list_runs(
    day: Optional[str] = None,
    user_id: Optional[int] = None,
    topic_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """admin 跨用户 / 跨主题跑批总览。
    - day=YYYY-MM-DD:按当日(UTC)过滤,不传则列最近
    - user_id / topic_id / status:可选过滤
    - 按 started_at DESC 排序,默认 100 条
    """
    _require_admin(current_user)
    from geo.models.user import UserORM
    from sqlalchemy import case

    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    q = (
        db.query(AiTelemetryRunORM, AiTelemetryTopicORM, UserORM)
          .join(AiTelemetryTopicORM, AiTelemetryRunORM.topic_id == AiTelemetryTopicORM.id)
          .join(UserORM, UserORM.id == AiTelemetryTopicORM.user_id)
          .order_by(AiTelemetryRunORM.started_at.desc())
    )
    if day:
        try:
            d = datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "day 必须是 YYYY-MM-DD")
        next_d = d + timedelta(days=1)
        q = q.filter(
            AiTelemetryRunORM.started_at >= d,
            AiTelemetryRunORM.started_at < next_d,
        )
    if user_id is not None:
        q = q.filter(UserORM.id == user_id)
    if topic_id is not None:
        q = q.filter(AiTelemetryRunORM.topic_id == topic_id)
    if status:
        q = q.filter(AiTelemetryRunORM.status == status)
    rows = q.offset(offset).limit(limit).all()

    run_ids = [run.id for run, _, _ in rows]
    stats: dict[int, dict[str, int]] = {}
    if run_ids:
        result = (
            db.query(
                AiTelemetryResponseORM.run_id,
                func.count(AiTelemetryResponseORM.id).label("total"),
                func.sum(case((AiTelemetryResponseORM.hit == True, 1), else_=0)).label("hits"),  # noqa: E712
                func.sum(case((AiTelemetryResponseORM.error.isnot(None), 1), else_=0)).label("errs"),
            )
            .filter(AiTelemetryResponseORM.run_id.in_(run_ids))
            .group_by(AiTelemetryResponseORM.run_id)
            .all()
        )
        for rid, total, hits, errs in result:
            stats[rid] = {
                "total": int(total or 0),
                "hits": int(hits or 0),
                "errs": int(errs or 0),
            }

    out: list[AdminRunOut] = []
    for run, topic, user in rows:
        s = stats.get(run.id, {"total": 0, "hits": 0, "errs": 0})
        out.append(AdminRunOut(
            run_id=run.id,
            topic_id=topic.id,
            topic_name=topic.name,
            topic_target=topic.target or "",
            user_id=user.id,
            user_email=user.email or "",
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            error=run.error,
            response_count=s["total"],
            hit_count=s["hits"],
            error_count=s["errs"],
        ))
    return out


@router.get("/admin/runs/{run_id}", response_model=AdminRunOut)
def admin_get_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """admin 取单条 run 元信息(详情页顶部展示用)。"""
    _require_admin(current_user)
    from geo.models.user import UserORM
    from sqlalchemy import case

    row = (
        db.query(AiTelemetryRunORM, AiTelemetryTopicORM, UserORM)
          .join(AiTelemetryTopicORM, AiTelemetryRunORM.topic_id == AiTelemetryTopicORM.id)
          .join(UserORM, UserORM.id == AiTelemetryTopicORM.user_id)
          .filter(AiTelemetryRunORM.id == run_id)
          .first()
    )
    if not row:
        raise HTTPException(404, "run not found")
    run, topic, user = row

    stats = (
        db.query(
            func.count(AiTelemetryResponseORM.id).label("total"),
            func.sum(case((AiTelemetryResponseORM.hit == True, 1), else_=0)).label("hits"),  # noqa: E712
            func.sum(case((AiTelemetryResponseORM.error.isnot(None), 1), else_=0)).label("errs"),
        )
        .filter(AiTelemetryResponseORM.run_id == run_id)
        .one()
    )

    return AdminRunOut(
        run_id=run.id,
        topic_id=topic.id,
        topic_name=topic.name,
        topic_target=topic.target or "",
        user_id=user.id,
        user_email=user.email or "",
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        error=run.error,
        response_count=int(stats[0] or 0),
        hit_count=int(stats[1] or 0),
        error_count=int(stats[2] or 0),
    )


@router.post(
    "/admin/users/{user_id}/topics",
    response_model=TopicOut,
    status_code=201,
)
def admin_create_topic_for_user(
    user_id: int,
    payload: TopicPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """admin 替指定 user 直接创建主题 — 跳过审核,落库即 approved.

    跟用户走 create_topic + submit-for-review + admin approve 的三段式不同,
    这里一步到位:queries/seeds 全部 status=approved, topic.submission_status=approved.
    """
    _require_admin(current_user)
    from geo.models.user import UserORM
    target_user = db.get(UserORM, user_id)
    if not target_user:
        raise HTTPException(404, "user not found")
    _validate_payload(payload)
    clusters_dump = [c.model_dump() for c in payload.clusters] if payload.clusters else []
    seed_prompts_init = _append_seed_prompts(
        "[]", payload.seed_drafts,
        new_status="approved", reviewer_id=current_user.id,
    )
    profile_init = "{}"
    if payload.profile is not None:
        profile_init = json.dumps(payload.profile.model_dump(), ensure_ascii=False)
    now = datetime.utcnow()
    t = AiTelemetryTopicORM(
        user_id=user_id,
        name=payload.name.strip(),
        target=payload.target,
        target_aliases_json=json.dumps(payload.target_aliases, ensure_ascii=False),
        industry=payload.industry,
        seed_prompts_json=seed_prompts_init,
        queries_json=_queries_with_meta(
            payload.queries, None, payload.query_cluster_ids, payload.query_seeds,
            payload.query_scene_types,
            new_status="approved", reviewer_id=current_user.id,
        ),
        clusters_json=json.dumps(clusters_dump, ensure_ascii=False),
        engines_json=json.dumps(payload.engines, ensure_ascii=False),
        enabled=payload.enabled,
        profile_json=profile_init,
        prompt_extension=payload.prompt_extension,
        submission_status="approved",
        approved_at=now,
        reviewer_id=current_user.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    _append_changelog(
        t, actor_id=current_user.id, actor_role="admin",
        field="submission_status", after="approved",
        note=f"admin created for user {user_id}",
    )
    db.commit()
    db.refresh(t)
    return TopicOut.from_orm_row(t)


@router.get("/topics", response_model=list[TopicOut])
def list_topics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(AiTelemetryTopicORM)
          .filter_by(user_id=current_user.id)
          .order_by(AiTelemetryTopicORM.created_at.desc())
          .all()
    )
    return [TopicOut.from_orm_row(r) for r in rows]


@router.get("/topics/{topic_id}", response_model=TopicOut)
def get_topic(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单条主题元信息 — owner 自取;admin 可取任意主题(品牌增长面板按 ?topic= 解析非自有主题用)。"""
    t = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    return TopicOut.from_orm_row(t)


@router.post("/topics", response_model=TopicOut, status_code=201)
def create_topic(
    payload: TopicPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_payload(payload)
    clusters_dump = [c.model_dump() for c in payload.clusters] if payload.clusters else []
    seed_prompts_init = _append_seed_prompts("[]", payload.seed_drafts)
    profile_init = "{}"
    if payload.profile is not None:
        profile_init = json.dumps(payload.profile.model_dump(), ensure_ascii=False)
    t = AiTelemetryTopicORM(
        user_id=current_user.id,
        name=payload.name.strip(),
        target=payload.target,
        target_aliases_json=json.dumps(payload.target_aliases, ensure_ascii=False),
        industry=payload.industry,
        seed_prompts_json=seed_prompts_init,
        queries_json=_queries_with_meta(
            payload.queries, None, payload.query_cluster_ids, payload.query_seeds,
            payload.query_scene_types,
        ),
        clusters_json=json.dumps(clusters_dump, ensure_ascii=False),
        engines_json=json.dumps(payload.engines, ensure_ascii=False),
        enabled=payload.enabled,
        profile_json=profile_init,
        # admin 自己创建主题也能写 prompt_extension;普通用户即使提交了也忽略
        prompt_extension=(payload.prompt_extension if getattr(current_user, "is_admin", False) else None),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    # 把资料创建动作追加到 changelog(创建时 changelog 还是空,直接补一条)
    if payload.profile is not None:
        _append_changelog(
            t, actor_id=current_user.id, actor_role="user", field="profile",
            after=payload.profile.profile_name or payload.profile.company_short_name,
            note="created with profile",
        )
        db.commit()
        db.refresh(t)
    return TopicOut.from_orm_row(t)


@router.post("/topics/draft", response_model=TopicOut, status_code=201)
def create_draft_topic(
    payload: TopicDraftPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Step1「下一步」即落库 — 只存品牌资料(6 大模块)+ 基础字段,queries/engines 可空,
    submission_status=draft。让用户填完资料就有 topic.id,后续 step 直接增量改,不必拖到最后才一次性保存。
    后续 step3 用 PUT /topics/{id} 补 queries/engines + 提交审核。"""
    # 引擎传了才校验白名单(草稿阶段可空);去重保序
    engines: list[str] = []
    for e in (payload.engines or []):
        if e in VALID_ENGINES and e not in engines:
            engines.append(e)
    name = payload.name.strip()
    target = payload.target.strip()
    industry = payload.industry.strip()
    profile_init = "{}"
    if payload.profile is not None:
        profile_init = json.dumps(payload.profile.model_dump(), ensure_ascii=False)
        # 跟 update_topic_profile 一致:资料里的简称 / 行业 / 名称回填到 topic 顶层字段
        if payload.profile.industry and not industry:
            industry = payload.profile.industry
        if payload.profile.company_short_name and not target:
            target = payload.profile.company_short_name
        if payload.profile.profile_name and not name:
            name = payload.profile.profile_name
    t = AiTelemetryTopicORM(
        user_id=current_user.id,
        name=name or "(unnamed)",
        target=target,
        target_aliases_json=json.dumps(payload.target_aliases, ensure_ascii=False),
        industry=industry,
        seed_prompts_json="[]",
        queries_json="[]",
        engines_json=json.dumps(engines, ensure_ascii=False),
        enabled=payload.enabled,
        profile_json=profile_init,
        submission_status="draft",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    if payload.profile is not None:
        _append_changelog(
            t, actor_id=current_user.id, actor_role="user", field="profile",
            after=payload.profile.profile_name or payload.profile.company_short_name,
            note="draft created with profile",
        )
        db.commit()
        db.refresh(t)
    return TopicOut.from_orm_row(t)


@router.put("/topics/{topic_id}", response_model=TopicOut)
def update_topic(
    topic_id: int,
    payload: TopicPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_payload(payload)
    t = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    # Phase C — 只增不改:approved query 不允许从 payload 消失.
    # 2026-05-31 — admin 编辑时跳过该约束(admin 本来就有 auto-approve 权限,
    # 删 / 改 approved query 应允许;普通用户编辑仍守住,防止绕过审核).
    is_admin_actor = bool(getattr(current_user, "is_admin", False))
    if not is_admin_actor:
        _validate_query_diff(payload.queries, t.queries_json)
    t.name = payload.name.strip()
    t.target = payload.target
    t.target_aliases_json = json.dumps(payload.target_aliases, ensure_ascii=False)
    t.industry = payload.industry
    # Phase D — 编辑时如果带了 profile,就写库 + 记 changelog
    if payload.profile is not None:
        t.profile_json = json.dumps(payload.profile.model_dump(), ensure_ascii=False)
        _append_changelog(
            t, actor_id=current_user.id, actor_role="user", field="profile",
            after=payload.profile.profile_name or payload.profile.company_short_name,
        )
    # Phase C — payload 带 seed_prompt / query 时追加。
    # admin 替别人改主题:新增 seed / query 直接 approved(跳过审核);
    # 普通用户编辑:沿用默认 pending,走审核流程。
    is_admin_actor = bool(getattr(current_user, "is_admin", False))
    new_status = "approved" if is_admin_actor else "pending"
    reviewer_id = current_user.id if is_admin_actor else None
    t.seed_prompts_json = _append_seed_prompts(
        t.seed_prompts_json, payload.seed_drafts,
        new_status=new_status, reviewer_id=reviewer_id,
    )
    t.queries_json = _queries_with_meta(
        payload.queries, t.queries_json, payload.query_cluster_ids, payload.query_seeds,
        payload.query_scene_types,
        new_status=new_status, reviewer_id=reviewer_id,
    )
    # clusters 只在 payload 显式传时才覆盖,避免 PUT 不带 clusters 时把旧簇清掉
    if payload.clusters is not None:
        t.clusters_json = json.dumps(
            [c.model_dump() for c in payload.clusters], ensure_ascii=False,
        )
    t.engines_json = json.dumps(payload.engines, ensure_ascii=False)
    t.enabled = payload.enabled
    # 只 admin 能改 prompt_extension;普通用户的 payload.prompt_extension 一律忽略(不动 DB)
    if getattr(current_user, "is_admin", False) and payload.prompt_extension is not None:
        t.prompt_extension = payload.prompt_extension.strip() or None
    db.commit()
    db.refresh(t)
    return TopicOut.from_orm_row(t)


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = _get_topic_or_404(db, topic_id, current_user.id)
    db.delete(t)
    db.commit()


# ─────────── Phase C — 种子提示词审核固化 ────────────


@router.post("/topics/{topic_id}/seed-prompts", response_model=TopicOut)
def submit_seed_prompt(
    topic_id: int,
    payload: SeedPromptSubmitPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """追加新种子提示词. admin 提交时直接 approved;普通用户提交走 pending → 待审核."""
    t = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    try:
        seeds = json.loads(t.seed_prompts_json or "[]")
    except Exception:  # noqa: BLE001
        seeds = []
    if not isinstance(seeds, list):
        seeds = []
    text = payload.text.strip()
    # 同一 topic 下种子词文本不允许重复
    if any(isinstance(s, dict) and s.get("text") == text for s in seeds):
        raise HTTPException(409, {"code": "DUPLICATE", "message": "种子提示词已存在"})
    is_admin = bool(getattr(current_user, "is_admin", False))
    now_iso = datetime.utcnow().isoformat()
    item: dict = {
        "text": text,
        "status": "approved" if is_admin else "pending",
        "submitted_at": now_iso,
    }
    if is_admin:
        item["approved_at"] = now_iso
        item["reviewer_id"] = current_user.id
    seeds.append(item)
    t.seed_prompts_json = json.dumps(seeds, ensure_ascii=False)
    _append_changelog(
        t, actor_id=current_user.id,
        actor_role="admin" if is_admin else "user",
        field="seed_prompts", after=text,
        note="admin submitted new seed (auto-approved)" if is_admin else "user submitted new seed",
    )

    # 2026-05-26 — admin 提交时种子自动 approved → 立刻派生同名 query
    # (is_seed=True, locked=True, selected=True)。普通用户提交走 pending,等 admin
    # 审批后由 admin_patch_topic 那一路统一派生,这里跳过。
    if is_admin:
        try:
            qarr = json.loads(t.queries_json or "[]")
        except Exception:  # noqa: BLE001
            qarr = []
        q_by_text = {q.get("text"): q for q in qarr if isinstance(q, dict)}
        if text in q_by_text:
            q = q_by_text[text]
            q.update({"is_seed": True, "locked": True,
                      "selected": True, "seed": text})
        else:
            qarr.append({
                "text": text, "status": "approved",
                "submitted_at": now_iso, "approved_at": now_iso,
                "reviewer_id": current_user.id,
                "seed": text, "is_seed": True, "locked": True,
                "selected": True, "cluster_id": -1,
            })
        t.queries_json = json.dumps(qarr, ensure_ascii=False)

    db.commit()
    db.refresh(t)
    return TopicOut.from_orm_row(t)


# ─────────── Phase D — 资料 / 提交审核 / 监测问题勾选 ────────────


def _append_changelog(t: AiTelemetryTopicORM, *, actor_id: int | None, actor_role: str,
                       field: str, before: str | None = None, after: str | None = None,
                       note: str | None = None) -> None:
    """topic_changelog_json 末尾追加一条记录(只增不减)+ version += 1.

    version 自增是审计与"修订号"语义的核心:每条 changelog 条目都对应一个版本,
    `version=N` 即第 N 次"有意义的状态改动"之后的快照。调用方不要绕过这里直接
    改 topic 然后忘记记 changelog。
    """
    try:
        log_arr = json.loads(t.topic_changelog_json or "[]")
    except Exception:  # noqa: BLE001
        log_arr = []
    if not isinstance(log_arr, list):
        log_arr = []
    # version 自增:旧表(migration 之前)可能没这列,getattr 兜底成 1
    new_version = int(getattr(t, "version", 1) or 1) + 1
    t.version = new_version
    entry: dict = {
        "at": datetime.utcnow().isoformat(),
        "actor_id": actor_id,
        "actor_role": actor_role,
        "field": field,
        "version": new_version,
    }
    if before is not None:
        entry["before"] = before[:500]
    if after is not None:
        entry["after"] = after[:500]
    if note is not None:
        entry["note"] = note
    log_arr.append(entry)
    t.topic_changelog_json = json.dumps(log_arr, ensure_ascii=False)


def _append_expansion_log(t: AiTelemetryTopicORM, *, seed: str, model: str,
                           expanded_count: int, raw_excerpt: str,
                           scene: str = "search") -> None:
    """expansion_log_json 末尾追加一条"种子词扩展"的调用记录.

    2026-05-28 起加 scene 字段记录这次扩展走的是哪一维(search/qa/intent/brand).
    legacy log 不带 scene 字段,前端展示时 fallback 到 "search".
    """
    try:
        log_arr = json.loads(t.expansion_log_json or "[]")
    except Exception:  # noqa: BLE001
        log_arr = []
    if not isinstance(log_arr, list):
        log_arr = []
    log_arr.append({
        "at": datetime.utcnow().isoformat(),
        "seed": seed[:200],
        "scene": scene,
        "model": model,
        "expanded_count": int(expanded_count),
        "raw_excerpt": (raw_excerpt or "")[:300],
    })
    t.expansion_log_json = json.dumps(log_arr, ensure_ascii=False)


def _ensure_editable(t: AiTelemetryTopicORM) -> None:
    """资料编辑权限:submission_status ∈ {draft, rejected} 时用户可改;pending/approved 不让动."""
    s = (t.submission_status or "draft")
    if s not in ("draft", "rejected"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LOCKED_STATUS",
                "field": "submission_status",
                "message": f"submission_status={s},不允许编辑;请等待 admin 审核",
            },
        )


def _validate_selected_cap(queries_json_str: str | None) -> None:
    """selected=True 的 query 总数不能超过 MAX_SELECTED_QUERIES."""
    try:
        arr = json.loads(queries_json_str or "[]")
    except Exception:  # noqa: BLE001
        return
    if not isinstance(arr, list):
        return
    n = sum(1 for q in arr if isinstance(q, dict) and bool(q.get("selected", True)))
    if n > MAX_SELECTED_QUERIES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TOO_MANY_SELECTED",
                "field": "queries",
                "message": f"最多勾选 {MAX_SELECTED_QUERIES} 个监测问题,当前 {n}",
            },
        )


@router.put("/topics/{topic_id}/profile", response_model=TopicOut)
def update_topic_profile(
    topic_id: int,
    payload: BrandProfile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新 topic 的品牌资料(6 大模块).只允许在 draft/rejected 状态下改."""
    t = _get_topic_or_404(db, topic_id, current_user.id)
    _ensure_editable(t)
    old_profile_summary = ""
    try:
        old = json.loads(t.profile_json or "{}")
        old_profile_summary = old.get("profile_name") or old.get("company_short_name") or ""
    except Exception:  # noqa: BLE001
        pass
    t.profile_json = json.dumps(payload.model_dump(), ensure_ascii=False)
    # 把 industry / target 也回填到 topic 顶层字段,跟 profile 保持一致
    if payload.industry:
        t.industry = payload.industry
    if payload.company_short_name and not t.target:
        t.target = payload.company_short_name
    if payload.profile_name and (t.name == "" or t.name == "(unnamed)"):
        t.name = payload.profile_name
    _append_changelog(
        t, actor_id=current_user.id, actor_role="user", field="profile",
        before=old_profile_summary or None,
        after=payload.profile_name or payload.company_short_name or None,
    )
    db.commit()
    db.refresh(t)
    return TopicOut.from_orm_row(t)


@router.post("/topics/{topic_id}/selected-queries", response_model=TopicOut)
def update_selected_queries(
    topic_id: int,
    payload: SelectedQueriesPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """根据用户勾选,更新 queries_json 里每条的 `selected` 字段.

    入参 items 用 text 匹配现有 queries — 不在 payload 里的 text 默认 selected=False.
    新文本(payload 里有但 queries_json 没的)直接加进 queries_json,status=pending + selected=值.
    """
    t = _get_topic_or_404(db, topic_id, current_user.id)
    _ensure_editable(t)
    try:
        arr = json.loads(t.queries_json or "[]")
    except Exception:  # noqa: BLE001
        arr = []
    if not isinstance(arr, list):
        arr = []
    # 升级 legacy str → dict
    upgraded: list[dict] = []
    for q in arr:
        if isinstance(q, str):
            upgraded.append({"text": q, "status": "approved", "selected": True})
        elif isinstance(q, dict) and q.get("text"):
            upgraded.append(dict(q))
    by_text = {q["text"]: q for q in upgraded}
    now_iso = datetime.utcnow().isoformat()
    desired_texts: set[str] = set()
    for item in payload.items:
        text = item.text.strip()
        if not text:
            continue
        desired_texts.add(text)
        seed = (getattr(item, "seed", None) or "").strip()[:200]
        scene_type = getattr(item, "scene_type", None) or "search"
        if scene_type not in ALL_SCENES:
            scene_type = "search"
        if text in by_text:
            by_text[text]["selected"] = bool(item.selected)
            # 第一次提交带 seed 时回填;已有非空 seed 不覆盖,避免误改历史归属
            if seed and not by_text[text].get("seed"):
                by_text[text]["seed"] = seed
            # 同理,首次带 scene_type 时回填;legacy item 没字段或为 search 时,
            # 新传的非 search scene 也允许覆盖(legacy 默认 search 不是用户真选的).
            existing_scene = by_text[text].get("scene_type")
            if scene_type != "search" and (not existing_scene or existing_scene == "search"):
                by_text[text]["scene_type"] = scene_type
        else:
            new_q: dict = {
                "text": text,
                "status": "pending",
                "submitted_at": now_iso,
                "selected": bool(item.selected),
                "scene_type": scene_type,
            }
            if seed:
                new_q["seed"] = seed
            upgraded.append(new_q)
            by_text[text] = upgraded[-1]
    # 不在 payload 里的:保留原状态,selected=False — 除非是 locked(种子原文 query)
    for text, q in by_text.items():
        if text not in desired_texts:
            # 2026-05-26 — locked=True 的 query(seed 原文)强制保持 selected=True,
            # 防止前端误传 / 旧 client 把它们刷下来
            if q.get("locked"):
                q["selected"] = True
            else:
                q["selected"] = False
    # 2026-05-26 — locked 的 query 即使在 payload 里被显式 unset 也要保持 selected=True
    for q in upgraded:
        if q.get("locked") and not q.get("selected"):
            q["selected"] = True
    selected_n = sum(1 for q in upgraded if q.get("selected"))
    if selected_n > MAX_SELECTED_QUERIES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TOO_MANY_SELECTED",
                "field": "queries",
                "message": f"最多勾选 {MAX_SELECTED_QUERIES} 个监测问题,当前 {selected_n}",
            },
        )
    t.queries_json = json.dumps(upgraded, ensure_ascii=False)
    _append_changelog(
        t, actor_id=current_user.id, actor_role="user", field="selected_queries",
        after=f"selected_count={selected_n}",
    )
    db.commit()
    db.refresh(t)
    return TopicOut.from_orm_row(t)


@router.post("/topics/{topic_id}/reclassify-queries", response_model=TopicOut)
def reclassify_queries(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """2026-05-28 — 把 topic 的历史 queries 用启发式重新打 scene_type 标签.

    用 query_expander.classify_query(text, target, aliases) 给每条 query 一刀切归类.
    - text 含 target / aliases → brand
    - 含意图词(如何 / 攻略 / 教程 / 怎么选)→ intent
    - 含问答词(哪家 / 怎么样 / 对比 / 吗)→ qa
    - 其余 → search

    幂等可重跑.把已有的 scene_type 覆盖掉(包括之前手动选的也覆盖).
    返回完整 TopicOut(含 query_scene_types[]),前端拿到后刷新 badge.
    """
    from geo.services.query_expander import classify_query

    t = _get_topic_or_404(db, topic_id, current_user.id)
    _ensure_editable(t)
    try:
        arr = json.loads(t.queries_json or "[]")
    except Exception:  # noqa: BLE001
        arr = []
    if not isinstance(arr, list):
        arr = []

    target = (t.target or "").strip()
    try:
        aliases = json.loads(t.target_aliases_json or "[]")
        if not isinstance(aliases, list):
            aliases = []
        aliases = [str(a) for a in aliases if isinstance(a, str)]
    except Exception:  # noqa: BLE001
        aliases = []

    counts: dict[str, int] = {"search": 0, "qa": 0, "intent": 0, "brand": 0}
    changed = 0
    upgraded: list[dict] = []
    for q in arr:
        if isinstance(q, str):
            scene = classify_query(q, target=target, aliases=aliases)
            counts[scene] = counts.get(scene, 0) + 1
            upgraded.append({"text": q, "status": "approved", "selected": True,
                             "scene_type": scene})
            changed += 1
        elif isinstance(q, dict) and q.get("text"):
            new_q = dict(q)
            scene = classify_query(str(q.get("text") or ""), target=target, aliases=aliases)
            counts[scene] = counts.get(scene, 0) + 1
            if new_q.get("scene_type") != scene:
                new_q["scene_type"] = scene
                changed += 1
            upgraded.append(new_q)
    t.queries_json = json.dumps(upgraded, ensure_ascii=False)
    _append_changelog(
        t, actor_id=current_user.id, actor_role="user", field="reclassify_queries",
        after=f"changed={changed} total={len(upgraded)} dist={counts}",
    )
    db.commit()
    db.refresh(t)
    return TopicOut.from_orm_row(t)


# submit-for-review 端点在去审核流里退役.客户不再提交,admin 在工作台直接「启动项目」.
# 校验逻辑下沉到 admin_review.start_topic 的 _validate_topic_runnable.


# ─────────────────────────── Run-now passthrough ──────────────


@router.post("/topics/run-now", response_model=list[RunNowResult])
async def run_now(
    payload: TopicPayload,
    current_user: User = Depends(get_current_user),
):
    """同步调 telemetry-service,把单话题跑一遍,结果直接返回前端 modal.

    不入库 — 这是"试跑预览"语义。每日定时跑批由 telemetry-service 自跑自存。
    """
    _validate_payload(payload)
    url = f"{TELEMETRY_SERVICE_URL}/run-now"
    body = {
        "name": payload.name,
        "queries": payload.queries,
        "engines": payload.engines,
        "user_id": current_user.id,
    }
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(url, json=body)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        log.warning("telemetry-service run-now failed: %s", e)
        raise HTTPException(502, f"telemetry-service unavailable: {e}")


# ─────────────── AI 智能填充 — 原始资料 → 品牌资料 ────────────


# 上传单个文件大小上限 — 10MB。
# 文本抽出后还会被 file_bytes_to_text → MAX_EXTRACTED_TEXT 截断,
# 这个 10MB 主要拦"扔了个几百兆的 PDF"那种意外。
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _do_extract(text: str, user_id: int) -> ProfileExtractOut:
    if not text or len(text.strip()) < 10:
        raise HTTPException(400, "原始资料过短(<10 字符),无法抽取资料")
    if len(text) > MAX_EXTRACTED_TEXT:
        text = text[:MAX_EXTRACTED_TEXT]
    try:
        profile, seed_suggestions, model_id = extract_profile_from_text(text)
    except Exception as e:  # noqa: BLE001
        log.warning("profile extract failed for user %s: %s", user_id, e)
        raise HTTPException(502, f"AI 解析失败: {e}")
    if not model_id:
        raise HTTPException(503, "未配置 DEEPSEEK_API_KEY / OPENROUTER_API_KEY,AI 智能填充不可用")
    return ProfileExtractOut(
        profile=profile, used_model=model_id, seed_suggestions=seed_suggestions,
    )


@router.post("/profile/extract", response_model=ProfileExtractOut)
def extract_profile_endpoint(
    payload: ProfileExtractPayload,
    current_user: User = Depends(get_current_user),
):
    """JSON 路径 — 用户粘贴的原始文本(textarea)走这里。

    文件类(PDF / Word / TXT 等)走 /profile/extract-file。
    503 = 后端没配 DEEPSEEK_API_KEY 或 OPENROUTER_API_KEY。
    """
    return _do_extract(payload.text, current_user.id)


@router.post("/profile/extract-file", response_model=ProfileExtractOut)
async def extract_profile_file_endpoint(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Multipart 路径 — 拖入 PDF / Word / 纯文本文件。

    流程:UploadFile → bytes → 按后缀分发解析器 → 抽出文本 → 同一条
    LLM pipeline。前端 form field 名:`file`。

    400 = 文件太大 / 空文件 / 文本太短
    415 = .doc 旧格式或扫描件 PDF 抽不到字
    502 = LLM 调用失败
    503 = 后端 LLM key 未配
    """
    if not file or not file.filename:
        raise HTTPException(400, "请上传一个文件")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "文件为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            400,
            f"文件过大({len(raw) // 1024} KB > {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限)",
        )
    try:
        text = file_bytes_to_text(file.filename, raw)
    except FileParseError as e:
        raise HTTPException(415, str(e))
    return _do_extract(text, current_user.id)


# ─────────────── Topic 媒体素材(图片 / 视频)— 资料上传 弹窗用 ──────────
#
# 资料上传:文本类走 /profile/extract*,LLM 抽完直接回填表单,不持久化;
# 媒体类(图片/视频)走本节 — 落 data/topic_media/{topic_id}/{uuid}.ext + DB 登记,
# 后续生稿 / 发文时引用。

MEDIA_DIR_NAME = "topic_media"
MAX_MEDIA_BYTES = 50 * 1024 * 1024   # 单文件 50 MB,视频也够用
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
ALLOWED_MEDIA_EXTS = ALLOWED_IMAGE_EXTS | ALLOWED_VIDEO_EXTS


def _media_root() -> Path:
    # 沿用项目 data/ 目录约定(DATABASE_URL 默认 sqlite:///./data/geo_checker.db)
    root = Path(os.environ.get("GEO_DATA_DIR") or "./data") / MEDIA_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _serialize_media(m: TopicMediaORM) -> TopicMediaOut:
    return TopicMediaOut(
        id=m.id, topic_id=m.topic_id,
        filename=m.filename or "", kind=m.kind or "image",
        mime=m.mime or "", size=m.size or 0,
        url=f"/api/ai-telemetry/topics/{m.topic_id}/media/{m.id}/blob",
        uploaded_at=m.uploaded_at,
    )


@router.get("/topics/{topic_id}/media", response_model=list[TopicMediaOut])
def list_topic_media(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_topic_or_404(db, topic_id, current_user.id)
    rows = (
        db.query(TopicMediaORM)
          .filter_by(topic_id=topic_id, user_id=current_user.id)
          .order_by(TopicMediaORM.uploaded_at.desc())
          .all()
    )
    return [_serialize_media(m) for m in rows]


@router.post("/topics/{topic_id}/media", response_model=TopicMediaOut, status_code=201)
async def upload_topic_media(
    topic_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """资料上传 — 图片 / 视频。

    400 = 缺文件 / 空 / 太大
    415 = 后缀不在白名单(.jpg/.png/.mp4/...)
    """
    _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    if not file or not file.filename:
        raise HTTPException(400, "请上传一个文件")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_MEDIA_EXTS:
        raise HTTPException(415, f"不支持的格式 {ext or '未知'};只接受图片(.jpg/.png/.gif/.webp)与视频(.mp4/.mov/.webm)")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "文件为空")
    if len(raw) > MAX_MEDIA_BYTES:
        raise HTTPException(
            400,
            f"文件过大({len(raw) // 1024 // 1024} MB > {MAX_MEDIA_BYTES // 1024 // 1024} MB 上限)",
        )
    kind = "video" if ext in ALLOWED_VIDEO_EXTS else "image"
    mime = file.content_type or mimetypes.guess_type(file.filename)[0] or ""

    topic_dir = _media_root() / str(topic_id)
    topic_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = topic_dir / stored_name
    stored_path.write_bytes(raw)

    row = TopicMediaORM(
        topic_id=topic_id, user_id=current_user.id,
        filename=file.filename[:255], kind=kind, mime=mime[:128],
        size=len(raw), storage_path=str(stored_path),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_media(row)


@router.get("/public/topic-media/{topic_id}/{filename}")
def get_topic_media_public(topic_id: int, filename: str):
    """2026-05-28 — 公开图片/视频访问端点,**无需 Bearer auth**.

    URL 含 32 hex UUID 文件名(128 bit 熵,不可猜测),靠 UUID 提供 obscurity-style 保护.
    LLM 生成稿件用这个 URL 嵌入 markdown ![](url),浏览器 / 公众号 / 知乎都能渲染.

    安全约束:
      - filename 必须是合法的 32 hex + 扩展名格式(防遍历 / 注入)
      - 路径必须落在 data/topic_media/{topic_id}/ 内
      - 文件必须存在
    """
    # 简单校验:filename = 32hex + dot + 2~4 char extension
    import re as _re
    if not _re.fullmatch(r"[a-f0-9]{32}\.[a-zA-Z0-9]{2,5}", filename):
        raise HTTPException(404, "media not found")
    p = _media_root() / str(topic_id) / filename
    # 防 path traversal:确保 resolved path 真的在 _media_root() 下
    try:
        p_real = p.resolve()
        root_real = _media_root().resolve()
        if not str(p_real).startswith(str(root_real) + os.sep):
            raise HTTPException(404, "media not found")
    except Exception:  # noqa: BLE001
        raise HTTPException(404, "media not found")
    if not p_real.exists() or not p_real.is_file():
        raise HTTPException(404, "media not found")
    mime, _ = mimetypes.guess_type(str(p_real))
    return FileResponse(p_real, media_type=mime or "application/octet-stream",
                        filename=p_real.name)


@router.get("/topics/{topic_id}/media/{media_id}/blob")
def get_topic_media_blob(
    topic_id: int,
    media_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """流式回吐媒体文件 — 仅 topic owner 可读."""
    _get_topic_or_404(db, topic_id, current_user.id)
    row = db.get(TopicMediaORM, media_id)
    if not row or row.topic_id != topic_id or row.user_id != current_user.id:
        raise HTTPException(404, "media not found")
    p = Path(row.storage_path)
    if not p.exists():
        raise HTTPException(410, "文件已丢失")
    return FileResponse(p, media_type=row.mime or "application/octet-stream",
                        filename=row.filename or p.name)


@router.delete("/topics/{topic_id}/media/{media_id}", status_code=204)
def delete_topic_media(
    topic_id: int,
    media_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_topic_or_404(db, topic_id, current_user.id)
    row = db.get(TopicMediaORM, media_id)
    if not row or row.topic_id != topic_id or row.user_id != current_user.id:
        raise HTTPException(404, "media not found")
    p = Path(row.storage_path)
    try:
        if p.exists():
            p.unlink()
    except OSError as e:
        log.warning("failed to unlink media file %s: %s", p, e)
    db.delete(row)
    db.commit()


# ─────────────── 候选 query 生成(DeepSeek)— 建话题时用 ───────────


def _parse_suggest_args(payload: dict) -> dict:
    """解析 /suggest-queries[/stream] 的 body → 规整后的参数 dict。
    普通版和 SSE 流式版共用,避免两处解析漂移。"""
    seed = (payload.get("seed") or "").strip()
    if not seed:
        raise HTTPException(400, "seed cannot be empty")
    # scene 子集校验
    raw_scenes = payload.get("scenes")
    if raw_scenes is None:
        scenes: list[str] = list(ALL_SCENES)
    elif isinstance(raw_scenes, list):
        scenes = [s for s in raw_scenes if isinstance(s, str)]
    else:
        raise HTTPException(400, "scenes must be an array")
    invalid = [s for s in scenes if s not in ALL_SCENES]
    if invalid:
        raise HTTPException(400, f"invalid scenes: {invalid}")
    if not scenes:
        raise HTTPException(400, "at least one scene must be selected")
    # 每场景产出数:default 50,兼容老 count
    cap_per_scene = max(5, MAX_EXPANSION_CANDIDATES // len(ALL_SCENES))
    if "count_per_scene" in payload:
        try:
            count_per_scene = int(payload["count_per_scene"])
        except (TypeError, ValueError):
            count_per_scene = cap_per_scene
    elif "count" in payload:
        try:
            count_per_scene = max(5, int(payload["count"]) // len(ALL_SCENES))
        except (TypeError, ValueError):
            count_per_scene = cap_per_scene
    else:
        count_per_scene = cap_per_scene
    count_per_scene = max(5, min(count_per_scene, cap_per_scene))

    aliases_in = payload.get("aliases") or []
    if not isinstance(aliases_in, list):
        aliases_in = []

    def _list_from_payload(key: str, *, max_items: int = 20, per_max: int = 300) -> list[str]:
        raw = payload.get(key)
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for x in raw:
            s = str(x or "").strip()
            if s:
                out.append(s[:per_max])
            if len(out) >= max_items:
                break
        return out

    return {
        "seed": seed,
        "scenes": scenes,
        "count_per_scene": count_per_scene,
        "target": (payload.get("target") or "").strip(),
        "industry": (payload.get("industry") or "").strip(),
        "entity_type": (payload.get("entity_type") or "").strip()[:32],
        "service_geo": (payload.get("service_geo") or "").strip()[:200],
        "aliases": [str(a).strip() for a in aliases_in if str(a).strip()][:20],
        "profile_cases": _list_from_payload("profile_cases", max_items=20, per_max=300),
        "core_credentials": _list_from_payload("core_credentials", max_items=20, per_max=300),
        "brand_diff_tags": _list_from_payload("brand_diff_tags", max_items=10, per_max=80),
        "core_service_overview": (payload.get("core_service_overview") or "").strip()[:500],
    }


async def _expand_scene_call(scene: str, args: dict, client):
    """按 args 调一次单场景扩展;两个端点共用同一套入参,避免漏传字段。"""
    return await expand_one_scene(
        scene=scene, seed=args["seed"], count=args["count_per_scene"],
        target=args["target"], aliases=args["aliases"],
        industry=args["industry"], service_geo=args["service_geo"],
        entity_type=args["entity_type"],
        profile_cases=args["profile_cases"],
        core_credentials=args["core_credentials"],
        brand_diff_tags=args["brand_diff_tags"],
        core_service_overview=args["core_service_overview"],
        client=client,
    )


@router.post("/suggest-queries")
async def suggest_queries(
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    """种子主题 → 候选 query(4 维场景扩展).前端 picker 多选回填。

    2026-05-28 起改成本地 4 维 fan-out(同 /topics/{id}/expand-queries),不再透传 telemetry-service.
    建话题阶段还没有 topic id,所以这个端点比 /expand-queries 早一步用,二者共享 query_expander.

    body:
      seed:              str   种子词
      scenes:            list  ["search","qa","intent","brand"](默认全 4)
      count_per_scene:   int   每场景产出条数,默认 50(每维 50 × 4 维 = 200)
      target:            str   品牌全称(brand 场景需要,空则跳过 brand)
      aliases:           list  品牌别名
      industry:          str   行业上下文
      service_geo:       str   服务地域(可作为关键词前缀)
      count:             int   兼容老调用方:若没传 count_per_scene 则用 count/4

    resp:
      {
        "seed":  str,
        "total_count": int,
        "scenes": {
          "search": {"queries":[...], "model":"...", "error":null|"..."},
          "qa":     {...},
          "intent": {...},
          "brand":  {...}
        },
        // 老调用方兼容:queries 字段是 4 场景产出的平铺合集,顺序 search→qa→intent→brand
        "queries": [str, ...]
      }
    """
    args = _parse_suggest_args(payload)
    seed = args["seed"]
    scenes = args["scenes"]
    target = args["target"]

    # brand 场景在 target 为空时无意义 —— 跳过
    runnable_scenes: list[str] = []
    scene_results: dict[str, dict] = {}
    for s in scenes:
        if s == "brand" and not target:
            scene_results[s] = {
                "queries": [],
                "error": "brand scene requires a brand name (target field is empty)",
            }
        else:
            runnable_scenes.append(s)

    # 4 路并行 fan-out — 画像字段按场景差异化注入(intent / brand)
    if runnable_scenes:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            tasks = [_expand_scene_call(s, args, client) for s in runnable_scenes]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        for s, res in zip(runnable_scenes, results):
            if isinstance(res, Exception):
                scene_results[s] = {"queries": [], "error": str(res)[:300]}
            else:
                scene_results[s] = res

    # 聚合:每条 query 打上 scene 字段(供前端在 picker 上分组渲染),并提供平铺 queries 列表保 老调用方兼容
    flat_queries: list[dict] = []
    total_count = 0
    for s in ALL_SCENES:
        info = scene_results.get(s) or {}
        qs = info.get("queries") or []
        for q in qs:
            flat_queries.append({"text": q, "score": 0, "sources": [], "scene": s})
        total_count += len(qs)

    return {
        "seed": seed,
        "total_count": total_count,
        "scenes": scene_results,
        # 老调用方平铺数组兼容:每项含 scene 字段
        "queries": flat_queries,
    }


@router.post("/suggest-queries/stream")
async def suggest_queries_stream(
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    """SSE 流式版 /suggest-queries:4 场景并行,哪个场景先生成完就先推一帧,前端边收边渲染,
    不必等整包(慢模型下体验差别明显)。提示词 / 解析与普通版完全一致,只是把结果改成逐场景流出。

    事件(均为 `data: <json>\\n\\n`):
      {"type":"scene","scene":"search","queries":[{text,score,sources,scene}],"model":..,"error":..}
      {"type":"done","total": N}
    """
    args = _parse_suggest_args(payload)
    scenes = args["scenes"]
    target = args["target"]

    runnable: list[str] = []
    skipped: dict[str, str] = {}
    for s in scenes:
        if s == "brand" and not target:
            skipped[s] = "brand scene requires a brand name (target field is empty)"
        else:
            runnable.append(s)

    def _sse(obj: dict) -> str:
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def gen():
        total = 0
        # 先把跳过的场景(brand 无 target)作为一帧推出去,前端立即知道它不跑
        for s, err in skipped.items():
            yield _sse({"type": "scene", "scene": s, "queries": [], "error": err})
        if runnable:
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    async def _labeled(scene: str):
                        try:
                            res = await _expand_scene_call(scene, args, client)
                            return scene, res
                        except Exception as e:  # noqa: BLE001
                            return scene, {"queries": [], "error": str(e)[:300]}
                    for fut in asyncio.as_completed([_labeled(s) for s in runnable]):
                        scene, res = await fut
                        qs = res.get("queries") or []
                        total += len(qs)
                        items = [
                            {"text": q, "score": 0, "sources": [], "scene": scene}
                            for q in qs
                        ]
                        yield _sse({
                            "type": "scene", "scene": scene, "queries": items,
                            "model": res.get("model"), "error": res.get("error"),
                        })
            except Exception as e:  # noqa: BLE001
                yield _sse({"type": "error", "error": str(e)[:300]})
        yield _sse({"type": "done", "total": total})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关掉 nginx 缓冲,SSE 才能逐帧到前端
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/topics/{topic_id}/expand-queries")
async def expand_queries_for_topic(
    topic_id: int, payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase D + 2026-05-28 — 4 维场景扩展.

    body:
      seed:              str   种子词(中性,不带场景)
      scenes:            list  ["search","qa","intent","brand"](默认全 4)
      count_per_scene:   int   每场景产出 ≤ 50,合计 ≤ MAX_EXPANSION_CANDIDATES
      count:             int   兼容老入参(被忽略,优先 count_per_scene)

    resp v2:
      {
        "seed":  str,
        "total_count": int,
        "scenes": {
          "search": {"queries":[...], "model":"deepseek-chat", "error":null|"..."},
          "qa":     {...},
          "intent": {...},
          "brand":  {...}
        }
      }

    扩展候选不直接落 queries_json — 前端拿到后让用户勾选,再调 /selected-queries.
    brand 场景在 target 为空时会自动跳过(返回 error),其他 3 个场景并行不受影响.
    """
    t = _get_topic_or_404(db, topic_id, current_user.id)
    _ensure_editable(t)
    seed = (payload.get("seed") or "").strip()
    if not seed:
        raise HTTPException(400, "seed cannot be empty")

    # scene 子集校验
    raw_scenes = payload.get("scenes")
    if raw_scenes is None:
        scenes: list[str] = list(ALL_SCENES)
    elif isinstance(raw_scenes, list):
        scenes = [s for s in raw_scenes if isinstance(s, str)]
    else:
        raise HTTPException(400, "scenes must be an array")
    invalid = [s for s in scenes if s not in ALL_SCENES]
    if invalid:
        raise HTTPException(400, f"invalid scenes: {invalid}")
    if not scenes:
        raise HTTPException(400, "at least one scene must be selected")

    # 每场景产出数:上限 = MAX_EXPANSION_CANDIDATES / 4 = 50(对齐老上限,每维 50,4 维合 200)
    cap_per_scene = max(5, MAX_EXPANSION_CANDIDATES // len(ALL_SCENES))
    try:
        count_per_scene = int(payload.get("count_per_scene", cap_per_scene))
    except (TypeError, ValueError):
        count_per_scene = cap_per_scene
    count_per_scene = max(5, min(count_per_scene, cap_per_scene))

    target = (t.target or "").strip()
    industry = t.industry or ""
    try:
        aliases = json.loads(t.target_aliases_json or "[]")
    except Exception:  # noqa: BLE001
        aliases = []
    # 2026-05-28 — 从 topic profile 自动注入画像字段,按场景差异化使用:
    #   search / qa: 只用 service_geo(行业从 t.industry 走)
    #   intent:      额外用 case_stories
    #   brand:       全用(case_stories / core_credentials / brand_diff_tags / core_service_overview)
    service_geo = ""
    entity_type = ""
    profile_cases: list[str] = []
    core_credentials: list[str] = []
    brand_diff_tags: list[str] = []
    core_service_overview = ""
    try:
        profile_obj = json.loads(t.profile_json or "{}")
        if isinstance(profile_obj, dict):
            service_geo = str(profile_obj.get("service_geo") or "").strip()[:200]
            entity_type = str(profile_obj.get("entity_type") or "").strip()[:32]
            core_service_overview = str(profile_obj.get("core_service_overview") or "").strip()
            for s in (profile_obj.get("case_stories") or []):
                s2 = str(s or "").strip()
                if s2:
                    profile_cases.append(s2[:300])
            for s in (profile_obj.get("core_credentials") or []):
                s2 = str(s or "").strip()
                if s2:
                    core_credentials.append(s2[:300])
            for s in (profile_obj.get("brand_diff_tags") or []):
                s2 = str(s or "").strip()
                if s2:
                    brand_diff_tags.append(s2[:80])
    except Exception:  # noqa: BLE001
        pass

    # brand 场景在 target 为空时无意义 —— 跳过(返回 error 给前端展示)
    runnable_scenes: list[str] = []
    scene_results: dict[str, dict] = {}
    for s in scenes:
        if s == "brand" and not target:
            scene_results[s] = {
                "queries": [],
                "error": "brand scene requires a brand name (target field is empty)",
            }
        else:
            runnable_scenes.append(s)

    # 4 路并行 fan-out — 画像字段按场景差异化注入
    if runnable_scenes:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            tasks = [
                expand_one_scene(
                    scene=s, seed=seed, count=count_per_scene,
                    target=target, aliases=aliases,
                    industry=industry, service_geo=service_geo,
                    entity_type=entity_type,
                    # intent / brand 才用得到这些 — render_prompt 内会按 scene 决定是否注入
                    profile_cases=profile_cases,
                    core_credentials=core_credentials,
                    brand_diff_tags=brand_diff_tags,
                    core_service_overview=core_service_overview,
                    client=client,
                )
                for s in runnable_scenes
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        for s, res in zip(runnable_scenes, results):
            if isinstance(res, Exception):
                scene_results[s] = {"queries": [], "error": str(res)[:300]}
            else:
                scene_results[s] = res

    # 聚合 + 写 expansion_log_json(每场景 1 条 log)
    total_count = 0
    for s in scenes:
        info = scene_results.get(s) or {}
        qs = info.get("queries") or []
        total_count += len(qs)
        excerpt = ", ".join(qs[:3])
        _append_expansion_log(
            t, seed=seed,
            model=info.get("model") or "deepseek",
            expanded_count=len(qs), raw_excerpt=excerpt,
            scene=s,
        )
    db.commit()

    return {
        "seed": seed,
        "total_count": total_count,
        "scenes": scene_results,
    }


# ─────────────────────────── Trigger run + result queries ─────


@router.post("/topics/{topic_id}/run", status_code=202)
async def trigger_run(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """触发一次正式跑批入库,立刻返回(202).结果通过 GET /topics/{id}/runs 轮询."""
    _get_topic_or_404(db, topic_id, current_user.id)
    url = f"{TELEMETRY_SERVICE_URL}/run-topic"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={"topic_id": topic_id})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        log.warning("telemetry-service /run-topic failed: %s", e)
        raise HTTPException(502, f"telemetry-service unavailable: {e}")


@router.get("/topics/{topic_id}/runs", response_model=list[RunOut])
def list_runs(
    topic_id: int,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_topic_or_404(db, topic_id, current_user.id)
    rows = (
        db.query(AiTelemetryRunORM)
          .filter_by(topic_id=topic_id)
          .order_by(AiTelemetryRunORM.id.desc())
          .limit(min(limit, 100))
          .all()
    )
    # response counts in one query
    counts = dict(
        db.query(AiTelemetryResponseORM.run_id, func.count(AiTelemetryResponseORM.id))
          .filter(AiTelemetryResponseORM.run_id.in_([r.id for r in rows]))
          .group_by(AiTelemetryResponseORM.run_id)
          .all()
    ) if rows else {}
    return [RunOut.from_orm_row(r, response_count=counts.get(r.id, 0)) for r in rows]


@router.get("/topics/{topic_id}/overview", response_model=OverviewOut)
def topic_overview(
    topic_id: int,
    period: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """概览页聚合 — 4 KPI 卡 + 每日引擎趋势 series.

    KPI 口径:
      - visibility = (Response.hit=True 的成功 response 数 / 总成功 response 数) × 100
      - citations = sum(len(citations_json)) 周期内所有 response
      - growth = citations 相对上一周期的 pct change
      - engines_covered = 本期有 ≥1 成功 response 的引擎数 / topic.engines 总数
    品牌词来源:topic.target + topic.target_aliases_json(与 runner 落 hit 时同源).
    """
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    now = datetime.utcnow()
    period_days, period_start = _resolve_period(period, topic, now)
    prev_start = period_start - timedelta(days=period_days)

    # 品牌词:用 topic 自己的检测词,与 runner detect_hit 同源
    brand_keywords: list[str] = []
    if topic.target:
        brand_keywords.append(topic.target)
    brand_keywords.extend(json.loads(topic.target_aliases_json or "[]"))
    brand_keywords = [k for k in brand_keywords if k]
    brand_lc = [k.lower() for k in brand_keywords]

    topic_engines = json.loads(topic.engines_json or "[]")
    engines_total = len(topic_engines)

    rows_curr = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .filter(AiTelemetryResponseORM.created_at >= period_start)
          .all()
    )
    rows_prev = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .filter(AiTelemetryResponseORM.created_at >= prev_start)
          .filter(AiTelemetryResponseORM.created_at < period_start)
          .all()
    )

    def _aggregate(rows: list[AiTelemetryResponseORM]) -> dict:
        cit_total = 0
        mention_hit = 0
        succ_engines: set[str] = set()
        total = 0
        for r in rows:
            cits = json.loads(r.citations_json or "[]")
            cit_total += len(cits)
            if not r.error:
                total += 1
                succ_engines.add(r.engine)
                if r.hit:
                    mention_hit += 1
        visibility = (mention_hit / total * 100) if total > 0 else 0.0
        return {
            "citations": cit_total,
            "visibility": round(visibility, 1),
            "engines": len(succ_engines),
            "succ_total": total,
        }

    curr = _aggregate(rows_curr)
    prev = _aggregate(rows_prev)

    def _delta(curr_val: float, prev_val: float) -> Optional[float]:
        if prev_val == 0:
            return None
        return round((curr_val - prev_val) / prev_val * 100, 1)

    # 每日 trend: date -> {engine: citation_count} + 每日 hit/total 计 visibility 曲线
    bucket: dict[str, dict[str, int]] = {}
    day_succ: dict[str, int] = {}
    day_hit: dict[str, int] = {}
    engines_in_window: set[str] = set()
    for r in rows_curr:
        d = r.created_at.strftime("%Y-%m-%d")
        if d not in bucket:
            bucket[d] = {}
        cits = json.loads(r.citations_json or "[]")
        bucket[d][r.engine] = bucket[d].get(r.engine, 0) + len(cits)
        engines_in_window.add(r.engine)
        if not r.error:
            day_succ[d] = day_succ.get(d, 0) + 1
            if r.hit:
                day_hit[d] = day_hit.get(d, 0) + 1

    # 填补缺失日期为空,保证 sparkline 连续
    trend: list[TrendPoint] = []
    sparkline_cit: list[float] = []
    sparkline_vis: list[float] = []
    for i in range(period_days):
        d = (period_start + timedelta(days=i)).strftime("%Y-%m-%d")
        day_vals = bucket.get(d, {})
        trend.append(TrendPoint(date=d, values=day_vals))
        sparkline_cit.append(float(sum(day_vals.values())))
        succ = day_succ.get(d, 0)
        sparkline_vis.append(round(day_hit.get(d, 0) / succ * 100, 1) if succ > 0 else 0.0)

    # ── 引用分析:Top domains + owned/other + engine×domain 矩阵 ──
    def _domain_stats(rows: list[AiTelemetryResponseORM]) -> tuple[dict[str, int], int, int, dict[str, dict[str, int]], dict[str, dict[str, int]]]:
        """返回 (domain_total_count, owned_count, total_cit_count, engine_domain[engine][domain] = count, engine_factor[engine][factor] = count)."""
        domain_count: dict[str, int] = {}
        owned = 0
        total = 0
        engine_domain: dict[str, dict[str, int]] = {}
        engine_factor: dict[str, dict[str, int]] = {}   # engine -> {GEO 因子: count}
        for r in rows:
            if r.error:
                continue
            cits = json.loads(r.citations_json or "[]")
            for c in cits:
                d = (c.get("domain") or "").lower().strip()
                if not d:
                    continue
                domain_count[d] = domain_count.get(d, 0) + 1
                total += 1
                eng = engine_domain.setdefault(r.engine, {})
                eng[d] = eng.get(d, 0) + 1
                is_owned = bool(brand_lc and any(k in d for k in brand_lc))
                if is_owned:
                    owned += 1
                # GEO 因子二次分析:按 标题 + url 归因(FirstPageSage 口径)
                factor = classify_factor(c.get("url") or "", c.get("title") or "", d, owned=is_owned)
                efac = engine_factor.setdefault(r.engine, {})
                efac[factor] = efac.get(factor, 0) + 1
        return domain_count, owned, total, engine_domain, engine_factor

    curr_domains, curr_owned, curr_total_cit, curr_engine_domain, curr_engine_factor = _domain_stats(rows_curr)
    _, prev_owned, prev_total_cit, _, _ = _domain_stats(rows_prev)

    top_n = sorted(curr_domains.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    top_domains_out = [
        DomainCount(
            domain=d, count=c,
            pct=round(c / curr_total_cit * 100, 1) if curr_total_cit > 0 else 0.0,
        )
        for d, c in top_n
    ]
    top_set = {d for d, _ in top_n}

    # 只保留 top domains 的 engine 矩阵,前端 heatmap 用
    engine_domain_filtered: dict[str, dict[str, int]] = {}
    for eng, dom_map in curr_engine_domain.items():
        engine_domain_filtered[eng] = {d: c for d, c in dom_map.items() if d in top_set}

    curr_owned_pct = round(curr_owned / curr_total_cit * 100, 1) if curr_total_cit > 0 else 0.0
    prev_owned_pct = (prev_owned / prev_total_cit * 100) if prev_total_cit > 0 else 0.0
    owned_split = OwnedSplit(
        owned=curr_owned,
        other=curr_total_cit - curr_owned,
        owned_pct=curr_owned_pct,
        delta_pct=_delta(curr_owned_pct, prev_owned_pct),
    )

    return OverviewOut(
        topic_id=topic_id,
        period_days=period_days,
        brand_keywords=brand_keywords,
        visibility=KpiBlock(
            value=curr["visibility"],
            delta_pct=_delta(curr["visibility"], prev["visibility"]),
            sparkline=sparkline_vis,
        ),
        citations=KpiBlock(
            value=float(curr["citations"]),
            delta_pct=_delta(curr["citations"], prev["citations"]),
            sparkline=sparkline_cit,
        ),
        growth=KpiBlock(
            value=_delta(curr["citations"], prev["citations"]) or 0.0,
            delta_pct=None,
            sparkline=[],
        ),
        engines_covered=KpiBlock(
            value=float(curr["engines"]),
            delta_pct=_delta(curr["engines"], prev["engines"]),
            sparkline=[],
        ),
        engines_total=engines_total,
        trend=trend,
        engines=sorted(engines_in_window),
        top_domains=top_domains_out,
        owned_split=owned_split,
        engine_domain_matrix=engine_domain_filtered,
        engine_factor_matrix=curr_engine_factor,
    )


@router.get("/topics/{topic_id}/intent-breakdown", response_model=IntentBreakdownOut)
def topic_intent_breakdown(
    topic_id: int,
    period: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按 picker 端聚出的 cluster_id 把本期 response 分组,出每簇 mention / citation 率。

    话题 queries_json 里没有 cluster_id(老话题或聚类失败时全 0)就只有一个簇,
    或者 query 文本与 cluster_id 对不上时落到 uncategorized 桶。
    """
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    period_days, period_start = _resolve_period(period, topic)

    # 品牌词(沿用 overview 口径:topic.target + aliases,与 runner detect_hit 同源)
    brand_keywords: list[str] = []
    if topic.target:
        brand_keywords.append(topic.target)
    brand_keywords.extend(json.loads(topic.target_aliases_json or "[]"))
    brand_keywords = [k for k in brand_keywords if k]

    # query → cluster_id 映射
    queries_raw = json.loads(topic.queries_json or "[]")
    query_to_cluster: dict[str, int] = {}
    query_count_by_cluster: dict[int, int] = {}
    for q in queries_raw:
        if isinstance(q, dict):
            text = q.get("text") or ""
            cid = q.get("cluster_id")
            cid_int = int(cid) if isinstance(cid, int) else -1
        elif isinstance(q, str):
            text, cid_int = q, -1
        else:
            continue
        if not text:
            continue
        query_to_cluster[text] = cid_int
        query_count_by_cluster[cid_int] = query_count_by_cluster.get(cid_int, 0) + 1

    # 簇标签
    clusters_raw = json.loads(topic.clusters_json or "[]")
    cluster_labels: dict[int, str] = {}
    cluster_order: list[int] = []
    for c in clusters_raw:
        if isinstance(c, dict) and "cluster_id" in c:
            cid = int(c["cluster_id"])
            cluster_labels[cid] = c.get("label") or f"cluster_{cid}"
            cluster_order.append(cid)

    rows = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .filter(AiTelemetryResponseORM.created_at >= period_start)
          .all()
    )

    # 按 cluster_id 聚合 response 维度
    agg: dict[int, dict] = {}
    for r in rows:
        if r.error:
            continue
        cid = query_to_cluster.get(r.query, -1)
        bucket = agg.setdefault(cid, {"response": 0, "mention": 0, "citation": 0})
        bucket["response"] += 1
        if r.hit:
            bucket["mention"] += 1
        bucket["citation"] += len(json.loads(r.citations_json or "[]"))

    def _mk(cid: int, label: str) -> ClusterBreakdownItem:
        b = agg.get(cid, {"response": 0, "mention": 0, "citation": 0})
        return ClusterBreakdownItem(
            cluster_id=cid,
            label=label,
            query_count=query_count_by_cluster.get(cid, 0),
            response_count=b["response"],
            mention_count=b["mention"],
            mention_rate=round(b["mention"] / b["response"], 3) if b["response"] else 0.0,
            citation_count=b["citation"],
        )

    # 按 size 降序排出有名簇,无标签 / 老话题落到 uncategorized
    out_clusters: list[ClusterBreakdownItem] = []
    seen_cids: set[int] = set()
    for cid in cluster_order:
        out_clusters.append(_mk(cid, cluster_labels[cid]))
        seen_cids.add(cid)
    out_clusters.sort(key=lambda c: c.query_count, reverse=True)

    uncat_b = agg.get(-1, {"response": 0, "mention": 0, "citation": 0})
    # 把所有 query 没对上簇的 response 累到 uncategorized
    for cid, b in agg.items():
        if cid != -1 and cid not in seen_cids:
            uncat_b["response"] += b["response"]
            uncat_b["mention"] += b["mention"]
            uncat_b["citation"] += b["citation"]
    uncat = ClusterBreakdownItem(
        cluster_id=-1,
        label="uncategorized",
        query_count=query_count_by_cluster.get(-1, 0)
                  + sum(c for cid, c in query_count_by_cluster.items()
                        if cid not in seen_cids and cid != -1),
        response_count=uncat_b["response"],
        mention_count=uncat_b["mention"],
        mention_rate=round(uncat_b["mention"] / uncat_b["response"], 3)
                   if uncat_b["response"] else 0.0,
        citation_count=uncat_b["citation"],
    )

    return IntentBreakdownOut(
        topic_id=topic_id,
        period_days=period_days,
        brand_keywords=brand_keywords,
        clusters=out_clusters,
        uncategorized=uncat,
    )


def _clean_citations_for_out(raw: str | None) -> list[dict]:
    """从 citations_json 解出 list,补全 domain / title — 老 response 可能缺字段,
    直接喂给 RunNowCitation 会 pydantic 校验失败 (端点 500)。
    """
    from urllib.parse import urlparse
    try:
        items = json.loads(raw or "[]")
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for c in items:
        if not isinstance(c, dict):
            continue
        url = (c.get("url") or "").strip()
        if not url:
            continue
        domain = (c.get("domain") or "").strip()
        if not domain:
            try:
                domain = urlparse(url).netloc
            except Exception:  # noqa: BLE001
                domain = ""
        out.append({
            "url": url,
            "domain": domain,
            "title": (c.get("title") or "").strip(),
        })
    return out


@router.get("/runs/{run_id}/responses", response_model=list[ResponseOut])
def list_responses(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.get(AiTelemetryRunORM, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    topic = db.get(AiTelemetryTopicORM, run.topic_id)
    if not topic:
        raise HTTPException(404, "run not found")
    if topic.user_id != current_user.id and not getattr(current_user, "is_admin", False):
        raise HTTPException(404, "run not found")
    rows = (
        db.query(AiTelemetryResponseORM)
          .filter_by(run_id=run_id)
          .order_by(AiTelemetryResponseORM.id.asc())
          .all()
    )
    out = []
    for r in rows:
        out.append(ResponseOut(
            id=r.id, engine=r.engine, query=r.query,
            answer=r.answer, citations=_clean_citations_for_out(r.citations_json),
            video_url=r.video_url, source_url=r.source_url, error=r.error,
            created_at=r.created_at,
            hit=bool(r.hit), hit_excerpt=r.hit_excerpt,
            mention_position=r.mention_position, brand_rank=r.brand_rank,
        ))
    return out


@router.get("/topics/{topic_id}/responses", response_model=list[ResponseOut])
def list_topic_responses(
    topic_id: int,
    engine: Optional[str] = None,
    domain: Optional[str] = None,
    query: Optional[str] = None,
    period: int = 30,
    limit: int = 200,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """topic 维度的 responses 列表 — 给品牌增长子页(信源 / 平台 / 关键词)下钻用。

    - engine: 单引擎筛选
    - domain: 命中该域(citation_domains_json 含)
    - query: 锁定单 query
    - period: 近 N 天(1-90)
    """
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    _, cutoff = _resolve_period(period, topic)

    q = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .filter(AiTelemetryResponseORM.created_at >= cutoff)
    )
    if engine:
        q = q.filter(AiTelemetryResponseORM.engine == engine)
    if query:
        q = q.filter(AiTelemetryResponseORM.query == query)
    rows = q.order_by(AiTelemetryResponseORM.created_at.desc()).limit(max(1, min(limit, 500))).all()

    # domain 过滤走应用层 — citation_domains_json 是 JSON list,跨方言 LIKE 不可靠
    if domain:
        d = domain.strip().lower()
        filtered = []
        for r in rows:
            try:
                doms = json.loads(r.citation_domains_json or "[]")
            except Exception:  # noqa: BLE001
                doms = []
            if any(d == (x or "").strip().lower() for x in doms):
                filtered.append(r)
        rows = filtered

    out = []
    for r in rows:
        out.append(ResponseOut(
            id=r.id, engine=r.engine, query=r.query,
            answer=r.answer, citations=_clean_citations_for_out(r.citations_json),
            video_url=r.video_url, source_url=r.source_url, error=r.error,
            created_at=r.created_at,
            hit=bool(r.hit), hit_excerpt=r.hit_excerpt,
            mention_position=r.mention_position, brand_rank=r.brand_rank,
        ))
    return out


# ─────────────────── v1 引用追踪 ──────────────────────────


def _cell_to_out(c: AiTelemetryQueryHitORM) -> QueryHitCell:
    return QueryHitCell(
        query=c.query, engine=c.engine, status=c.status,
        first_hit_at=c.first_hit_at,
        first_hit_response_id=c.first_hit_response_id,
        last_checked_at=c.last_checked_at,
        total_runs=c.total_runs or 0, total_hits=c.total_hits or 0,
    )


@router.get("/topics/{topic_id}/tracking-matrix", response_model=TrackingMatrixOut)
def get_tracking_matrix(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """v1 引用追踪 — 整个 topic 的 (query × engine) 矩阵 + 首次命中时间线."""
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    queries_raw = json.loads(topic.queries_json or "[]")
    queries: list[str] = []
    for q in queries_raw:
        if isinstance(q, dict):
            t = q.get("text") or ""
            if t:
                queries.append(t)
        elif isinstance(q, str):
            queries.append(q)
    engines: list[str] = json.loads(topic.engines_json or "[]")
    target_aliases: list[str] = json.loads(topic.target_aliases_json or "[]")

    cell_rows = (
        db.query(AiTelemetryQueryHitORM)
          .filter(AiTelemetryQueryHitORM.topic_id == topic_id)
          .all()
    )
    by_key: dict[tuple[str, str], AiTelemetryQueryHitORM] = {
        (c.query, c.engine): c for c in cell_rows
    }

    # 2026-05-26 — 扫 responses 聚合每个 cell 命中过的 target / alias 列表。
    # 用于前端「按命中词筛选」。
    #
    # Compound alias 匹配规则(2026-05-26 v2):
    #   • 单词 alias(如「程晓峰」):答复含此字面 → 命中
    #   • Compound alias(含分隔符 & + | ＆ ｜ 和 与 或):拆成多个 part,
    #     **所有 part 都在答复里出现**(任意位置、任意顺序、任意中间字符)→ 命中
    #     例:alias「竞天公诚 & 程晓峰」,答复「...竞天公诚｜程晓峰(合伙人)...」
    #         拆成 ["竞天公诚", "程晓峰"],两 part 都在 answer → 算命中此 compound alias
    #     这样不论实际答复用什么分隔符,只要两边都提到了就识别为「品牌+人物」复合命中。
    #
    # 子串去重:用「长串先匹 + 匹中后替换 haystack」机制,避免「竞天程晓峰」(target)
    # 出现时把内部「程晓峰」也算上。
    import re
    _SEPARATOR_RE = re.compile(r"\s*[&+|＆｜和与或]\s*|\s+")

    def _split_compound(term: str) -> list[str]:
        """alias 含分隔符就拆 part,否则返回单元素。"""
        parts = [p.strip() for p in _SEPARATOR_RE.split(term) if p.strip()]
        return parts if len(parts) >= 2 else [term]

    raw_terms = [topic.target.strip()] + [a.strip() for a in target_aliases]
    seen_terms: set[str] = set()
    hit_terms_pool: list[tuple[str, list[str]]] = []  # (display_term, parts_to_match)
    for t in raw_terms:
        if t and t not in seen_terms:
            seen_terms.add(t)
            hit_terms_pool.append((t, _split_compound(t)))
    # 排序:compound(part 多)优先,再按字符长度倒序
    hit_terms_pool.sort(key=lambda x: (len(x[1]), len(x[0])), reverse=True)

    aliases_hit_by_cell: dict[tuple[str, str], set[str]] = {}
    if hit_terms_pool:
        hit_resp_rows = (
            db.query(AiTelemetryResponseORM.query, AiTelemetryResponseORM.engine,
                     AiTelemetryResponseORM.hit_excerpt, AiTelemetryResponseORM.answer)
              .filter(AiTelemetryResponseORM.topic_id == topic_id)
              .filter(AiTelemetryResponseORM.hit.is_(True))  # noqa: E712
              .all()
        )
        for r in hit_resp_rows:
            key = (r.query, r.engine)
            bucket = aliases_hit_by_cell.setdefault(key, set())
            haystack = (r.hit_excerpt or r.answer or "").lower()
            if not haystack:
                continue
            for term, parts in hit_terms_pool:
                parts_low = [p.lower() for p in parts]
                if all(p in haystack for p in parts_low):
                    bucket.add(term)
                    # 抠掉 part(避免被更小的子 alias 重复计)
                    for p in parts_low:
                        haystack = haystack.replace(p, " ")

    # 填充所有 (query × engine) — 未跑过的 cell 给 pending 占位(不入库,只 in-memory 返回)
    cells: list[QueryHitCell] = []
    for q in queries:
        for e in engines:
            c = by_key.get((q, e))
            aliases_hit = sorted(aliases_hit_by_cell.get((q, e), set()))
            if c is not None:
                cell_out = _cell_to_out(c)
                cell_out.aliases_hit = aliases_hit
                cells.append(cell_out)
            else:
                cells.append(QueryHitCell(
                    query=q, engine=e, status="pending",
                    first_hit_at=None, first_hit_response_id=None,
                    last_checked_at=None, total_runs=0, total_hits=0,
                    aliases_hit=[],
                ))

    # 时间线 — 每个 engine 在所有 query 里最早 first_hit_at
    timeline: list[EngineFirstHit] = []
    for e in engines:
        best: AiTelemetryQueryHitORM | None = None
        for c in cell_rows:
            if c.engine != e:
                continue
            if c.first_hit_at is None:
                continue
            if best is None or (c.first_hit_at < best.first_hit_at):
                best = c
        if best is None:
            timeline.append(EngineFirstHit(
                engine=e, first_hit_at=None, first_hit_query=None, days_after_start=None,
            ))
        else:
            days = (best.first_hit_at - topic.created_at).days if topic.created_at else None
            timeline.append(EngineFirstHit(
                engine=e, first_hit_at=best.first_hit_at,
                first_hit_query=best.query,
                days_after_start=max(0, days) if days is not None else None,
            ))

    # KPI
    total_cells = len(queries) * len(engines)
    hit_cells = sum(1 for c in cells if c.total_hits >= 1)
    hit_pct = round(hit_cells / total_cells * 100, 1) if total_cells > 0 else 0.0

    total_runs = (
        db.query(func.count(AiTelemetryRunORM.id))
          .filter(AiTelemetryRunORM.topic_id == topic_id)
          .scalar() or 0
    )

    return TrackingMatrixOut(
        topic_id=topic_id,
        target=topic.target or topic.name or "",
        target_aliases=target_aliases,
        queries=queries,
        engines=engines,
        started_at=topic.created_at,
        cells=cells,
        timeline=timeline,
        total_runs=int(total_runs),
        total_cells=total_cells,
        hit_cells=hit_cells,
        hit_cells_pct=hit_pct,
    )


@router.get("/topics/{topic_id}/growth-report", response_model=GrowthReportOut)
def get_growth_report(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """增长报告 — 逐条监测问题对比「首次跑批结果」与「当前累计结果」。

    口径:
      baseline = 该 topic 时间最早的一次 run 的全部 responses。
      current  = 该 topic 历史全部 responses(累计)。
    每条问题聚合:命中 = 任一引擎命中;排名 = 命中里最好的 brand_rank;
    引擎 = 命中过的引擎集合。status 反映从首跑到现在的变化。
    """
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)

    # 监测问题集合 + 种子映射(与 tracking-matrix 同源:取所有 query 文本)
    queries_raw = json.loads(topic.queries_json or "[]")
    queries: list[str] = []
    seed_of: dict[str, str] = {}
    for q in queries_raw:
        if isinstance(q, dict):
            txt = q.get("text") or ""
            if txt:
                queries.append(txt)
                if q.get("seed"):
                    seed_of[txt] = q["seed"]
        elif isinstance(q, str) and q:
            queries.append(q)
    query_set = set(queries)

    # 首次跑批
    first_run = (
        db.query(AiTelemetryRunORM)
          .filter(AiTelemetryRunORM.topic_id == topic_id)
          .order_by(AiTelemetryRunORM.id.asc())
          .first()
    )
    has_baseline = first_run is not None

    baseline_rows = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.run_id == first_run.id)
          .all()
    ) if first_run else []
    current_rows = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .all()
    )

    # 当前不可用 / 已停用的引擎 — 报告里完全不计入(命中、排名、覆盖、引擎列表都剔除)。
    # 2026-06:元宝(yuanbao)暂不可用,先排除。
    excluded_engines = {"yuanbao"}

    def _group(rows: list[AiTelemetryResponseORM]) -> dict[str, list[AiTelemetryResponseORM]]:
        g: dict[str, list[AiTelemetryResponseORM]] = {}
        for r in rows:
            if r.query in query_set and r.engine not in excluded_engines:
                g.setdefault(r.query, []).append(r)
        return g

    base_g = _group(baseline_rows)
    curr_g = _group(current_rows)

    def _agg(rows: list[AiTelemetryResponseORM]) -> tuple[bool, Optional[int], list[str]]:
        """returns (hit, best_rank, engines_hit)."""
        hit = False
        best_rank: Optional[int] = None
        engines: set[str] = set()
        for r in rows:
            if r.hit:
                hit = True
                engines.add(r.engine)
                if r.brand_rank is not None:
                    best_rank = r.brand_rank if best_rank is None else min(best_rank, r.brand_rank)
        return hit, best_rank, sorted(engines)

    def _status(b_hit: bool, b_rank: Optional[int], c_hit: bool, c_rank: Optional[int]) -> str:
        if c_hit and not b_hit:
            return "new_hit"
        if c_hit and b_hit:
            if b_rank is not None and c_rank is not None:
                if c_rank < b_rank:
                    return "improved"
                if c_rank > b_rank:
                    return "regressed"
            return "steady"
        if b_hit and not c_hit:
            return "regressed"
        return "still_miss"

    rows_out: list[GrowthQueryRow] = []
    for q in queries:
        b_hit, b_rank, b_eng = _agg(base_g.get(q, []))
        c_hit, c_rank, c_eng = _agg(curr_g.get(q, []))
        rows_out.append(GrowthQueryRow(
            query=q, seed=seed_of.get(q),
            baseline_hit=b_hit, baseline_rank=b_rank, baseline_engines=b_eng,
            current_hit=c_hit, current_rank=c_rank, current_engines=c_eng,
            status=_status(b_hit, b_rank, c_hit, c_rank),
        ))

    def _snapshot(grouped: dict[str, list[AiTelemetryResponseORM]], run_at) -> GrowthSnapshot:
        total = len(queries)
        hit_count = 0
        ranks: list[int] = []
        engines: set[str] = set()
        for q in queries:
            hit, rank, eng = _agg(grouped.get(q, []))
            if hit:
                hit_count += 1
                engines.update(eng)
                if rank is not None:
                    ranks.append(rank)
        return GrowthSnapshot(
            run_at=run_at,
            queries_total=total,
            queries_hit=hit_count,
            hit_rate_pct=round(hit_count / total * 100, 1) if total else 0.0,
            avg_rank=round(sum(ranks) / len(ranks), 2) if ranks else None,
            engines_covered=len(engines),
        )

    return GrowthReportOut(
        topic_id=topic_id,
        target=topic.target or topic.name or "",
        generated_at=datetime.utcnow(),
        has_baseline=has_baseline,
        baseline=_snapshot(base_g, first_run.started_at if first_run else None),
        current=_snapshot(curr_g, datetime.utcnow()),
        rows=rows_out,
    )


@router.get("/topics/{topic_id}/share-of-voice", response_model=ShareOfVoiceOut)
def get_share_of_voice(
    topic_id: int, period: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """v1.3 SAIV(Share of AI Voice)聚合 — 品牌 vs 竞品 提及次数对比.

    口径(近 period 天):
      brand_count = COUNT(Response WHERE hit=True)
      competitors[name].count = SUM(competitors_json[*].count) 按 name 聚合
      saiv_pct = brand / (brand + sum(competitors)) × 100
      position_dist = COUNT(Response GROUP BY mention_position) 仅 hit=True
      optimal_rate_pct = SUM(QueryHit.total_hits) / SUM(QueryHit.total_runs) × 100
    """
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    period_days, cutoff = _resolve_period(period, topic)

    rows = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .filter(AiTelemetryResponseORM.created_at >= cutoff)
          .all()
    )

    brand_count = 0
    competitors_map: dict[str, int] = {}
    pos = {"lead": 0, "body": 0, "tail": 0, "unknown": 0}
    for r in rows:
        if r.error:
            continue
        if r.hit:
            brand_count += 1
            p = (r.mention_position or "unknown").lower()
            if p not in pos:
                p = "unknown"
            pos[p] += 1
        if r.competitors_json:
            try:
                arr = json.loads(r.competitors_json or "[]")
            except Exception:  # noqa: BLE001
                arr = []
            for c in arr:
                if not isinstance(c, dict):
                    continue
                name = (c.get("name") or "").strip()
                cnt = int(c.get("count") or 0)
                if name and cnt > 0:
                    competitors_map[name] = competitors_map.get(name, 0) + cnt

    comp_total = sum(competitors_map.values())
    total = brand_count + comp_total
    saiv_pct = round(brand_count / total * 100, 1) if total > 0 else 0.0

    top_comps = sorted(competitors_map.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    comp_entries = [
        CompetitorShareEntry(
            name=name, count=cnt,
            pct=round(cnt / total * 100, 1) if total > 0 else 0.0,
        )
        for name, cnt in top_comps
    ]

    # 优选率 = sum(QueryHit.total_hits) / sum(QueryHit.total_runs)
    qh_rows = (
        db.query(AiTelemetryQueryHitORM)
          .filter(AiTelemetryQueryHitORM.topic_id == topic_id)
          .all()
    )
    sum_hits = sum((c.total_hits or 0) for c in qh_rows)
    sum_runs = sum((c.total_runs or 0) for c in qh_rows)
    optimal_pct = round(sum_hits / sum_runs * 100, 1) if sum_runs > 0 else 0.0

    total_runs = (
        db.query(func.count(AiTelemetryRunORM.id))
          .filter(AiTelemetryRunORM.topic_id == topic_id)
          .scalar() or 0
    )

    return ShareOfVoiceOut(
        topic_id=topic_id,
        target=topic.target or topic.name or "",
        period_days=period_days,
        brand_count=brand_count,
        competitors_count_total=comp_total,
        saiv_pct=saiv_pct,
        competitors=comp_entries,
        position_dist=PositionDist(**pos),
        optimal_rate_pct=optimal_pct,
        total_runs=int(total_runs),
        sample_size=len(rows),
    )


def _norm_url(u: str) -> str:
    """URL 归一化:小写 scheme+host,去尾斜杠,保留 path/query。"""
    if not u:
        return ""
    u = u.strip()
    try:
        p = _urlparse(u)
        host = p.netloc.lower()
        path = p.path.rstrip("/") or "/"
        q = ("?" + p.query) if p.query else ""
        return f"{p.scheme.lower()}://{host}{path}{q}"
    except Exception:
        return u


def _load_owned_urls(db: Session, topic_id: int) -> set[str]:
    """加载某主题"已发布自有文章"的归一化 URL 集合(用于信源占比分子判定)。"""
    docs = (
        db.query(TopicGeneratedDocORM)
          .filter(
              TopicGeneratedDocORM.topic_id == topic_id,
              TopicGeneratedDocORM.status == "published",
          )
          .all()
    )
    owned: set[str] = set()
    for d in docs:
        try:
            tgts = json.loads(d.publish_targets_json or "[]")
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(tgts, list):
            continue
        for t in tgts:
            if isinstance(t, dict):
                url = t.get("url") or ""
                if url:
                    owned.add(_norm_url(url))
    return owned


def _aggregate_position_breakdown(
    rows: list[AiTelemetryResponseORM], total_queries: int, total_engines: int,
    *,
    allowed_queries: Optional[set[str]] = None,
    allowed_engines: Optional[set[str]] = None,
    owned_urls: Optional[set[str]] = None,
    query_to_seed: Optional[dict[str, str]] = None,
    approved_seeds: Optional[set[str]] = None,
) -> PositionBreakdown:
    """口径:cell × lifetime 维度。

    可见占比 — 基于 N×M:
      - visible_pct = COUNT(cell with any hit) / (N×M)

    Top3/5 占比 — 命中后排名分布(分母改为命中 cell 数,避免被未命中格子稀释):
      - top3_pct    = COUNT(cell with MIN(brand_rank)≤3) / COUNT(cell with any hit)
      - top5_pct    = COUNT(cell with MIN(brand_rank)≤5) / COUNT(cell with any hit)
      - 若 visible=0,top3/5_pct = 0

    source_pct(信源占比,2026-05-21 改口径)— 自有文章被引用密度:
      - 分母 = 命中响应的 citation URL 归一化去重数(只看 hit=True)
      - 分子 = 全部响应里 citation URL ∈ owned_urls 的条目数(不去重,
              包括 hit=False 但引了自有 URL 的响应)
      - owned_urls=None 或为空 → source_pct=0
      - 因分母去重 / 分子计次,该值可能 > 100%

    seed_coverage_pct(种子覆盖率)— 至少 1 条扩展 query 有 hit 的 approved 种子占比:
      - 分母 = approved_seeds 数(从 topic.seed_prompts_json 取 status=approved 的种子)
      - 分子 = 在 approved_seeds 集合内、有任一扩展 query 在本切片里 hit=True 的种子数
      - query_to_seed:query 文本 → 种子文本(从 topic.queries_json 的 seed 字段建)
      - approved_seeds=None / 空 → seed_coverage_pct=0
    """
    # (query, engine) → {hit: bool, min_rank: int|None}
    cells: dict[tuple[str, str], dict] = {}
    denom_urls: set[str] = set()       # 命中响应的引用 URL 去重(信源占比分母)
    owned_cit_count = 0                # 全部响应里 owned URL 出现条目数(信源占比分子,不去重)
    has_owned = bool(owned_urls)
    seeds_with_hit: set[str] = set()   # 本切片内已命中过的种子
    has_seed_index = bool(approved_seeds and query_to_seed)
    for r in rows:
        if r.error:
            continue
        if allowed_queries is not None and r.query not in allowed_queries:
            continue
        if allowed_engines is not None and r.engine not in allowed_engines:
            continue
        key = (r.query, r.engine)
        c = cells.setdefault(key, {"hit": False, "min_rank": None})
        if has_seed_index and r.hit:
            seed = (query_to_seed or {}).get(r.query)
            if seed and seed in (approved_seeds or set()):
                seeds_with_hit.add(seed)
        # 解析 citations(信源占比要用 — 即便不 hit 也要扫 owned)
        try:
            cits = json.loads(r.citations_json or "[]")
        except Exception:  # noqa: BLE001
            cits = []
        urls_norm: list[str] = []
        if isinstance(cits, list):
            for cit in cits:
                if not isinstance(cit, dict):
                    continue
                u = cit.get("url") or ""
                if u:
                    urls_norm.append(_norm_url(u))
        if r.hit:
            c["hit"] = True
            for nu in urls_norm:
                denom_urls.add(nu)
        if has_owned:
            for nu in urls_norm:
                if nu in owned_urls:
                    owned_cit_count += 1
        rank = r.brand_rank
        if isinstance(rank, int) and rank >= 1:
            if c["min_rank"] is None or rank < c["min_rank"]:
                c["min_rank"] = rank

    total_cells = total_queries * total_engines
    if total_cells == 0:
        return PositionBreakdown()

    top3 = sum(1 for c in cells.values() if c["min_rank"] is not None and c["min_rank"] <= 3)
    top5 = sum(1 for c in cells.values() if c["min_rank"] is not None and c["min_rank"] <= 5)
    visible = sum(1 for c in cells.values() if c["hit"])
    source_pct = (owned_cit_count / len(denom_urls) * 100) if denom_urls else 0.0
    seed_coverage_pct = (
        len(seeds_with_hit) / len(approved_seeds) * 100
        if approved_seeds else 0.0
    )
    return PositionBreakdown(
        top3_pct=round(top3 / visible * 100, 2) if visible else 0.0,
        top5_pct=round(top5 / visible * 100, 2) if visible else 0.0,
        visible_pct=round(visible / total_cells * 100, 2),
        source_pct=round(source_pct, 2),
        seed_coverage_pct=round(seed_coverage_pct, 2),
    )


@router.get("/topics/{topic_id}/position-breakdown", response_model=PositionBreakdownOut)
def get_position_breakdown(
    topic_id: int, period: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """雷达 5 维 + 右核心指标卡 — 基于 brand_rank 聚合。

    返回本期 breakdown + 行业基准(样本不足时 industry_baseline = None)。
    """
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    # period 参数保留是为了向后兼容(前端可能仍在传),但在 lifetime 口径下不再使用。
    period_days = max(1, min(period, 90))

    rows = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .all()
    )

    try:
        queries_raw = json.loads(topic.queries_json or "[]")
    except Exception:  # noqa: BLE001
        queries_raw = []
    total_queries = 0
    query_to_seed: dict[str, str] = {}
    for q in queries_raw:
        if isinstance(q, str) and q.strip():
            total_queries += 1
        elif isinstance(q, dict) and (q.get("text") or "").strip():
            total_queries += 1
            seed_txt = (q.get("seed") or "").strip()
            if seed_txt:
                query_to_seed[q["text"].strip()] = seed_txt
    try:
        engines_raw = json.loads(topic.engines_json or "[]")
    except Exception:  # noqa: BLE001
        engines_raw = []
    engines_list = [e.strip() for e in engines_raw if isinstance(e, str) and e.strip()]
    total_engines = len(engines_list)

    owned_urls = _load_owned_urls(db, topic_id)
    approved_seeds: set[str] = set()
    try:
        for s in json.loads(topic.seed_prompts_json or "[]"):
            if isinstance(s, dict) and s.get("status") == "approved":
                txt = (s.get("text") or "").strip()
                if txt:
                    approved_seeds.add(txt)
    except Exception:  # noqa: BLE001
        pass

    # 全 Query 组 + 各 engine 切片(用于模型多选对比)
    query_overall = _aggregate_position_breakdown(
        rows, total_queries, total_engines, owned_urls=owned_urls,
        query_to_seed=query_to_seed, approved_seeds=approved_seeds,
    )
    query_by_engine: list[EngineSlice] = []
    for eng in engines_list:
        eng_breakdown = _aggregate_position_breakdown(
            rows, total_queries, 1, allowed_engines={eng}, owned_urls=owned_urls,
            query_to_seed=query_to_seed, approved_seeds=approved_seeds,
        )
        query_by_engine.append(EngineSlice(
            engine=eng, breakdown=eng_breakdown, total_queries=total_queries,
        ))
    query_group = GroupBreakdown(
        scope="query",
        total_queries=total_queries,
        total_engines=total_engines,
        total_cells=total_queries * total_engines,
        breakdown=query_overall,
        by_engine=query_by_engine,
    )

    industry = (topic.industry or "").strip()
    industry_baseline = _compute_industry_baseline(db, industry) if industry else None

    return PositionBreakdownOut(
        topic_id=topic_id,
        period_days=period_days,
        industry=industry,
        total_cells=total_queries * total_engines,
        total_queries=total_queries,
        breakdown=query_overall,
        industry_baseline=industry_baseline,
        query_group=query_group,
        engines=engines_list,
    )


MIN_INDUSTRY_BASELINE_SAMPLES = 3


def _compute_industry_baseline(
    db: Session, industry: str,
) -> Optional[PositionBreakdown]:
    """跨租户聚 industry 内所有 topic 的 P50 breakdown(lifetime 口径,不切 period)。

    样本量 <3 个 topic 返回 None(前端不渲染基准多边形 / 行业小字),避免 mock。
    """
    if not industry:
        return None
    topics = (
        db.query(AiTelemetryTopicORM)
          .filter(AiTelemetryTopicORM.industry == industry)
          .all()
    )
    if len(topics) < MIN_INDUSTRY_BASELINE_SAMPLES:
        return None

    per_topic: list[PositionBreakdown] = []
    for t in topics:
        rows = (
            db.query(AiTelemetryResponseORM)
              .filter(AiTelemetryResponseORM.topic_id == t.id)
              .all()
        )
        if not rows:
            continue
        try:
            queries_raw = json.loads(t.queries_json or "[]")
        except Exception:  # noqa: BLE001
            queries_raw = []
        tq = 0
        q2s: dict[str, str] = {}
        for q in queries_raw:
            if isinstance(q, str) and q.strip():
                tq += 1
            elif isinstance(q, dict) and (q.get("text") or "").strip():
                tq += 1
                seed_txt = (q.get("seed") or "").strip()
                if seed_txt:
                    q2s[q["text"].strip()] = seed_txt
        try:
            engines_raw = json.loads(t.engines_json or "[]")
        except Exception:  # noqa: BLE001
            engines_raw = []
        te = sum(1 for e in engines_raw if isinstance(e, str) and e.strip())
        if tq == 0 or te == 0:
            continue
        owned_t = _load_owned_urls(db, t.id)
        approved_t: set[str] = set()
        try:
            for s in json.loads(t.seed_prompts_json or "[]"):
                if isinstance(s, dict) and s.get("status") == "approved":
                    txt = (s.get("text") or "").strip()
                    if txt:
                        approved_t.add(txt)
        except Exception:  # noqa: BLE001
            pass
        per_topic.append(_aggregate_position_breakdown(
            rows, tq, te, owned_urls=owned_t,
            query_to_seed=q2s, approved_seeds=approved_t,
        ))

    if len(per_topic) < MIN_INDUSTRY_BASELINE_SAMPLES:
        return None

    def _p50(values: list[float]) -> float:
        s = sorted(values)
        n = len(s)
        if n == 0:
            return 0.0
        if n % 2 == 1:
            return s[n // 2]
        return round((s[n // 2 - 1] + s[n // 2]) / 2, 2)

    return PositionBreakdown(
        top3_pct=_p50([b.top3_pct for b in per_topic]),
        top5_pct=_p50([b.top5_pct for b in per_topic]),
        visible_pct=_p50([b.visible_pct for b in per_topic]),
        source_pct=_p50([b.source_pct for b in per_topic]),
        seed_coverage_pct=_p50([b.seed_coverage_pct for b in per_topic]),
    )


@router.get("/benchmarks/industry", response_model=IndustryBenchmarkOut)
def get_industry_benchmark(
    industry: str, period: int = 30,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    db: Session = Depends(get_db),
):
    """跨租户行业基准 — 样本不足返回 breakdown=None。"""
    industry_clean = (industry or "").strip()
    period_days = max(1, min(period, 90))
    sample_topics = (
        db.query(func.count(AiTelemetryTopicORM.id))
          .filter(AiTelemetryTopicORM.industry == industry_clean)
          .scalar() or 0
    )
    # period 参数保留是向后兼容,行业基准已改 lifetime 口径
    _ = period_days
    breakdown = _compute_industry_baseline(db, industry_clean) if industry_clean else None
    return IndustryBenchmarkOut(
        industry=industry_clean,
        sample_size=int(sample_topics),
        breakdown=breakdown,
    )


@router.get("/topics/{topic_id}/competitor-substitutions", response_model=CompetitorSubstitutionOut)
def get_competitor_substitutions(
    topic_id: int, period: int = 30,
    competitor: Optional[str] = None, limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """C3 "被替代证据" — 提了竞品但没提我的 query 列表。

    口径:近 period 天内,(query, engine) 维度下 hit=False(未命中本品)
          但 competitors_json 非空的 responses;按 query × competitor 聚 count。
    """
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    period_days, cutoff = _resolve_period(period, topic)

    rows = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .filter(AiTelemetryResponseORM.created_at >= cutoff)
          .filter(AiTelemetryResponseORM.hit == False)  # noqa: E712
          .filter(AiTelemetryResponseORM.error.is_(None))
          .filter(AiTelemetryResponseORM.competitors_json.isnot(None))
          .all()
    )

    # (query, competitor_name) -> {count, sample_response_id, sample_snippet}
    agg: dict[tuple[str, str], dict] = {}
    for r in rows:
        try:
            comps = json.loads(r.competitors_json or "[]")
        except Exception:  # noqa: BLE001
            continue
        for c in comps:
            if not isinstance(c, dict):
                continue
            name = (c.get("name") or "").strip()
            cnt = int(c.get("count") or 0)
            snippet = (c.get("snippet") or "")[:200]
            if not name or cnt <= 0:
                continue
            if competitor and competitor.strip() and name != competitor.strip():
                continue
            key = (r.query, name)
            cur = agg.get(key)
            if cur is None:
                agg[key] = {
                    "count": cnt,
                    "sample_response_id": r.id,
                    "sample_snippet": snippet,
                }
            else:
                cur["count"] += cnt

    items = [
        CompetitorSubstitutionItem(
            query=q, competitor_name=name,
            competitor_count=v["count"],
            sample_response_id=v["sample_response_id"],
            sample_snippet=v["sample_snippet"],
        )
        for (q, name), v in agg.items()
    ]
    items.sort(key=lambda x: (-x.competitor_count, x.query, x.competitor_name))
    return CompetitorSubstitutionOut(
        topic_id=topic_id, period_days=period_days,
        competitor_filter=(competitor.strip() if competitor else None),
        items=items[:limit], total=len(items),
    )


@router.get("/topics/{topic_id}/cells/drawer", response_model=CellDrawerOut)
def get_cell_drawer(
    topic_id: int, query: str, engine: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单个 cell drawer — 状态 + 历次答复(最近 N 条).

    诊断块 insight 不在这里取(那是 LLM 调用 / 按需触发),由前端单独 POST /cell-insight 拉.
    """
    topic = _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    cell = (
        db.query(AiTelemetryQueryHitORM)
          .filter(AiTelemetryQueryHitORM.topic_id == topic_id)
          .filter(AiTelemetryQueryHitORM.query == query)
          .filter(AiTelemetryQueryHitORM.engine == engine)
          .one_or_none()
    )
    if cell is None:
        cell_out = QueryHitCell(
            query=query, engine=engine, status="pending",
            first_hit_at=None, first_hit_response_id=None,
            last_checked_at=None, total_runs=0, total_hits=0,
        )
    else:
        cell_out = _cell_to_out(cell)

    resp_rows = (
        db.query(AiTelemetryResponseORM)
          .filter(AiTelemetryResponseORM.topic_id == topic_id)
          .filter(AiTelemetryResponseORM.query == query)
          .filter(AiTelemetryResponseORM.engine == engine)
          .order_by(AiTelemetryResponseORM.created_at.desc())
          .limit(min(limit, 30))
          .all()
    )
    evidence = [
        CellEvidence(
            response_id=r.id, run_id=r.run_id, created_at=r.created_at,
            engine=r.engine, query=r.query,
            hit=bool(r.hit), hit_excerpt=r.hit_excerpt,
            mention_position=r.mention_position,
            source_url=r.source_url, answer=r.answer or "",
            citations=[RunNowCitation(**c) for c in json.loads(r.citations_json or "[]")],
        )
        for r in resp_rows
    ]

    # 已有 insight (最新) — 不强制生成
    insight_row = (
        db.query(AiTelemetryCellInsightORM)
          .filter(AiTelemetryCellInsightORM.topic_id == topic_id)
          .filter(AiTelemetryCellInsightORM.query == query)
          .filter(AiTelemetryCellInsightORM.engine == engine)
          .order_by(AiTelemetryCellInsightORM.generated_at.desc())
          .first()
    )
    insight_out = _insight_orm_to_out(insight_row) if insight_row else None

    return CellDrawerOut(cell=cell_out, evidence=evidence, insight=insight_out)


def _insight_orm_to_out(r: AiTelemetryCellInsightORM) -> CellInsightOut:
    comps_raw = json.loads(r.competitors_top3_json or "[]")
    recs_raw = json.loads(r.recommendations_json or "[]")
    return CellInsightOut(
        id=r.id, topic_id=r.topic_id, query=r.query, engine=r.engine,
        window_start=r.window_start, window_end=r.window_end,
        verdict=r.verdict, summary=r.summary or "",
        competitors_top3=[CompetitorMention(**c) for c in comps_raw if isinstance(c, dict)],
        recommendations=[CellInsightRec(**c) for c in recs_raw if isinstance(c, dict)],
        evidence_response_ids=json.loads(r.evidence_response_ids_json or "[]"),
        llm_model=r.llm_model or "", prompt_version=r.prompt_version or "",
        generated_at=r.generated_at, feedback=r.feedback,
    )


# ─────────────────── v1.1 LLM 诊断 ──────────────────────────


@router.post("/topics/{topic_id}/cells/insight", response_model=CellInsightOut)
async def fetch_cell_insight(
    topic_id: int, query: str, engine: str, force: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """drawer 点"分析"按钮触发 — 转发到 telemetry-service 同步生成(LLM 3-8s)."""
    _get_topic_or_404(db, topic_id, current_user.id)
    url = f"{TELEMETRY_SERVICE_URL}/cell-insight"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json={
                "topic_id": topic_id, "query": query, "engine": engine, "force": force,
            })
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"telemetry-service unavailable: {e}")
    if not isinstance(data, dict) or data.get("status") == "not_found":
        raise HTTPException(404, "cell insight not generated")
    # 入库已在 telemetry-service 那侧完成,这里 raw dict → CellInsightOut
    return CellInsightOut(
        id=data["id"], topic_id=data["topic_id"], query=data["query"], engine=data["engine"],
        window_start=datetime.fromisoformat(data["window_start"]) if data.get("window_start") else datetime.utcnow(),
        window_end=datetime.fromisoformat(data["window_end"]) if data.get("window_end") else datetime.utcnow(),
        verdict=data["verdict"], summary=data.get("summary") or "",
        competitors_top3=[CompetitorMention(**c) for c in data.get("competitors_top3") or [] if isinstance(c, dict)],
        recommendations=[CellInsightRec(**c) for c in data.get("recommendations") or [] if isinstance(c, dict)],
        answer_format=data.get("answer_format"),
        citation_domains=data.get("citation_domains") or [],
        evidence_response_ids=data.get("evidence_response_ids") or [],
        llm_model=data.get("llm_model") or "", prompt_version=data.get("prompt_version") or "",
        generated_at=datetime.fromisoformat(data["generated_at"]) if data.get("generated_at") else datetime.utcnow(),
        feedback=data.get("feedback"),
    )


@router.post("/cell-insights/{insight_id}/feedback", status_code=204)
def post_cell_insight_feedback(
    insight_id: int, payload: FeedbackPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """drawer 里的 👍 / 👎 / wrong 反馈."""
    row = db.get(AiTelemetryCellInsightORM, insight_id)
    if row is None:
        raise HTTPException(404, "insight not found")
    topic = db.get(AiTelemetryTopicORM, row.topic_id)
    if topic is None or topic.user_id != current_user.id:
        raise HTTPException(404, "insight not found")
    row.feedback = payload.feedback
    db.commit()


# ─────────────────── v1.2 周报 ──────────────────────────


def _briefing_orm_to_out(b: AiTelemetryTopicBriefingORM) -> BriefingOut:
    actions_raw = json.loads(b.top_actions_json or "[]")
    return BriefingOut(
        id=b.id, topic_id=b.topic_id,
        period_start=b.period_start, period_end=b.period_end,
        body_md=b.body_md or "",
        kpi_snapshot=json.loads(b.kpi_snapshot_json or "{}"),
        top_actions=[BriefingAction(**a) for a in actions_raw if isinstance(a, dict)],
        delivered_email_at=b.delivered_email_at,
        feedback_score=b.feedback_score,
        llm_model=b.llm_model or "", prompt_version=b.prompt_version or "",
        generated_at=b.generated_at,
    )


@router.get("/topics/{topic_id}/briefings", response_model=list[BriefingOut])
def list_briefings(
    topic_id: int, limit: int = 12,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    rows = (
        db.query(AiTelemetryTopicBriefingORM)
          .filter(AiTelemetryTopicBriefingORM.topic_id == topic_id)
          .order_by(AiTelemetryTopicBriefingORM.period_end.desc())
          .limit(min(limit, 52))
          .all()
    )
    return [_briefing_orm_to_out(b) for b in rows]


@router.get("/briefings/{briefing_id}", response_model=BriefingOut)
def get_briefing(
    briefing_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = db.get(AiTelemetryTopicBriefingORM, briefing_id)
    if b is None:
        raise HTTPException(404, "briefing not found")
    topic = db.get(AiTelemetryTopicORM, b.topic_id)
    if topic is None or topic.user_id != current_user.id:
        raise HTTPException(404, "briefing not found")
    return _briefing_orm_to_out(b)


@router.post("/briefings/{briefing_id}/feedback", status_code=204)
def post_briefing_feedback(
    briefing_id: int, payload: BriefingFeedbackPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    b = db.get(AiTelemetryTopicBriefingORM, briefing_id)
    if b is None:
        raise HTTPException(404, "briefing not found")
    topic = db.get(AiTelemetryTopicORM, b.topic_id)
    if topic is None or topic.user_id != current_user.id:
        raise HTTPException(404, "briefing not found")
    b.feedback_score = payload.score
    db.commit()


@router.post("/topics/{topic_id}/briefings/generate", response_model=BriefingOut)
async def trigger_briefing_generation(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动触发生成上一周的周报(管理员 / 客户主动点重新生成)."""
    _get_topic_or_404(db, topic_id, current_user.id)
    url = f"{TELEMETRY_SERVICE_URL}/briefing/generate"
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(url, json={"topic_id": topic_id})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"telemetry-service unavailable: {e}")
    if not isinstance(data, dict) or data.get("status") == "not_found":
        raise HTTPException(404, "topic not found")
    # 重读 ORM(已经入库)
    b = (
        db.query(AiTelemetryTopicBriefingORM)
          .filter(AiTelemetryTopicBriefingORM.id == data["id"])
          .one_or_none()
    )
    if b is None:
        raise HTTPException(500, "briefing inconsistency")
    return _briefing_orm_to_out(b)


# ─────────────────── 内部邮件投递 (briefings 调) ────────────


@router.post("/internal/telemetry-briefing-email", include_in_schema=False)
def internal_briefing_email(payload: dict):
    """telemetry-service 周报生成完毕后调用,本机内网投递邮件 (Resend).

    暂时只 log,等 SMTP / Resend 配置确认后填实际邮件代码.
    不需要 auth(内网调用,backend ↔ telemetry-service 同 VPC).
    """
    topic_id = payload.get("topic_id")
    label = payload.get("label")
    body_md = (payload.get("body_md") or "")[:500]
    log.info("[BRIEFING DELIVER] topic=%s week=%s body=%s", topic_id, label, body_md)
    return {"status": "logged"}


# ─────── 调度中心 / Worker 管理(/workbench/workers,admin)────────
# 转发到 telemetry-service 的 /dispatch/*。telemetry 校验 X-Dispatch-Token,
# 这里携带共享 token;前端鉴权由 _require_admin 负责。
DISPATCH_TOKEN = os.environ.get("DISPATCH_TOKEN", "").strip()


def _dispatch_headers() -> dict:
    return {"X-Dispatch-Token": DISPATCH_TOKEN} if DISPATCH_TOKEN else {}


@router.get("/admin/workers")
async def admin_list_workers(current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{TELEMETRY_SERVICE_URL}/dispatch/workers", headers=_dispatch_headers())
        r.raise_for_status()
        return r.json()


@router.get("/admin/workers-queue-stats")
async def admin_workers_queue_stats(current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{TELEMETRY_SERVICE_URL}/dispatch/queue/stats", headers=_dispatch_headers())
        r.raise_for_status()
        return r.json()


@router.post("/admin/workers/{worker_uid}/{action}")
async def admin_worker_action(
    worker_uid: str, action: str, current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    if action not in ("enable", "disable", "drain"):
        raise HTTPException(400, "action must be enable|disable|drain")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{TELEMETRY_SERVICE_URL}/dispatch/workers/{worker_uid}/{action}",
            headers=_dispatch_headers(),
        )
        r.raise_for_status()
        return r.json()


@router.post("/admin/authorize-account")
def admin_authorize_account(
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    """管理台「添加账号·密码授权」—— 代理到 browser-service 的 /authorize:
    server 端用账号密码自动登录(走代理)→ 抓登录态入池。

    body: {engine, identifier, password}。仅 admin。密码只透传到内网 worker,不落库于此。
    """
    _require_admin(current_user)
    engine = (payload or {}).get("engine")
    identifier = (payload or {}).get("identifier")
    password = (payload or {}).get("password")
    if not (engine and identifier and password):
        raise HTTPException(status_code=400, detail="engine/identifier/password 必填")
    import os
    import httpx
    url = os.environ.get("BROWSER_SERVICE_AUTHORIZE_URL", "http://127.0.0.1:8092").rstrip("/") + "/authorize"
    try:
        with httpx.Client(timeout=140) as c:
            r = c.post(url, json={"engine": engine, "identifier": identifier, "password": password})
        if r.status_code >= 400:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"authorize 代理失败: {e}")


def _bs_authorize_url(path: str) -> str:
    base = os.environ.get("BROWSER_SERVICE_AUTHORIZE_URL", "http://127.0.0.1:8092").rstrip("/")
    return base + path


@router.post("/admin/authorize-qr/start")
def admin_authorize_qr_start(payload: dict, current_user: User = Depends(get_current_user)):
    """扫码授权-开始:代理到 browser-service /authorize/qr/start。返回 {session_id, qr_image}。"""
    _require_admin(current_user)
    engine = (payload or {}).get("engine")
    if not engine:
        raise HTTPException(status_code=400, detail="engine 必填")
    import httpx
    try:
        with httpx.Client(timeout=95) as c:
            r = c.post(_bs_authorize_url("/authorize/qr/start"), json={"engine": engine})
        return r.json() if r.status_code < 400 else {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"qr start 代理失败: {e}")


@router.post("/admin/authorize-qr/poll")
def admin_authorize_qr_poll(payload: dict, current_user: User = Depends(get_current_user)):
    """扫码授权-轮询:代理到 browser-service /authorize/qr/poll。"""
    _require_admin(current_user)
    sid = (payload or {}).get("session_id")
    if not sid:
        raise HTTPException(status_code=400, detail="session_id 必填")
    import httpx
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(_bs_authorize_url("/authorize/qr/poll"), json={"session_id": sid})
        return r.json() if r.status_code < 400 else {"status": "error", "error": f"HTTP {r.status_code}"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"qr poll 代理失败: {e}")


@router.get("/admin/engine-sessions")
def admin_list_engine_sessions(
    page: int = 1,
    page_size: int = 20,
    engine: Optional[str] = None,
    status: Optional[str] = None,   # active | expired | quarantined
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """调度中心「账号池」列表 — 每条登录态(账号)的引擎/标识/状态/用量/过期。

    分页 + 筛选(engine / status,status 按"有效状态"算:active 但已过
    expires_at 的归 expired)。返回 {items, total, grand_total, active_total,
    engines, page, page_size}:total 是筛选后的条数(驱动分页),
    grand_total / active_total 是全池统计(供表头「可用 n / 共 m」),
    engines 是池里出现过的引擎(供筛选下拉)。
    """
    _require_admin(current_user)
    from geo.models.engine_sessions import EngineSessionORM
    from geo.api.engine_sessions import _session_daily_cap, _local_today
    now = datetime.utcnow()
    today_local = _local_today()
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    not_expired = (EngineSessionORM.expires_at == None) | (EngineSessionORM.expires_at > now)  # noqa: E711

    base = db.query(EngineSessionORM)
    grand_total = base.count()
    active_total = (base.filter(EngineSessionORM.status == "active")
                    .filter(not_expired).count())
    # 掉线(需处理):quarantined + 有密码可自愈的另算。这里给总掉线数 + 各引擎掉线数(看板告警用)
    quarantined_total = base.filter(EngineSessionORM.status == "quarantined").count()
    quar_rows = (db.query(EngineSessionORM.engine, func.count())
                 .filter(EngineSessionORM.status == "quarantined")
                 .group_by(EngineSessionORM.engine).all())
    quarantined_by_engine = {e: c for e, c in quar_rows}
    engines = [r[0] for r in
               db.query(EngineSessionORM.engine).distinct().order_by(EngineSessionORM.engine)]

    q = base
    if engine:
        q = q.filter(EngineSessionORM.engine == engine)
    if status == "active":
        q = q.filter(EngineSessionORM.status == "active").filter(not_expired)
    elif status == "expired":
        # 有效状态 expired = 标记 active 但已过期(quarantined 即使过期仍算 quarantined)
        q = q.filter(EngineSessionORM.status == "active").filter(~not_expired)
    elif status == "quarantined":
        q = q.filter(EngineSessionORM.status == "quarantined")
    total = q.count()
    rows = (q.order_by(EngineSessionORM.engine, EngineSessionORM.id)
            .offset((page - 1) * page_size).limit(page_size).all())
    items = []
    for r in rows:
        expired = r.expires_at is not None and r.expires_at <= now
        eff = "expired" if (expired and r.status == "active") else r.status
        # 今日已用:仅当 used_date 为本地今天才算,否则视为 0(跨天归零)
        used_today = (r.used_today or 0) if r.used_date == today_local else 0
        # 生效单账号上限:每账号 daily_cap 覆盖引擎默认;None=用默认,0=不限
        eff_cap = r.daily_cap if r.daily_cap is not None else _session_daily_cap(r.engine)
        remaining = None if not eff_cap else max(0, eff_cap - used_today)
        # 手动停用判定:unschedulable_until 在未来
        disabled = r.unschedulable_until is not None and r.unschedulable_until > now
        items.append({
            "id": r.id, "engine": r.engine, "label": r.source_label,
            "account_handle": r.account_handle,
            "status": eff,
            "use_count": r.use_count or 0, "captcha_count": r.captcha_count or 0,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "captured_at": r.captured_at.isoformat() if r.captured_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "last_fail_type": r.last_fail_type,
            "used_today": used_today,
            "auth_type": r.auth_type,
            "egress": r.egress,
            "exit_ip": r.exit_ip,
            "exit_ip_at": r.exit_ip_at.isoformat() if r.exit_ip_at else None,
            "daily_cap": r.daily_cap,           # 每账号覆盖值(None=用引擎默认)
            "effective_cap": eff_cap,           # 实际生效上限(0=不限)
            "remaining": remaining,             # 今日剩余配额(None=不限)
            "priority": r.priority if r.priority is not None else 50,
            "disabled": disabled,               # 是否被手动停用
            "rate_limited": r.rate_limited_until is not None and r.rate_limited_until > now,
        })
    return {"items": items, "total": total, "grand_total": grand_total,
            "active_total": active_total, "engines": engines,
            "quarantined_total": quarantined_total,
            "quarantined_by_engine": quarantined_by_engine,
            "page": page, "page_size": page_size}


class EngineSessionPatch(BaseModel):
    """账号管理改动(Worker 管理页)。只改提供的字段。"""
    disabled: Optional[bool] = None    # True=停用(不可调度) / False=恢复
    daily_cap: Optional[int] = None    # 单账号日上限:-1=清除覆盖(回引擎默认) / 0=不限 / N=上限
    priority: Optional[int] = None     # 调度优先级,低值优先


@router.patch("/admin/engine-sessions/{session_id}")
def admin_patch_engine_session(
    session_id: int,
    payload: EngineSessionPatch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Worker 管理:启停账号 / 改单账号日上限 / 改优先级。"""
    _require_admin(current_user)
    from geo.models.engine_sessions import EngineSessionORM
    now = datetime.utcnow()
    row = db.query(EngineSessionORM).get(session_id)
    if row is None:
        raise HTTPException(404, f"session id={session_id} not found")
    if payload.disabled is not None:
        # 停用 = unschedulable_until 设远期;恢复 = 清空
        row.unschedulable_until = (now + timedelta(days=3650)) if payload.disabled else None
    if payload.daily_cap is not None:
        row.daily_cap = None if payload.daily_cap < 0 else payload.daily_cap
    if payload.priority is not None:
        row.priority = max(0, min(100, payload.priority))
    db.commit()
    db.refresh(row)
    disabled = row.unschedulable_until is not None and row.unschedulable_until > now
    return {"id": row.id, "daily_cap": row.daily_cap,
            "priority": row.priority, "disabled": disabled}


@router.get("/admin/engine-sessions/by-ip")
def admin_engine_sessions_by_ip(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按出口 IP 聚合账号池:每个 IP 上挂了几个号、各引擎、今日合计用量、密度。
    用于「每 IP × 每账号」视图,看清哪个 IP 账号过密(易被风控)。"""
    _require_admin(current_user)
    from geo.models.engine_sessions import EngineSessionORM
    from geo.api.engine_sessions import _local_today
    now = datetime.utcnow()
    today_local = _local_today()
    not_expired = (EngineSessionORM.expires_at == None) | (EngineSessionORM.expires_at > now)  # noqa: E711
    rows = (db.query(EngineSessionORM)
            .filter(EngineSessionORM.status == "active").filter(not_expired).all())
    agg: dict = {}
    for r in rows:
        ip = r.exit_ip or "(未探测)"
        key = (ip, r.engine)
        g = agg.setdefault(key, {"exit_ip": ip, "engine": r.engine,
                                 "accounts": 0, "used_today": 0})
        g["accounts"] += 1
        g["used_today"] += (r.used_today or 0) if r.used_date == today_local else 0
    groups = sorted(agg.values(), key=lambda x: (x["exit_ip"], x["engine"]))
    # 每 IP 总账号数(跨引擎)— 看密度
    ip_totals: dict = {}
    for g in groups:
        ip_totals[g["exit_ip"]] = ip_totals.get(g["exit_ip"], 0) + g["accounts"]
    for g in groups:
        g["ip_account_total"] = ip_totals[g["exit_ip"]]
    return {"groups": groups, "ip_count": len(ip_totals)}


@router.post("/admin/heal-engine/{engine}")
def admin_heal_engine(
    engine: str,
    current_user: User = Depends(get_current_user),
):
    """引擎自愈(browser-agent Phase 2):跑结构探针 → LLM 提议新选择器。
    **只提议、不自动写**(人工审阅后再 apply,避免覆盖坏配置)。返回 {probe, proposal}。"""
    _require_admin(current_user)
    from geo.api.platform_rules import _llm_text
    base = os.environ.get("BROWSER_SERVICE_AUTHORIZE_URL", "http://127.0.0.1:8092").rstrip("/")
    # 1) 结构探针(browser-service 子进程,只读)
    try:
        with httpx.Client(timeout=140) as c:
            probe = c.post(f"{base}/heal-probe", json={"engine": engine, "query": "canary"}).json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"heal-probe 失败: {e}")
    # 2) LLM 提议选择器
    prompt = (
        f"你是浏览器自动化专家。下面是 AI 搜索引擎「{engine}」网页(可能刚改版)的结构探针。\n"
        "请定位并**只输出 JSON**(不要任何解释/markdown),字段:\n"
        '{"input_sels":[...],"send_sels":[...],"answer_sels":[...],"chat_api":"<completion API url 子串>"}\n'
        "- input_sels: 输入框 CSS 候选链(优先 contenteditable / textarea)\n"
        "- send_sels: 发送按钮 CSS 候选(优先 aria-label 含 发送/Send)\n"
        "- answer_sels: 答案容器 CSS 候选(从候选答案容器里挑最像正文外壳的 class/data 属性)\n"
        "- chat_api: completion 流 API 的 url 子串(从网络 API 里挑含 web_source/messages/stream 的)\n\n"
        f"可交互元素: {json.dumps((probe.get('interactive') or [])[:30], ensure_ascii=False)}\n"
        f"候选答案容器: {json.dumps((probe.get('answer_candidates') or [])[:12], ensure_ascii=False)}\n"
        f"网络API: {json.dumps((probe.get('apis') or [])[:8], ensure_ascii=False)}\n"
    )
    raw = _llm_text(prompt)
    # 解析 LLM 返回的 JSON(剥 ```json 围栏)
    proposal = None
    s = raw.strip()
    if "```" in s:
        s = s.split("```")[1] if s.count("```") >= 2 else s
        s = s.replace("json", "", 1).strip() if s.lstrip().startswith("json") else s
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            proposal = json.loads(s[i:j + 1])
        except Exception:  # noqa: BLE001
            proposal = None
    # 3) 验证门:用提议的选择器跑一条 canary,确认真能出答案+引用(才值得应用)
    validation = None
    if proposal:
        try:
            with httpx.Client(timeout=150) as c:
                validation = c.post(f"{base}/heal-validate",
                                    json={"engine": engine, "override": proposal}).json()
        except Exception as e:  # noqa: BLE001
            validation = {"error": f"validate 调用失败: {e}"[:150], "ans_len": 0, "cites": 0}
    validated = bool(validation and validation.get("ans_len", 0) > 0)
    return {"engine": engine, "probe_error": probe.get("error"),
            "proposal": proposal, "validation": validation, "validated": validated,
            "llm_raw": raw[:800]}


_SELECTORS_OVERRIDE_FILE = os.environ.get(
    "ENGINE_SELECTORS_OVERRIDE_FILE", "/opt/geo/engine_selectors_override.json")


@router.get("/engine-selectors-config")
def engine_selectors_config():
    """中心选择器覆盖配置(各 browser worker 拉取)。自愈 apply 写到这里 → 全队自动生效。
    无鉴权(只是选择器、非敏感),只读。"""
    try:
        with open(_SELECTORS_OVERRIDE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


class HealApplyIn(BaseModel):
    input_sels: Optional[list] = None
    send_sels: Optional[list] = None
    answer_sels: Optional[list] = None
    chat_api: Optional[str] = None
    url: Optional[str] = None


@router.post("/admin/heal-engine/{engine}/apply")
def admin_heal_engine_apply(
    engine: str,
    payload: HealApplyIn,
    current_user: User = Depends(get_current_user),
):
    """把审阅过的选择器提议写入中心配置(覆盖该引擎),全队 worker 下次查询即生效。"""
    _require_admin(current_user)
    patch = {k: v for k, v in payload.dict().items() if v}
    if not patch:
        raise HTTPException(400, "空提议,无可写入")
    try:
        with open(_SELECTORS_OVERRIDE_FILE, encoding="utf-8") as f:
            store = json.load(f)
    except Exception:  # noqa: BLE001
        store = {}
    cur = store.get(engine) if isinstance(store.get(engine), dict) else {}
    cur.update(patch)
    store[engine] = cur
    with open(_SELECTORS_OVERRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    return {"engine": engine, "applied": cur}


@router.get("/admin/engine-health")
def admin_engine_health(current_user: User = Depends(get_current_user)):
    """引擎健康哨兵最新结果(engine_health_check.py 定时写的 JSON)。
    {checked_at, engines:[{engine, ok, ans_len, cites, error}]}。文件不存在 → 空。"""
    _require_admin(current_user)
    path = os.environ.get("ENGINE_HEALTH_FILE", "/opt/geo/engine_health.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"checked_at": None, "engines": []}


# ─────── 对外网关运营管理(/workbench/gateway,admin)────────
# 转发到 telemetry-service 的 /v1/admin/*(校验 X-Admin-Token);前端鉴权由
# _require_admin 负责。GATEWAY_ADMIN_TOKEN 只在服务端持有,绝不下发浏览器。
GATEWAY_ADMIN_TOKEN = os.environ.get("GATEWAY_ADMIN_TOKEN", "").strip()


def _gateway_headers() -> dict:
    return {"X-Admin-Token": GATEWAY_ADMIN_TOKEN} if GATEWAY_ADMIN_TOKEN else {}


@router.get("/admin/gateway/tenants")
async def admin_gateway_tenants(current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{TELEMETRY_SERVICE_URL}/v1/admin/tenants", headers=_gateway_headers())
        r.raise_for_status()
        return r.json()


@router.post("/admin/gateway/tenants")
async def admin_gateway_create_tenant(payload: dict, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{TELEMETRY_SERVICE_URL}/v1/admin/tenants",
                              json=payload, headers=_gateway_headers())
        r.raise_for_status()
        return r.json()


@router.patch("/admin/gateway/tenants/{tenant_id}")
async def admin_gateway_update_tenant(tenant_id: int, payload: dict,
                                      current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.patch(f"{TELEMETRY_SERVICE_URL}/v1/admin/tenants/{tenant_id}",
                               json=payload, headers=_gateway_headers())
        r.raise_for_status()
        return r.json()


@router.post("/admin/gateway/tenants/{tenant_id}/credits")
async def admin_gateway_topup(tenant_id: int, payload: dict,
                              current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{TELEMETRY_SERVICE_URL}/v1/admin/tenants/{tenant_id}/credits",
                              json=payload, headers=_gateway_headers())
        r.raise_for_status()
        return r.json()


@router.post("/admin/gateway/tenants/{tenant_id}/keys")
async def admin_gateway_reissue_key(tenant_id: int, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{TELEMETRY_SERVICE_URL}/v1/admin/tenants/{tenant_id}/keys",
                              headers=_gateway_headers())
        r.raise_for_status()
        return r.json()


@router.post("/admin/gateway/keys/{key_id}/revoke")
async def admin_gateway_revoke_key(key_id: int, current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{TELEMETRY_SERVICE_URL}/v1/admin/keys/{key_id}/revoke",
                              headers=_gateway_headers())
        r.raise_for_status()
        return r.json()


@router.get("/admin/gateway/jobs")
async def admin_gateway_jobs(tenant_id: int | None = None, limit: int = 50,
                             current_user: User = Depends(get_current_user)):
    _require_admin(current_user)
    params: dict = {"limit": limit}
    if tenant_id is not None:
        params["tenant_id"] = tenant_id
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{TELEMETRY_SERVICE_URL}/v1/admin/jobs",
                             params=params, headers=_gateway_headers())
        r.raise_for_status()
        return r.json()
