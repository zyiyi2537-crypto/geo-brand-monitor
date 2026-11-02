"""Admin 审核 — Phase C(单条种子/query 审核)+ Phase D(整张申请审核).

Phase D 新增端点(以 topic 为整体审核单位):
- GET    /admin/review/topics                          — 列出全部 topic 申请,带 status 过滤
- GET    /admin/review/topic/{id}                      — 单条申请的完整资料(资料 / 种子 / 监测问题 / 日志)
- PATCH  /admin/review/topic/{id}                      — admin 修改资料 / 种子 / 监测问题(走 changelog)
- POST   /admin/review/topic/{id}/approve              — 通过:跑一次 + 生成执行计划书 + 异步生成文案稿 + 邮件
- POST   /admin/review/topic/{id}/reject               — 拒绝 + 邮件
- GET    /admin/review/topic/{id}/execution-plan       — 拿执行计划书(含 4 分区 + 运行进度,轮询用)

Phase C 单条端点(种子词逐条 / queries 批量)保留向后兼容.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from geo.api.auth import require_admin
from geo.api.ai_telemetry import get_db, _append_changelog
from geo.models.ai_telemetry import (
    AiTelemetryQueryHitORM, AiTelemetryRunORM, AiTelemetryTopicORM,
    AiTelemetryTopicExecutionPlanORM, AiTelemetryTopicSolutionORM,
    BrandProfile, ContentTemplateORM, ExecutionPlanUpdatePayload,
    GenerateSolutionPayload, MAX_SELECTED_QUERIES, PlanItemDraft,
    PROFILE_REQUIRED_FIELDS, PublishPlanItem, SolutionDiagnosis,
    SolutionDiagnosisCheck, SolutionDiagnosisCluster, SolutionKeywordTier,
    SolutionQueriesSnapshot, SolutionQueryCluster, SolutionQueryItem,
    SolutionSevenStepItem, SolutionVisionItem, TopicChangelogEntry,
    TopicExecutionPlanOut, TopicGeneratedDocORM, TopicProgressCell,
    TopicSolutionOut, ExpansionLogEntry, TopicOut,
)
from geo.models.user import UserORM

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/review")
# 去审核新通道:admin 直接「启动」项目,不再走 pending → approved 那一步.
# 旧 router 在 PR 2 退役;本 router 是长期入口.
topics_router = APIRouter(prefix="/admin/topics")

TELEMETRY_SERVICE_URL = os.environ.get("TELEMETRY_SERVICE_URL", "http://localhost:8095")


# ═════════════════ Phase C — pending(种子 / 单条 query)═════════════════


class PendingSeedItem(BaseModel):
    topic_id: int
    topic_name: str
    target: str
    user_id: int
    user_email: str
    idx: int
    text: str
    submitted_at: Optional[str] = None


class PendingQueryItem(BaseModel):
    topic_id: int
    topic_name: str
    target: str
    user_id: int
    user_email: str
    idx: int
    text: str
    cluster_id: Optional[int] = None
    submitted_at: Optional[str] = None


class PendingOut(BaseModel):
    seed_prompts: list[PendingSeedItem]
    queries: list[PendingQueryItem]


@router.get("/pending", response_model=PendingOut)
def list_pending(
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(AiTelemetryTopicORM).all()
    user_ids = {r.user_id for r in rows}
    email_by_uid: dict[int, str] = {}
    if user_ids:
        for u in db.query(UserORM).filter(UserORM.id.in_(user_ids)).all():
            email_by_uid[u.id] = u.email
    seeds: list[PendingSeedItem] = []
    queries: list[PendingQueryItem] = []
    for r in rows:
        email = email_by_uid.get(r.user_id, "")
        try:
            seed_list = json.loads(r.seed_prompts_json or "[]")
        except Exception:  # noqa: BLE001
            seed_list = []
        for i, s in enumerate(seed_list):
            if isinstance(s, dict) and s.get("status") == "pending" and s.get("text"):
                seeds.append(PendingSeedItem(
                    topic_id=r.id, topic_name=r.name, target=r.target or "",
                    user_id=r.user_id, user_email=email,
                    idx=i, text=s["text"], submitted_at=s.get("submitted_at"),
                ))
        try:
            q_list = json.loads(r.queries_json or "[]")
        except Exception:  # noqa: BLE001
            q_list = []
        for i, q in enumerate(q_list):
            if isinstance(q, dict) and q.get("status") == "pending" and q.get("text"):
                queries.append(PendingQueryItem(
                    topic_id=r.id, topic_name=r.name, target=r.target or "",
                    user_id=r.user_id, user_email=email,
                    idx=i, text=q["text"],
                    cluster_id=q.get("cluster_id") if isinstance(q.get("cluster_id"), int) else None,
                    submitted_at=q.get("submitted_at"),
                ))
    return PendingOut(seed_prompts=seeds, queries=queries)


def _load_topic_or_404(db: Session, topic_id: int) -> AiTelemetryTopicORM:
    t = db.get(AiTelemetryTopicORM, topic_id)
    if not t:
        raise HTTPException(404, "topic not found")
    return t


# Phase C 子项审核端点(approve/reject seed + queries)在去审核流里退役了.
# admin 直建项目就落 approved,不再需要逐条审批通道.helpers 保留供 PATCH 用.


# ═════════════════ Phase D — 整张申请审核 ═════════════════


# 项目进度 stage 状态值域 — 与前端 AdminCockpit.tsx 的 StageState 保持一致.
# done / running / pending / blocked / idle 共 5 态.
StageState = str

# 审核未通过 → 后续 stage 一律 idle(还没批准就不能开工).这条规则是闸门,
# 避免每个映射函数都重复写,统一在调用点判断后再传 approved=True 进来.

def _diagnose_state(approved: bool, sol: Optional[AiTelemetryTopicSolutionORM]) -> StageState:
    """健康度诊断报告 — TopicSolution 表(每 topic 唯一)."""
    if not approved or sol is None:
        return "idle"
    s = (sol.status or "").lower()
    return {"ready": "done", "generating": "running", "failed": "blocked"}.get(s, "idle")


def _plan_state(approved: bool, plan: Optional[AiTelemetryTopicExecutionPlanORM]) -> StageState:
    """执行策略与规划 — TopicExecutionPlan(取最新一条).启动项目时落 draft,
    运营在编辑器里编辑发文表 + 确认后变 confirmed."""
    if not approved or plan is None:
        return "idle"
    s = (plan.status or "").lower()
    # draft = 编辑中,前端按 pending(等运营操作)展示;confirmed = done.
    return {
        "draft": "pending", "confirmed": "done", "failed": "blocked",
        # 兼容旧值
        "ready": "done", "generating": "running",
    }.get(s, "idle")


def _content_state(approved: bool, agg: dict[str, int]) -> StageState:
    """内容发布与审核 — TopicGeneratedDoc 按 status 聚合.

    agg = {"draft": n, "pending_review": n, "approved": n, "rejected": n, "published": n}.
    优先级:已发布 > 待 admin 操作(待审 / 已批准未标发布) > 仅 draft(LLM 出稿中)
    > 全部 rejected > 无文稿.
    """
    if not approved:
        return "idle"
    total = sum(agg.values())
    if total == 0:
        return "idle"
    if agg.get("published", 0) > 0:
        return "done"
    if agg.get("pending_review", 0) > 0 or agg.get("approved", 0) > 0:
        return "pending"  # 等 admin 审 / 等 admin 标记发布
    if agg.get("draft", 0) > 0:
        return "running"  # LLM 还在出稿
    return "blocked"      # 剩下只能是 rejected 全部死光


def _insight_state(approved: bool, last_status: Optional[str], last_at) -> StageState:
    """效果查验与更新 — 直接读 topic 表的 last_run_status / last_run_at,免 N+1."""
    if not approved or last_at is None:
        return "idle"
    s = (last_status or "").lower()
    return {"success": "done", "running": "running", "failed": "blocked"}.get(s, "idle")


class TopicReviewListItem(BaseModel):
    topic_id: int
    topic_name: str
    user_id: int
    user_email: str
    submission_status: str
    submitted_at: Optional[datetime]
    approved_at: Optional[datetime]
    rejected_at: Optional[datetime]
    profile_name: str
    company_short_name: str
    industry: str
    seed_count: int
    selected_query_count: int
    version: int = 1                          # 修订号,跟 TopicOut.version 对齐
    # 项目进度 stage 3-6 状态(stage 1 永远 done、stage 2 由 submission_status 推).
    diagnose_status: StageState = "idle"
    plan_status: StageState = "idle"
    content_status: StageState = "idle"
    insight_status: StageState = "idle"


class TopicReviewDetailOut(TopicOut):
    user_id: int = 0
    user_email: str = ""
    topic_changelog: list[TopicChangelogEntry] = Field(default_factory=list)
    expansion_log: list[ExpansionLogEntry] = Field(default_factory=list)


def _parse_log_list(raw: str | None) -> list[dict]:
    """解析 topic_changelog / expansion_log 的 JSON 数组,返回 list[dict].

    历史 changelog 在 list 类型 profile 字段(如 core_business_lines)被改写时
    会把 before/after 存成 list/dict,而 TopicChangelogEntry 模型期望 Optional[str].
    这里统一把 before/after 的非 str 值序列化成 str,避免下游 Pydantic 500.
    """
    try:
        arr = json.loads(raw or "[]")
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for x in arr:
        if not isinstance(x, dict):
            continue
        for k in ("before", "after"):
            v = x.get(k)
            if v is not None and not isinstance(v, str):
                x[k] = json.dumps(v, ensure_ascii=False)
        out.append(x)
    return out


@router.get("/topics", response_model=list[TopicReviewListItem])
def list_topic_reviews(
    status: Optional[str] = None,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """全平台 topic 申请列表;status 过滤:draft / pending / approved / rejected.

    默认按 submitted_at desc 排;无 submitted_at 的退回 created_at desc.
    """
    q = db.query(AiTelemetryTopicORM)
    if status:
        q = q.filter(AiTelemetryTopicORM.submission_status == status)
    rows = q.all()
    user_ids = {r.user_id for r in rows}
    email_by_uid: dict[int, str] = {}
    if user_ids:
        for u in db.query(UserORM).filter(UserORM.id.in_(user_ids)).all():
            email_by_uid[u.id] = u.email

    # 项目进度 stage 3-6 的批量预取(全部按 topic_id IN (...) 一次拿).
    topic_ids = [r.id for r in rows]
    sol_by_tid: dict[int, AiTelemetryTopicSolutionORM] = {}
    plan_by_tid: dict[int, AiTelemetryTopicExecutionPlanORM] = {}
    doc_agg_by_tid: dict[int, dict[str, int]] = {}
    if topic_ids:
        for s in db.query(AiTelemetryTopicSolutionORM).filter(
            AiTelemetryTopicSolutionORM.topic_id.in_(topic_ids)
        ).all():
            sol_by_tid[s.topic_id] = s   # unique 约束保证每 topic 至多一条
        # 执行计划可能多条(重新批准会再生成),按 id desc 取最新一条
        for p in db.query(AiTelemetryTopicExecutionPlanORM).filter(
            AiTelemetryTopicExecutionPlanORM.topic_id.in_(topic_ids)
        ).order_by(AiTelemetryTopicExecutionPlanORM.id.desc()).all():
            plan_by_tid.setdefault(p.topic_id, p)
        # 文稿按 (topic_id, status) 聚合,只拉两列避免拖出 body_markdown 巨量文本
        for tid, st in db.query(
            TopicGeneratedDocORM.topic_id, TopicGeneratedDocORM.status
        ).filter(TopicGeneratedDocORM.topic_id.in_(topic_ids)).all():
            doc_agg_by_tid.setdefault(tid, {}).setdefault(st or "", 0)
            doc_agg_by_tid[tid][st or ""] += 1

    out: list[TopicReviewListItem] = []
    for r in rows:
        try:
            profile = json.loads(r.profile_json or "{}")
        except Exception:  # noqa: BLE001
            profile = {}
        if not isinstance(profile, dict):
            profile = {}
        try:
            seeds = json.loads(r.seed_prompts_json or "[]")
        except Exception:  # noqa: BLE001
            seeds = []
        seed_count = sum(1 for s in seeds if isinstance(s, dict) and s.get("text"))
        try:
            qarr = json.loads(r.queries_json or "[]")
        except Exception:  # noqa: BLE001
            qarr = []
        sel_n = sum(
            1 for q in qarr
            if isinstance(q, dict) and q.get("text") and q.get("selected", True)
        )
        approved = (r.submission_status == "approved")
        out.append(TopicReviewListItem(
            topic_id=r.id, topic_name=r.name,
            user_id=r.user_id, user_email=email_by_uid.get(r.user_id, ""),
            submission_status=r.submission_status or "draft",
            submitted_at=r.submitted_at,
            approved_at=r.approved_at, rejected_at=r.rejected_at,
            profile_name=str(profile.get("profile_name") or ""),
            company_short_name=str(profile.get("company_short_name") or ""),
            industry=str(profile.get("industry") or r.industry or ""),
            seed_count=seed_count,
            selected_query_count=sel_n,
            version=int(getattr(r, "version", 1) or 1),
            diagnose_status=_diagnose_state(approved, sol_by_tid.get(r.id)),
            plan_status=_plan_state(approved, plan_by_tid.get(r.id)),
            content_status=_content_state(approved, doc_agg_by_tid.get(r.id, {})),
            insight_status=_insight_state(approved, r.last_run_status, r.last_run_at),
        ))
    out.sort(key=lambda x: (x.submitted_at or datetime.min, x.topic_id), reverse=True)
    return out


@router.get("/topic/{topic_id}", response_model=TopicReviewDetailOut)
def get_topic_review_detail(
    topic_id: int,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    t = _load_topic_or_404(db, topic_id)
    base = TopicOut.from_orm_row(t)
    user = db.get(UserORM, t.user_id)
    out = TopicReviewDetailOut(
        **base.model_dump(),
        user_id=t.user_id,
        user_email=(user.email if user else ""),
        topic_changelog=[
            TopicChangelogEntry(**e) for e in _parse_log_list(t.topic_changelog_json)
            if "at" in e
        ],
        expansion_log=[
            ExpansionLogEntry(**e) for e in _parse_log_list(t.expansion_log_json)
            if "at" in e
        ],
    )
    return out


class AdminPatchTopicPayload(BaseModel):
    """admin 编辑资料 / 种子 / queries 任一字段;字段缺省 = 不改."""
    profile: Optional[BrandProfile] = None
    seed_prompts: Optional[list[str]] = None         # 若给,以这份替换种子列表(text 集合)
    selected_query_texts: Optional[list[str]] = None  # 若给,把这些 text 的 selected 设 True,其余 False
    add_queries: Optional[list[str]] = None           # 追加 query 候选(status=approved,直接可选)
    note: Optional[str] = Field(None, max_length=500)


@router.patch("/topic/{topic_id}", response_model=TopicReviewDetailOut)
def admin_patch_topic(
    topic_id: int,
    payload: AdminPatchTopicPayload,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 编辑申请.changelog 全程追加,actor_role=admin.
    任意 submission_status 都允许 — admin 是终审,approved 之后也能修正
    资料/种子/监测问题(已生成的内容稿件不会自动重跑,需手动触发).
    """
    t = _load_topic_or_404(db, topic_id)

    actor_id = admin.id

    if payload.profile is not None:
        t.profile_json = json.dumps(payload.profile.model_dump(), ensure_ascii=False)
        if payload.profile.industry:
            t.industry = payload.profile.industry
        if payload.profile.company_short_name:
            t.target = payload.profile.company_short_name
        if payload.profile.profile_name:
            t.name = payload.profile.profile_name
        _append_changelog(t, actor_id=actor_id, actor_role="admin",
                          field="profile",
                          after=payload.profile.profile_name or payload.profile.company_short_name)

    if payload.seed_prompts is not None:
        cleaned = [s.strip() for s in payload.seed_prompts if s and s.strip()]
        now_iso = datetime.utcnow().isoformat()
        try:
            existing = json.loads(t.seed_prompts_json or "[]")
        except Exception:  # noqa: BLE001
            existing = []
        existing_by_text = {
            s["text"]: s for s in existing
            if isinstance(s, dict) and s.get("text")
        }
        new_list = []
        for text in cleaned:
            if text in existing_by_text:
                new_list.append(existing_by_text[text])
            else:
                new_list.append({
                    "text": text, "status": "approved",
                    "submitted_at": now_iso, "approved_at": now_iso,
                    "reviewer_id": actor_id,
                })
        t.seed_prompts_json = json.dumps(new_list, ensure_ascii=False)
        _append_changelog(t, actor_id=actor_id, actor_role="admin",
                          field="seed_prompts",
                          after=f"count={len(new_list)}")

        # 2026-05-26 — 每条 approved seed 自动派生一条同名 query(is_seed=True, locked=True)。
        # 已存在的同名 query → 升级标记;不存在 → 新增。这样:
        #   - seed 提示词在监测列表里有独立一行,可单独筛选
        #   - locked=True 让前端 picker 不可取消勾选,保证 seed 必跑监测
        #   - 跟扩展出来的 query 共享同一份 ai_telemetry_responses,无需 re-run
        approved_texts = [s["text"] for s in new_list
                          if isinstance(s, dict) and s.get("status") == "approved" and s.get("text")]
        if approved_texts:
            try:
                qarr = json.loads(t.queries_json or "[]")
            except Exception:  # noqa: BLE001
                qarr = []
            q_by_text = {q.get("text"): q for q in qarr if isinstance(q, dict)}
            seed_added = 0
            seed_marked = 0
            for txt in approved_texts:
                if txt in q_by_text:
                    q = q_by_text[txt]
                    if not q.get("is_seed"):
                        q["is_seed"] = True
                        q["locked"] = True
                        q["selected"] = True
                        q["seed"] = txt
                        seed_marked += 1
                else:
                    qarr.append({
                        "text": txt, "status": "approved",
                        "submitted_at": now_iso, "approved_at": now_iso,
                        "reviewer_id": actor_id,
                        "seed": txt, "is_seed": True, "locked": True,
                        "selected": True, "cluster_id": -1,
                    })
                    seed_added += 1
            if seed_added or seed_marked:
                t.queries_json = json.dumps(qarr, ensure_ascii=False)
                _append_changelog(t, actor_id=actor_id, actor_role="admin",
                                  field="queries.is_seed",
                                  after=f"seed_added={seed_added}, seed_marked={seed_marked}")

    if payload.add_queries:
        try:
            qarr = json.loads(t.queries_json or "[]")
        except Exception:  # noqa: BLE001
            qarr = []
        existing_q_texts = {
            q["text"] for q in qarr
            if isinstance(q, dict) and q.get("text")
        }
        now_iso = datetime.utcnow().isoformat()
        added = 0
        for text in payload.add_queries:
            text = (text or "").strip()
            if not text or text in existing_q_texts:
                continue
            qarr.append({
                "text": text, "status": "approved",
                "submitted_at": now_iso, "approved_at": now_iso,
                "reviewer_id": actor_id, "selected": False,
            })
            existing_q_texts.add(text)
            added += 1
        t.queries_json = json.dumps(qarr, ensure_ascii=False)
        _append_changelog(t, actor_id=actor_id, actor_role="admin",
                          field="queries", after=f"added={added}")

    if payload.selected_query_texts is not None:
        desired = {s.strip() for s in payload.selected_query_texts if s and s.strip()}
        if len(desired) > MAX_SELECTED_QUERIES:
            raise HTTPException(422, {
                "code": "TOO_MANY_SELECTED",
                "message": f"最多 {MAX_SELECTED_QUERIES} 个监测问题,当前 {len(desired)}",
            })
        try:
            qarr = json.loads(t.queries_json or "[]")
        except Exception:  # noqa: BLE001
            qarr = []
        upgraded: list[dict] = []
        for q in qarr:
            if isinstance(q, str):
                upgraded.append({"text": q, "status": "approved", "selected": q in desired})
            elif isinstance(q, dict) and q.get("text"):
                qq = dict(q)
                qq["selected"] = qq["text"] in desired
                upgraded.append(qq)
        # 添加 desired 中不在 qarr 的(admin 直接挑了新文本进监测)
        existing_texts = {q["text"] for q in upgraded}
        for text in desired - existing_texts:
            upgraded.append({
                "text": text, "status": "approved",
                "selected": True, "approved_at": datetime.utcnow().isoformat(),
                "reviewer_id": actor_id,
            })
        t.queries_json = json.dumps(upgraded, ensure_ascii=False)
        _append_changelog(t, actor_id=actor_id, actor_role="admin",
                          field="selected_queries",
                          after=f"selected_count={len(desired)}")

    if payload.note:
        _append_changelog(t, actor_id=actor_id, actor_role="admin",
                          field="note", note=payload.note)

    db.commit()
    db.refresh(t)

    user = db.get(UserORM, t.user_id)
    base = TopicOut.from_orm_row(t)
    return TopicReviewDetailOut(
        **base.model_dump(),
        user_id=t.user_id,
        user_email=(user.email if user else ""),
        topic_changelog=[
            TopicChangelogEntry(**e) for e in _parse_log_list(t.topic_changelog_json) if "at" in e
        ],
        expansion_log=[
            ExpansionLogEntry(**e) for e in _parse_log_list(t.expansion_log_json) if "at" in e
        ],
    )


def _send_review_email_safe(*, to: str, topic_name: str, decision: str,
                             reject_reason: str | None = None,
                             execution_plan_url: str | None = None) -> None:
    """发审核结果邮件;失败不抛(邮件挂了不应该阻塞审核)."""
    if not to:
        log.warning("review email skipped: no recipient for topic '%s'", topic_name)
        return
    try:
        from geo.services.email_service import email_service
        email_service.send_review_result_email(
            to=to, topic_name=topic_name, decision=decision,
            reject_reason=reject_reason, execution_plan_url=execution_plan_url,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("review email failed: %s", e)


def _trigger_run_topic_sync(topic_id: int) -> Optional[int]:
    """同步触发 telemetry-service /run-topic,返回 run_id(失败返回 None)."""
    url = f"{TELEMETRY_SERVICE_URL}/run-topic"
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(url, json={"topic_id": topic_id})
            r.raise_for_status()
            data = r.json()
            run_id = data.get("run_id") if isinstance(data, dict) else None
            return int(run_id) if isinstance(run_id, int) else None
    except Exception as e:  # noqa: BLE001
        log.warning("trigger run failed for topic %d: %s", topic_id, e)
        return None


def _build_execution_plan_snapshot(t: AiTelemetryTopicORM, run_id: int | None) -> dict:
    """通过审核时落 ExecutionPlan 那一刻的快照."""
    try:
        qarr = json.loads(t.queries_json or "[]")
    except Exception:  # noqa: BLE001
        qarr = []
    monitored = [
        q["text"] for q in qarr
        if isinstance(q, dict) and q.get("text") and q.get("selected", True)
        and q.get("status") == "approved"
    ]
    try:
        profile = json.loads(t.profile_json or "{}")
    except Exception:  # noqa: BLE001
        profile = {}
    if not isinstance(profile, dict):
        profile = {}
    try:
        engines = json.loads(t.engines_json or "[]")
    except Exception:  # noqa: BLE001
        engines = []
    overview = {
        "topic_id": t.id,
        "topic_name": t.name,
        "company_short_name": profile.get("company_short_name") or t.target,
        "industry": profile.get("industry") or t.industry,
        "service_geo": profile.get("service_geo") or "",
        "monitored_queries_count": len(monitored),
        "engines": engines,
        "engines_count": len(engines),
        "estimated_cells": len(monitored) * len(engines),
        "snapshot_at": datetime.utcnow().isoformat(),
        "approved_by_run_id": run_id,
    }
    return {
        "overview": overview,
        "monitored_queries": monitored,
        "changelog": _parse_log_list(t.topic_changelog_json),
        "expansion_log": _parse_log_list(t.expansion_log_json),
    }


def _schedule_content_generation(
    topic_id: int, plan_id: int,
    *, plan_item_ids: Optional[list[str]] = None,
) -> None:
    """异步触发内容文案生成.支持指定 plan_item_ids 跑单条;为 None 跑全表."""
    try:
        from geo.services.content_generator import schedule_generation
        schedule_generation(
            topic_id=topic_id, plan_id=plan_id,
            plan_item_ids=plan_item_ids,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("schedule content generation failed: %s", e)


def _create_draft_plan(
    db: Session,
    t: AiTelemetryTopicORM,
    actor_id: int,
    background: BackgroundTasks,
) -> AiTelemetryTopicExecutionPlanORM:
    """启动项目时的副作用:跑监控 + 落 draft plan + 发邮件.**不**触发文章生成.

    文章生成移到 _confirm_plan / regenerate-item.
    调用前提:t 的状态变更已 db.commit()(避免 SQLite 写锁阻塞 telemetry-service).
    """
    topic_id = t.id
    run_id = _trigger_run_topic_sync(topic_id)
    snapshot = _build_execution_plan_snapshot(t, run_id)
    plan = AiTelemetryTopicExecutionPlanORM(
        topic_id=topic_id,
        generated_by_reviewer_id=actor_id,
        overview_json=json.dumps(snapshot["overview"], ensure_ascii=False),
        topic_changelog_snapshot_json=json.dumps(snapshot["changelog"], ensure_ascii=False),
        expansion_log_snapshot_json=json.dumps(snapshot["expansion_log"], ensure_ascii=False),
        monitored_queries_snapshot_json=json.dumps(snapshot["monitored_queries"], ensure_ascii=False),
        publishing_plan_json="[]",
        run_id=run_id,
        # 监控触发失败时直接 failed;监控触发成功 → 进入 draft 等运营编辑发文表
        status="draft" if run_id is not None else "failed",
        error=None if run_id is not None else "telemetry-service /run-topic failed",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    user = db.get(UserORM, t.user_id)
    plan_url = None
    try:
        from geo.database import settings as _s
        plan_url = f"{(_s.FRONTEND_URL or '').rstrip('/')}/workbench/topics/{topic_id}/execution-plan"
    except Exception:  # noqa: BLE001
        pass

    if user and user.email:
        background.add_task(_send_review_email_safe,
                            to=user.email, topic_name=t.name,
                            decision="approved", execution_plan_url=plan_url)
    return plan


def _kick_content_generation(
    plan: AiTelemetryTopicExecutionPlanORM,
    background: BackgroundTasks,
    *, plan_item_ids: Optional[list[str]] = None,
) -> None:
    """把文章生成派进后台.confirm / regenerate-item 共用."""
    background.add_task(
        _schedule_content_generation,
        topic_id=plan.topic_id, plan_id=plan.id,
        plan_item_ids=plan_item_ids,
    )


def _post_approval_pipeline(
    db: Session,
    t: AiTelemetryTopicORM,
    actor_id: int,
    background: BackgroundTasks,
) -> AiTelemetryTopicExecutionPlanORM:
    """[已退役入口] 仅为兼容性保留,实际仍只走 _create_draft_plan.

    旧 approve_topic / rerun 的语义里它会立即触发文章生成;新流程改成
    需要运营 confirm 才生成,所以这里**不再**自动 kick content generator.
    """
    return _create_draft_plan(db, t, actor_id, background)


# approve_topic / reject_topic 在去审核流里退役了.功能改由 POST /admin/topics/{id}/start
# 承担(见本文件 start_topic 端点).rerun_topic 与 _post_approval_pipeline 仍在,给重启复用.


# ───────────── 执行计划书 — 拉取 + 运行进度 ─────────────


DEFAULT_PUBLISH_PLATFORMS = ["公众号", "小红书", "抖音", "视频号"]

# 发文计划是「持续滚动」的:每批最多铺一个月(~30 天),定时任务临近末尾再接排下一个月.
PLAN_WINDOW_DAYS = int(os.environ.get("GEO_PLAN_WINDOW_DAYS", "30"))
# 计划末尾日期距今 ≤ 该天数时算 runway 不足,自动续期(见 extend_plan_one_month).
PLAN_REFILL_LEAD_DAYS = int(os.environ.get("GEO_PLAN_REFILL_LEAD_DAYS", "7"))


def _pick_default_template_id(db: Session) -> Optional[int]:
    """挑一个默认模板给新 draft 的种子行 — 优先 system 范围,最早一条."""
    t = (
        db.query(ContentTemplateORM)
          .filter(ContentTemplateORM.scope == "system")
          .order_by(ContentTemplateORM.id.asc())
          .first()
    )
    return t.id if t else None


# GEO 内容投放主力 kind — 排在 seed × 模板 列表最前,优先生成「行业合辑 · 推荐榜单」.
# 见 migration c5f4a8b9e3d2_add_industry_listicle_template.py 注入的 system 模板.
_PRIMARY_TEMPLATE_KIND = "榜单合辑"


def _pick_template_kinds_per_seed(db: Session, n: int = 5) -> list[ContentTemplateORM]:
    """挑 N 个 system 范围、kind 互不相同的模板 — seed × 模板 发文表用.

    顺序:_PRIMARY_TEMPLATE_KIND(榜单合辑)优先 → 其余按 id 升序.
    每个 kind 只取一条(同 kind 的多条 system 模板里按 id 取第一条).
    system 模板不够 n 种 kind 时返回更短列表;全空时返回 [],由调用方 fallback 到 legacy.
    """
    sys_templates = (
        db.query(ContentTemplateORM)
          .filter(ContentTemplateORM.scope == "system")
          .order_by(ContentTemplateORM.id.asc())
          .all()
    )
    # 主推 kind 拉到队首
    primary = [t for t in sys_templates if t.kind == _PRIMARY_TEMPLATE_KIND]
    others = [t for t in sys_templates if t.kind != _PRIMARY_TEMPLATE_KIND]
    ordered = primary + others

    seen_kinds: set[str] = set()
    picked: list[ContentTemplateORM] = []
    for tmpl in ordered:
        if tmpl.kind in seen_kinds:
            continue
        seen_kinds.add(tmpl.kind)
        picked.append(tmpl)
        if len(picked) >= n:
            break
    return picked


def _legacy_query_window(
    db: Session, topic_id: int, monitored: list[str],
    *, start_date, days: int, start_seq: int = 0,
) -> list[dict]:
    """旧版回退:按 query 命中率排序,循环铺满 [start_date, start_date+days),每天 1 篇.

    新版没有 system 模板 / 没有 approved 种子 时 fallback 到这里.
    query 不足 days 天时循环复用(队首高优先级先排).
    """
    import uuid as _uuid
    cells = (
        db.query(AiTelemetryQueryHitORM)
          .filter(AiTelemetryQueryHitORM.topic_id == topic_id)
          .all()
    )
    by_query: dict[str, dict] = {}
    for c in cells:
        if c.query not in monitored:
            continue
        agg = by_query.setdefault(c.query, {"runs": 0, "hits": 0})
        agg["runs"] += c.total_runs or 0
        agg["hits"] += c.total_hits or 0

    def _priority_rank(q: str) -> int:
        agg = by_query.get(q, {"runs": 0, "hits": 0})
        if agg["runs"] <= 0:
            return 0
        cov = agg["hits"] / agg["runs"] * 100
        if cov == 0: return 0
        if cov < 50: return 1
        return 2

    sorted_queries = sorted(monitored, key=lambda q: (_priority_rank(q), q))
    if not sorted_queries:
        return []

    default_tmpl_id = _pick_default_template_id(db)
    default_tmpl = db.get(ContentTemplateORM, default_tmpl_id) if default_tmpl_id else None
    default_platform: Optional[str] = None
    if default_tmpl:
        try:
            platforms = json.loads(default_tmpl.target_platforms_json or "[]")
        except Exception:  # noqa: BLE001
            platforms = []
        if isinstance(platforms, list) and platforms:
            default_platform = str(platforms[0])
    if not default_platform:
        default_platform = DEFAULT_PUBLISH_PLATFORMS[0]

    items: list[dict] = []
    for day_offset in range(days):
        q = sorted_queries[day_offset % len(sorted_queries)]
        items.append({
            "id": str(_uuid.uuid4()),
            "seq": start_seq + day_offset,
            "publish_date": (start_date + timedelta(days=day_offset)).isoformat(),
            "seed": None,
            "query": q,
            "template_id": default_tmpl_id,
            "platform": default_platform,
            "note": None,
        })
    return items


# 2026-06-12 — 初始计划按模板 kind 自动分配单行创作偏好(创作方向 × 文案类型),
# 不再留空靠画像默认(画像默认是笛卡尔积,一行会爆多篇变体)。
# 取值与 content_generator 的 DIRECTION_HINTS / TYPE_HINTS key 对齐。
_KIND_COMBO: dict[str, tuple[str, str]] = {
    "榜单合辑": ("product_review", "long_form"),
    "长文":     ("industry_insight", "long_form"),
    "短文":     ("trend_forecast", "short_social"),
    "FAQ":      ("faq", "faq_list"),
    "问答":     ("faq", "faq_list"),
    "案例":     ("case_story", "medium_post"),
    "对比":     ("product_review", "medium_post"),
    "测评":     ("product_review", "medium_post"),
    "教程":     ("how_to_guide", "medium_post"),
}
_DIR_CYCLE = ["industry_insight", "case_story", "how_to_guide",
              "trend_forecast", "product_review", "customer_story", "faq"]
_TYPE_CYCLE = ["long_form", "medium_post", "short_social",
               "video_script_short", "faq_list"]


def _default_row_combo(kind: str, idx: int) -> tuple[str, str]:
    """模板 kind → (创作方向, 文案类型);未知 kind 按 idx 轮换兜底."""
    pair = _KIND_COMBO.get((kind or "").strip())
    if pair:
        return pair
    return _DIR_CYCLE[idx % len(_DIR_CYCLE)], _TYPE_CYCLE[idx % len(_TYPE_CYCLE)]


def _build_plan_window(
    db: Session, topic_id: int, monitored: list[str],
    *, start_date, days: int, start_seq: int = 0,
) -> list[dict]:
    """seed × 模板 的滚动发文计划 — 在 [start_date, start_date+days) 内铺满,每天 N 篇.

    N = 选中的 system 模板数(kind 互不相同,通常 5).种子按天 round-robin:
      day 0:seeds[0] × N 模板
      day 1:seeds[1] × N 模板
      ...   seeds 用尽后循环复用,直到铺满 days 天.

    没 approved 种子 / 没 system 模板 时 fallback 到 _legacy_query_window.
    返回 publishing_plan_json 内部存储格式(只放持久化字段).每批最多 days 天 → 满足「一次最多一个月」.
    """
    import uuid as _uuid

    picked_templates = _pick_template_kinds_per_seed(db, n=5)
    if not picked_templates:
        return _legacy_query_window(
            db, topic_id, monitored, start_date=start_date, days=days, start_seq=start_seq)

    topic = db.get(AiTelemetryTopicORM, topic_id)
    if not topic:
        return _legacy_query_window(
            db, topic_id, monitored, start_date=start_date, days=days, start_seq=start_seq)
    try:
        seeds_raw = json.loads(topic.seed_prompts_json or "[]")
    except Exception:  # noqa: BLE001
        seeds_raw = []
    approved_seeds = [
        str(s.get("text") or "").strip()
        for s in seeds_raw
        if isinstance(s, dict) and s.get("status") == "approved" and s.get("text")
    ]
    if not approved_seeds:
        return _legacy_query_window(
            db, topic_id, monitored, start_date=start_date, days=days, start_seq=start_seq)

    # 2026-06-11 — 种子 → 该种子下被选监测 query 列表(每天的 N 篇文章把这组 query 轮流分组,
    # 一篇文章挂多条 query,生成正文时要求自然覆盖这组问题)。
    monitored_set = set(monitored)
    seed_to_queries: dict[str, list[str]] = {}
    try:
        qarr = json.loads(topic.queries_json or "[]")
    except Exception:  # noqa: BLE001
        qarr = []
    for qd in qarr:
        if not (isinstance(qd, dict) and qd.get("text")):
            continue
        if qd["text"] not in monitored_set:
            continue
        seed_to_queries.setdefault(str(qd.get("seed") or ""), []).append(str(qd["text"]))

    # 默认 platform — 走模板自带的 target_platforms 第一个,空则 fallback.
    def _default_platform(tmpl: ContentTemplateORM) -> str:
        try:
            platforms = json.loads(tmpl.target_platforms_json or "[]")
        except Exception:  # noqa: BLE001
            platforms = []
        if isinstance(platforms, list) and platforms:
            return str(platforms[0])
        return DEFAULT_PUBLISH_PLATFORMS[0]

    items: list[dict] = []
    seq = start_seq
    n_tmpl = len(picked_templates)
    for day_offset in range(days):
        seed_text = approved_seeds[day_offset % len(approved_seeds)]
        # 该种子下的 query 轮流分给当天的 N 篇(第 i 篇拿 i, i+N, i+2N…条)
        day_queries = seed_to_queries.get(seed_text) or []
        for ti, tmpl in enumerate(picked_templates):
            direction, ctype = _default_row_combo(tmpl.kind, day_offset + ti)
            items.append({
                "id": str(_uuid.uuid4()),
                "seq": seq,
                "publish_date": (start_date + timedelta(days=day_offset)).isoformat(),
                "seed": seed_text,
                "query": "",
                "queries": day_queries[ti::n_tmpl],
                "template_id": tmpl.id,
                "platform": _default_platform(tmpl),
                "note": None,
                "creation_directions": [direction],
                "copywriting_types": [ctype],
            })
            seq += 1
    return items


def _seed_initial_plan_items(
    db: Session, topic_id: int, monitored: list[str],
) -> list[dict]:
    """首批发文计划 — 从今天起铺满一个月(PLAN_WINDOW_DAYS).薄封装 _build_plan_window."""
    return _build_plan_window(
        db, topic_id, monitored,
        start_date=datetime.utcnow().date(),
        days=PLAN_WINDOW_DAYS, start_seq=0,
    )


def extend_plan_one_month(db: Session, plan: AiTelemetryTopicExecutionPlanORM) -> int:
    """计划 runway 不足时,从最后一天次日接排一个月(PLAN_WINDOW_DAYS).

    runway 充足(末尾日期距今 > PLAN_REFILL_LEAD_DAYS)时返回 0 不续期 —— 内置幂等,
    定时任务每天扫也只在临近末尾那次真正续.返回新增行数.
    """
    items = _load_publishing_items(plan)
    if not items:
        return 0

    def _pdate(it: dict):
        try:
            return datetime.fromisoformat(str(it.get("publish_date"))).date()
        except Exception:  # noqa: BLE001
            return None

    dates = [d for d in (_pdate(it) for it in items) if d is not None]
    if not dates:
        return 0
    last_date = max(dates)
    today = datetime.utcnow().date()
    if (last_date - today).days > PLAN_REFILL_LEAD_DAYS:
        return 0  # runway 还够,不续

    try:
        monitored = json.loads(plan.monitored_queries_snapshot_json or "[]")
    except Exception:  # noqa: BLE001
        monitored = []
    monitored = [str(x) for x in monitored if x] if isinstance(monitored, list) else []

    # 正常滚动从末尾次日接排;老的一次性计划末尾已是过去日期时,从今天接排,避免排出过去日期.
    next_start = max(last_date + timedelta(days=1), today)
    max_seq = max((int(it.get("seq") or 0) for it in items), default=-1)
    new_items = _build_plan_window(
        db, plan.topic_id, monitored,
        start_date=next_start,
        days=PLAN_WINDOW_DAYS, start_seq=max_seq + 1,
    )
    if not new_items:
        return 0
    items.extend(new_items)
    plan.publishing_plan_json = json.dumps(items, ensure_ascii=False)
    plan.last_edited_at = datetime.utcnow()
    db.commit()
    return len(new_items)


def _enrich_publishing_items(
    db: Session, plan_id: int, topic_id: int,
    monitored: list[str], items: list[dict],
) -> list[PublishPlanItem]:
    """把持久化的发文行 + 实时聚合(命中率 / doc / template) 拼成 PublishPlanItem 列表."""
    # 1) 命中率聚合
    cells = (
        db.query(AiTelemetryQueryHitORM)
          .filter(AiTelemetryQueryHitORM.topic_id == topic_id)
          .all()
    )
    by_query: dict[str, dict] = {}
    for c in cells:
        agg = by_query.setdefault(c.query, {"runs": 0, "hits": 0})
        agg["runs"] += c.total_runs or 0
        agg["hits"] += c.total_hits or 0

    # 2) doc 关联 — 优先 plan_item_id,fallback source_query_text(老数据)
    docs = (
        db.query(TopicGeneratedDocORM)
          .filter(TopicGeneratedDocORM.topic_id == topic_id)
          .filter(
              (TopicGeneratedDocORM.execution_plan_id == plan_id) |
              (TopicGeneratedDocORM.execution_plan_id.is_(None))
          )
          .all()
    )
    doc_by_item: dict[str, TopicGeneratedDocORM] = {}
    doc_by_query: dict[str, TopicGeneratedDocORM] = {}
    for d in docs:
        if d.plan_item_id and d.plan_item_id not in doc_by_item:
            doc_by_item[d.plan_item_id] = d
        if d.source_query_text and d.source_query_text not in doc_by_query:
            doc_by_query[d.source_query_text] = d

    # 3) 模板批量取
    tmpl_ids = {it.get("template_id") for it in items if it.get("template_id")}
    tmpl_by_id: dict[int, ContentTemplateORM] = {}
    if tmpl_ids:
        for tmpl in (
            db.query(ContentTemplateORM)
              .filter(ContentTemplateORM.id.in_(list(tmpl_ids)))
              .all()
        ):
            tmpl_by_id[tmpl.id] = tmpl

    out: list[PublishPlanItem] = []
    for it in sorted(items, key=lambda x: (x.get("seq") or 0, x.get("publish_date") or "")):
        q = str(it.get("query") or "")
        seed = str(it.get("seed") or "")
        row_queries = [str(x) for x in (it.get("queries") or []) if str(x).strip()]
        # 覆盖率:多选行按这组 query 聚合;legacy 行用 query 反查;seed-based 行用「种子下所有 query」的聚合.
        if row_queries:
            runs = sum(by_query.get(k, {"runs": 0})["runs"] for k in row_queries)
            hits = sum(by_query.get(k, {"hits": 0})["hits"] for k in row_queries)
        elif seed:
            runs = sum(v["runs"] for k, v in by_query.items()
                       if k in monitored and _query_seed_of(monitored, k) == seed)
            hits = sum(v["hits"] for k, v in by_query.items()
                       if k in monitored and _query_seed_of(monitored, k) == seed)
        else:
            agg = by_query.get(q, {"runs": 0, "hits": 0})
            runs, hits = agg["runs"], agg["hits"]
        cov = round(hits / runs * 100, 1) if runs > 0 else 0.0
        if cov == 0:
            priority = "high"
        elif cov < 50:
            priority = "med"
        else:
            priority = "low"

        item_id = str(it.get("id") or "")
        d = doc_by_item.get(item_id) or (doc_by_query.get(q) if q else None)
        tmpl = tmpl_by_id.get(it.get("template_id")) if it.get("template_id") else None
        suggested: list[str] = []
        if tmpl:
            try:
                raw = json.loads(tmpl.target_platforms_json or "[]")
                if isinstance(raw, list):
                    suggested = [str(p) for p in raw if p]
            except Exception:  # noqa: BLE001
                suggested = []
        if not suggested:
            suggested = list(DEFAULT_PUBLISH_PLATFORMS)

        out.append(PublishPlanItem(
            id=item_id,
            seq=int(it.get("seq") or 0),
            publish_date=str(it.get("publish_date") or ""),
            seed=seed or None,
            query=q,
            queries=row_queries,
            template_id=it.get("template_id"),
            platform=it.get("platform"),
            note=it.get("note"),
            creation_directions=[s for s in (it.get("creation_directions") or []) if s],
            copywriting_types=[s for s in (it.get("copywriting_types") or []) if s],
            day=int(it.get("seq") or 0),     # 兼容旧字段
            coverage_pct=cov,
            priority=priority,
            doc_id=d.id if d else None,
            doc_status=d.status if d else None,
            template_name=tmpl.name if tmpl else None,
            template_kind=tmpl.kind if tmpl else None,
            suggested_platforms=suggested,
        ))
    return out


def _query_seed_of(_monitored: list[str], _query: str) -> str:
    """[占位] query → seed 反查.目前 topic.queries_json/query_seeds 关系没拉进来,
    返回空串(seed-based 覆盖率回退到「按种子算 0%」).日后需要时联表查 query_seeds.
    """
    return ""


def _build_publishing_plan(
    db: Session, topic_id: int,
    monitored: list[str], overview: dict,
) -> list[PublishPlanItem]:
    """[兼容] 老调用点用 — 直接走"现算"路径,不读 publishing_plan_json.

    新代码改走 _enrich_publishing_items(items_from_json).
    """
    items = _seed_initial_plan_items(db, topic_id, monitored)
    return _enrich_publishing_items(db, 0, topic_id, monitored, items)


def _load_publishing_items(plan: AiTelemetryTopicExecutionPlanORM) -> list[dict]:
    """读出 publishing_plan_json 的存储格式(list[dict]).非法 / 空时返回 []."""
    try:
        items = json.loads(plan.publishing_plan_json or "[]")
    except Exception:  # noqa: BLE001
        items = []
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict)]


def _to_plan_out(db: Session, plan: AiTelemetryTopicExecutionPlanORM) -> TopicExecutionPlanOut:
    overview = json.loads(plan.overview_json or "{}")
    if not isinstance(overview, dict):
        overview = {}
    changelog = [
        TopicChangelogEntry(**e) for e in _parse_log_list(plan.topic_changelog_snapshot_json)
        if "at" in e
    ]
    expansion = [
        ExpansionLogEntry(**e) for e in _parse_log_list(plan.expansion_log_snapshot_json)
        if "at" in e
    ]
    try:
        monitored = json.loads(plan.monitored_queries_snapshot_json or "[]")
    except Exception:  # noqa: BLE001
        monitored = []
    if not isinstance(monitored, list):
        monitored = []
    monitored = [str(x) for x in monitored if x]

    # 实时聚合运行进度
    run_status: str | None = None
    progress_cells: list[TopicProgressCell] = []
    done = 0
    if plan.run_id:
        run = db.get(AiTelemetryRunORM, plan.run_id)
        run_status = run.status if run else None
        cells = (
            db.query(AiTelemetryQueryHitORM)
              .filter(AiTelemetryQueryHitORM.topic_id == plan.topic_id)
              .all()
        )
        for c in cells:
            if c.query not in monitored:
                continue
            progress_cells.append(TopicProgressCell(
                query=c.query, engine=c.engine, status=c.status,
                hit=(True if (c.total_hits or 0) > 0
                     else (False if c.status == "done" else None)),
                last_checked_at=c.last_checked_at,
            ))
            if c.status == "done":
                done += 1

    # 发文表:读持久化 items;首次为空 → 用 monitored 种子一份并回写,自迁移老数据.
    raw_items = _load_publishing_items(plan)
    if not raw_items and monitored:
        raw_items = _seed_initial_plan_items(db, plan.topic_id, monitored)
        plan.publishing_plan_json = json.dumps(raw_items, ensure_ascii=False)
        db.commit()
        db.refresh(plan)
    publishing_plan = _enrich_publishing_items(
        db, plan.id, plan.topic_id, monitored, raw_items,
    )

    return TopicExecutionPlanOut(
        id=plan.id, topic_id=plan.topic_id,
        generated_at=plan.generated_at,
        generated_by_reviewer_id=plan.generated_by_reviewer_id,
        status=plan.status, error=plan.error,
        overview=overview,
        topic_changelog=changelog,
        expansion_log=expansion,
        monitored_queries=monitored,
        run_id=plan.run_id, run_status=run_status,
        progress=progress_cells,
        progress_done=done,
        progress_total=len(progress_cells),
        publishing_plan=publishing_plan,
        confirmed_at=plan.confirmed_at,
        confirmed_by_id=plan.confirmed_by_id,
        last_edited_at=plan.last_edited_at,
    )


@router.get("/topic/{topic_id}/execution-plan", response_model=TopicExecutionPlanOut)
def get_execution_plan(
    topic_id: int,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """拿这个 topic 最新的执行计划书(含运行进度).没有则 404."""
    plan = (
        db.query(AiTelemetryTopicExecutionPlanORM)
          .filter(AiTelemetryTopicExecutionPlanORM.topic_id == topic_id)
          .order_by(AiTelemetryTopicExecutionPlanORM.id.desc())
          .first()
    )
    if not plan:
        raise HTTPException(404, "no execution plan generated")
    return _to_plan_out(db, plan)


def _latest_plan_or_404(db: Session, topic_id: int) -> AiTelemetryTopicExecutionPlanORM:
    plan = (
        db.query(AiTelemetryTopicExecutionPlanORM)
          .filter(AiTelemetryTopicExecutionPlanORM.topic_id == topic_id)
          .order_by(AiTelemetryTopicExecutionPlanORM.id.desc())
          .first()
    )
    if not plan:
        raise HTTPException(404, "no execution plan")
    return plan


def _validate_plan_items(
    db: Session, monitored: list[str], items: list[PlanItemDraft],
) -> list[dict]:
    """PUT /execution-plan 入参校验 + 转存储格式(list[dict]).

    - seed 或 query 至少有一个非空
    - 若 query 非空,必 ∈ monitored;seed-based 行允许 query 为空
    - template_id 必存在
    - platform 必 ∈ template.target_platforms (空列表则不限制)
    返回写回 publishing_plan_json 的 list[dict].
    """
    import uuid as _uuid
    monitored_set = set(monitored)
    out: list[dict] = []
    for it in items:
        q = (it.query or "").strip()
        seed = (it.seed or "").strip()
        # 2026-06-11 — 多选 queries:去空去重保序,每条必 ∈ monitored
        queries = list(dict.fromkeys(
            str(x).strip() for x in (it.queries or []) if str(x).strip()
        ))
        if not q and not seed and not queries:
            raise HTTPException(422, {
                "code": "MISSING_TOPIC", "field": "seed",
                "message": "seed 与 query 至少要填一个",
            })
        if q and q not in monitored_set:
            raise HTTPException(422, {
                "code": "INVALID_QUERY", "field": "query",
                "message": f"query 不在监测列表里:{q}",
            })
        bad_q = [x for x in queries if x not in monitored_set]
        if bad_q:
            raise HTTPException(422, {
                "code": "INVALID_QUERY", "field": "queries",
                "message": f"query 不在监测列表里:{bad_q[0]}",
            })
        tmpl = db.get(ContentTemplateORM, it.template_id)
        if not tmpl:
            raise HTTPException(422, {
                "code": "INVALID_TEMPLATE", "field": "template_id",
                "message": f"模板不存在:{it.template_id}",
            })
        try:
            allowed = json.loads(tmpl.target_platforms_json or "[]")
        except Exception:  # noqa: BLE001
            allowed = []
        if isinstance(allowed, list) and allowed and it.platform not in allowed:
            raise HTTPException(422, {
                "code": "INVALID_PLATFORM", "field": "platform",
                "message": f"平台 {it.platform} 不在模板「{tmpl.name}」的适用平台里",
            })
        out.append({
            "id": it.id or str(_uuid.uuid4()),
            "seq": it.seq,
            "publish_date": it.publish_date,
            "seed": seed or None,
            "query": q,
            "queries": queries,
            "template_id": it.template_id,
            "platform": it.platform,
            "note": (it.note or None),
            # 2026-06-12 — 之前这里把行级创作偏好丢了(编辑器勾了也不落库),补上
            "creation_directions": [s for s in (it.creation_directions or []) if s],
            "copywriting_types": [s for s in (it.copywriting_types or []) if s],
        })
    # 归一化 seq:按入参顺序 0..N
    out.sort(key=lambda x: (x.get("seq", 0)))
    for idx, row in enumerate(out):
        row["seq"] = idx
    return out


@router.put("/topic/{topic_id}/execution-plan", response_model=TopicExecutionPlanOut)
def update_execution_plan(
    topic_id: int,
    payload: ExecutionPlanUpdatePayload,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """整段替换发文表(draft / confirmed 都允许).

    confirmed 状态下调用不会退回 draft,也不会清掉已生成的 docs;新增行
    则在下次 confirm 或被运营点 [↻] 时再生成。
    """
    plan = _latest_plan_or_404(db, topic_id)
    monitored = json.loads(plan.monitored_queries_snapshot_json or "[]") or []
    monitored = [str(x) for x in monitored if x]
    new_items = _validate_plan_items(db, monitored, payload.items)
    plan.publishing_plan_json = json.dumps(new_items, ensure_ascii=False)
    plan.last_edited_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)
    return _to_plan_out(db, plan)


@router.post("/topic/{topic_id}/execution-plan/confirm", response_model=TopicExecutionPlanOut)
def confirm_execution_plan(
    topic_id: int,
    background: BackgroundTasks,
    force: bool = False,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """确认发文表,触发文章生成.

    - status=draft → 全表生成,落 confirmed
    - status=confirmed:幂等 — 默认只对**还没出稿的 plan_item** 派单条生成;
      ?force=true 强制全表重生
    """
    plan = _latest_plan_or_404(db, topic_id)
    items = _load_publishing_items(plan)
    if not items:
        raise HTTPException(422, {
            "code": "EMPTY_PLAN", "message": "发文表为空,请先添加至少一行",
        })

    if plan.status == "draft":
        plan.status = "confirmed"
        plan.confirmed_at = datetime.utcnow()
        plan.confirmed_by_id = admin.id
        db.commit()
        db.refresh(plan)
        _kick_content_generation(plan, background)
    else:
        # confirmed → 默认增量:只对没出稿的 item;force=True 强制全量
        if force:
            _kick_content_generation(plan, background)
        else:
            done_ids = {
                d.plan_item_id for d in (
                    db.query(TopicGeneratedDocORM)
                      .filter(TopicGeneratedDocORM.topic_id == topic_id)
                      .filter(TopicGeneratedDocORM.plan_item_id.isnot(None))
                      .all()
                ) if d.plan_item_id
            }
            todo = [it["id"] for it in items if it.get("id") and it["id"] not in done_ids]
            if todo:
                _kick_content_generation(plan, background, plan_item_ids=todo)
    return _to_plan_out(db, plan)


@router.post(
    "/topic/{topic_id}/execution-plan/items/{item_id}/regenerate",
    response_model=TopicExecutionPlanOut,
)
def regenerate_plan_item(
    topic_id: int, item_id: str,
    background: BackgroundTasks,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """单条重生:把对应 doc 置 draft + 清正文 + 派单条生成任务."""
    plan = _latest_plan_or_404(db, topic_id)
    items = _load_publishing_items(plan)
    if not any(it.get("id") == item_id for it in items):
        raise HTTPException(404, "plan item not found")
    if plan.status != "confirmed":
        raise HTTPException(409, {
            "code": "NOT_CONFIRMED",
            "message": "请先确认执行计划再重生单条",
        })
    d = (
        db.query(TopicGeneratedDocORM)
          .filter(TopicGeneratedDocORM.topic_id == topic_id,
                  TopicGeneratedDocORM.plan_item_id == item_id)
          .first()
    )
    if d:
        d.status = "draft"
        d.generation_error = None
        # 不清 body,避免运营改过的内容被瞬间擦掉;LLM 跑成功会覆写
        db.commit()
    _kick_content_generation(plan, background, plan_item_ids=[item_id])
    db.refresh(plan)
    return _to_plan_out(db, plan)


@router.post("/topic/{topic_id}/rerun", response_model=TopicExecutionPlanOut)
def rerun_topic(
    topic_id: int,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """重新触发跑批 — 给 plan failed / run_id 缺失 / 想再跑一次的场景用.

    调用 telemetry-service /run-topic 拿新 run_id,
    更新当前 topic 最新的 execution plan(run_id / status / error)并返回.
    没 plan 时新建一条.
    """
    t = _load_topic_or_404(db, topic_id)
    run_id = _trigger_run_topic_sync(topic_id)

    plan = (
        db.query(AiTelemetryTopicExecutionPlanORM)
          .filter(AiTelemetryTopicExecutionPlanORM.topic_id == topic_id)
          .order_by(AiTelemetryTopicExecutionPlanORM.id.desc())
          .first()
    )
    if plan is None:
        # 没历史 plan,直接补一条 draft
        snapshot = _build_execution_plan_snapshot(t, run_id)
        plan = AiTelemetryTopicExecutionPlanORM(
            topic_id=topic_id,
            generated_by_reviewer_id=admin.id,
            overview_json=json.dumps(snapshot["overview"], ensure_ascii=False),
            topic_changelog_snapshot_json=json.dumps(snapshot["changelog"], ensure_ascii=False),
            expansion_log_snapshot_json=json.dumps(snapshot["expansion_log"], ensure_ascii=False),
            monitored_queries_snapshot_json=json.dumps(snapshot["monitored_queries"], ensure_ascii=False),
            publishing_plan_json="[]",
            run_id=run_id,
            status="draft" if run_id is not None else "failed",
            error=None if run_id is not None else "telemetry-service /run-topic failed",
        )
        db.add(plan)
    else:
        # 只刷新 run_id,不动 status —— confirmed 计划不能因为重跑监控就退回 draft
        plan.run_id = run_id
        if run_id is None:
            plan.status = "failed"
            plan.error = "telemetry-service /run-topic failed"
        else:
            plan.error = None
        plan.generated_at = datetime.utcnow()
        plan.generated_by_reviewer_id = admin.id

    _append_changelog(t, actor_id=admin.id, actor_role="admin",
                      field="rerun", after=f"run_id={run_id}",
                      note="admin 手动重新触发跑批")

    db.commit()
    db.refresh(plan)
    return _to_plan_out(db, plan)


@router.post("/topic/{topic_id}/execution-plan/regenerate", response_model=TopicExecutionPlanOut)
def regenerate_execution_plan(
    topic_id: int,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """重新生成计划书快照 — 用 topic 当前的 资料 / 监测问题 / 日志 重建三份快照.

    给「审核通过后又改了种子词 / 扩展词」的场景用:计划书展示的快照是
    生成那一刻的冻结副本,topic 后续编辑不会自动同步,需要 admin 手动重建。
    发文表(publishing_plan_json)与 status / run_id / confirmed_at 都保持不动,
    只刷新快照与 generated_at / generated_by_reviewer_id。
    """
    t = _load_topic_or_404(db, topic_id)
    plan = _latest_plan_or_404(db, topic_id)
    snapshot = _build_execution_plan_snapshot(t, plan.run_id)
    plan.overview_json = json.dumps(snapshot["overview"], ensure_ascii=False)
    plan.topic_changelog_snapshot_json = json.dumps(snapshot["changelog"], ensure_ascii=False)
    plan.expansion_log_snapshot_json = json.dumps(snapshot["expansion_log"], ensure_ascii=False)
    plan.monitored_queries_snapshot_json = json.dumps(snapshot["monitored_queries"], ensure_ascii=False)
    plan.generated_at = datetime.utcnow()
    plan.generated_by_reviewer_id = admin.id
    _append_changelog(t, actor_id=admin.id, actor_role="admin",
                      field="execution_plan",
                      after=f"queries={len(snapshot['monitored_queries'])}",
                      note="admin 重新生成计划书快照")
    db.commit()
    db.refresh(plan)
    return _to_plan_out(db, plan)


# ═════════════════ v3.3 — GEO 品牌增长战略方案 ═════════════════


def _solution_to_out(sol: AiTelemetryTopicSolutionORM) -> TopicSolutionOut:
    """ORM → TopicSolutionOut。status != ready 时各内容块为 None / 空,
    前端按 status 渲染 loading / error / content 三态."""
    diagnosis: SolutionDiagnosis | None = None
    seven_steps: list[SolutionSevenStepItem] = []
    keyword_tiers: list[SolutionKeywordTier] = []
    vision: list[SolutionVisionItem] = []
    brand_snapshot: BrandProfile | None = None
    queries_snapshot: SolutionQueriesSnapshot | None = None

    if sol.status == "ready":
        try:
            d = json.loads(sol.diagnosis_json or "{}")
        except Exception:  # noqa: BLE001
            d = {}
        try:
            n = json.loads(sol.narrative_json or "{}")
        except Exception:  # noqa: BLE001
            n = {}
        try:
            k = json.loads(sol.keywords_json or "{}")
        except Exception:  # noqa: BLE001
            k = {}
        try:
            bp = json.loads(sol.brand_snapshot_json or "{}")
        except Exception:  # noqa: BLE001
            bp = {}

        if isinstance(bp, dict):
            try:
                brand_snapshot = BrandProfile(**bp)
            except Exception:  # noqa: BLE001
                brand_snapshot = None

        if isinstance(d, dict) and d:
            clusters_raw = d.get("clusters") or []
            cluster_summaries = (n.get("cluster_summaries") if isinstance(n, dict) else {}) or {}
            clusters: list[SolutionDiagnosisCluster] = []
            for c in clusters_raw:
                if not isinstance(c, dict):
                    continue
                checks_raw = c.get("checks") or []
                checks_typed = [
                    SolutionDiagnosisCheck(
                        category=str(x.get("category") or ""),
                        status=str(x.get("status") or ""),
                        message=str(x.get("message") or ""),
                        fix=(str(x.get("fix")) if x.get("fix") else None),
                    )
                    for x in checks_raw if isinstance(x, dict)
                ]
                clusters.append(SolutionDiagnosisCluster(
                    key=str(c.get("key") or ""),
                    title_zh=str(c.get("title_zh") or ""),
                    severity=str(c.get("severity") or "low"),
                    summary=str(cluster_summaries.get(c.get("key")) or c.get("summary") or ""),
                    bullets=[str(b) for b in (c.get("bullets") or []) if b],
                    checks=checks_typed,
                ))
            all_checks_raw = d.get("all_checks") or []
            all_checks_typed = [
                SolutionDiagnosisCheck(
                    category=str(x.get("category") or ""),
                    status=str(x.get("status") or ""),
                    message=str(x.get("message") or ""),
                    fix=(str(x.get("fix")) if x.get("fix") else None),
                )
                for x in all_checks_raw if isinstance(x, dict)
            ]
            diagnosis = SolutionDiagnosis(
                url=str(d.get("url") or sol.website_url),
                score=int(d.get("score") or 0),
                grade=str(d.get("grade") or ""),
                pass_count=int(d.get("pass_count") or 0),
                warn_count=int(d.get("warn_count") or 0),
                fail_count=int(d.get("fail_count") or 0),
                info_count=int(d.get("info_count") or 0),
                clusters=clusters,
                execution_layers=[x for x in (d.get("execution_layers") or []) if isinstance(x, dict)],
                all_checks=all_checks_typed,
            )

        if isinstance(n, dict):
            for s in n.get("seven_steps") or []:
                if not isinstance(s, dict):
                    continue
                try:
                    seven_steps.append(SolutionSevenStepItem(
                        step=int(s.get("step") or 0),
                        name=str(s.get("name") or ""),
                        core_goal=str(s.get("core_goal") or ""),
                        core_action=str(s.get("core_action") or ""),
                        output_value=str(s.get("output_value") or ""),
                    ))
                except Exception:  # noqa: BLE001
                    continue
            for v in n.get("vision") or []:
                if not isinstance(v, dict):
                    continue
                vision.append(SolutionVisionItem(
                    title=str(v.get("title") or ""),
                    body=str(v.get("body") or ""),
                ))

        if isinstance(k, dict):
            for tt in k.get("tiers") or []:
                if not isinstance(tt, dict):
                    continue
                keyword_tiers.append(SolutionKeywordTier(
                    tier=str(tt.get("tier") or ""),
                    title_zh=str(tt.get("title_zh") or ""),
                    description=str(tt.get("description") or ""),
                    keywords=[str(x) for x in (tt.get("keywords") or []) if str(x).strip()],
                ))

        try:
            q = json.loads(sol.queries_snapshot_json or "{}")
        except Exception:  # noqa: BLE001
            q = {}
        if isinstance(q, dict) and (q.get("queries") or q.get("clusters")):
            query_items: list[SolutionQueryItem] = []
            for item in (q.get("queries") or []):
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                try:
                    cid = int(item.get("cluster_id", -1))
                except (TypeError, ValueError):
                    cid = -1
                query_items.append(SolutionQueryItem(
                    text=text, cluster_id=cid,
                    seed=str(item.get("seed") or ""),
                ))
            cluster_items: list[SolutionQueryCluster] = []
            for c in (q.get("clusters") or []):
                if not isinstance(c, dict):
                    continue
                try:
                    cid = int(c.get("cluster_id"))
                except (TypeError, ValueError):
                    continue
                label = str(c.get("label") or "").strip()
                if not label:
                    continue
                cluster_items.append(SolutionQueryCluster(cluster_id=cid, label=label))
            queries_snapshot = SolutionQueriesSnapshot(
                clusters=cluster_items, queries=query_items,
            )
        else:
            queries_snapshot = None
    else:
        queries_snapshot = None

    return TopicSolutionOut(
        id=sol.id, topic_id=sol.topic_id, status=sol.status or "idle",
        website_url=sol.website_url or "",
        error=sol.error, generated_by_admin_id=sol.generated_by_admin_id,
        llm_model=sol.llm_model or "",
        created_at=sol.created_at, updated_at=sol.updated_at,
        brand_snapshot=brand_snapshot, diagnosis=diagnosis,
        seven_steps=seven_steps, keyword_tiers=keyword_tiers, vision=vision,
        queries_snapshot=queries_snapshot,
    )


@router.get("/topic/{topic_id}/solution", response_model=TopicSolutionOut)
def get_strategic_solution(
    topic_id: int,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """拿这个 topic 最新的战略方案。无记录时返回 status='idle' 的存根 —
    前端按 status 切「未生成 / 生成中 / 已生成 / 失败」四态,不用关心 404."""
    _load_topic_or_404(db, topic_id)   # 校验 topic 存在
    sol = (
        db.query(AiTelemetryTopicSolutionORM)
          .filter(AiTelemetryTopicSolutionORM.topic_id == topic_id)
          .first()
    )
    if not sol:
        return TopicSolutionOut(
            id=0, topic_id=topic_id, status="idle", website_url="",
            error=None, generated_by_admin_id=None, llm_model="",
            created_at=None, updated_at=None,
            brand_snapshot=None, diagnosis=None,
            seven_steps=[], keyword_tiers=[], vision=[],
            queries_snapshot=None,
        )
    # 双保险:startup 兜底之外,读路径再检一次。daemon thread 死掉时 updated_at
    # 不会再涨,超过阈值即视为僵尸 — 翻成 failed 让前端能拿到重试入口。
    if sol.status == "generating":
        from geo.services.solution_generator import STALE_GENERATING_THRESHOLD
        if sol.updated_at and datetime.utcnow() - sol.updated_at > STALE_GENERATING_THRESHOLD:
            sol.status = "failed"
            sol.error = "后端在生成途中重启,后台任务被中断。请点重试重新生成。"
            sol.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(sol)
    return _solution_to_out(sol)


def _trigger_solution_generation(topic_id: int, website_url: str, admin_id: int) -> None:
    """后台触发战略方案生成 — 走 solution_generator 的 daemon thread."""
    try:
        from geo.services.solution_generator import schedule_solution_generation
        schedule_solution_generation(
            topic_id=topic_id, website_url=website_url, admin_id=admin_id,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("schedule solution generation failed: %s", e)


@router.post("/topic/{topic_id}/solution/generate", response_model=TopicSolutionOut)
def generate_strategic_solution(
    topic_id: int,
    payload: GenerateSolutionPayload,
    background: BackgroundTasks,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """触发(或重新触发)战略方案生成 — 异步后台跑.

    流程:
      1. 先 upsert solution 行,status=generating + website_url + 清空 error
      2. BackgroundTasks 触发 solution_generator daemon thread
      3. 立刻返回 status=generating 给前端;前端 3s 轮询 GET solution 直到 ready/failed
    """
    t = _load_topic_or_404(db, topic_id)

    sol = (
        db.query(AiTelemetryTopicSolutionORM)
          .filter(AiTelemetryTopicSolutionORM.topic_id == topic_id)
          .first()
    )
    if sol is None:
        sol = AiTelemetryTopicSolutionORM(topic_id=topic_id)
        db.add(sol)
    sol.status = "generating"
    sol.website_url = payload.website_url.strip()
    sol.error = None
    sol.generated_by_admin_id = admin.id
    sol.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(sol)

    background.add_task(
        _trigger_solution_generation,
        topic_id=topic_id, website_url=sol.website_url, admin_id=admin.id,
    )
    _append_changelog(t, actor_id=admin.id, actor_role="admin",
                      field="solution", after=sol.website_url,
                      note="admin 触发战略方案生成")
    db.commit()
    return _solution_to_out(sol)


# ════════════ 去审核新通道:POST /admin/topics/{id}/start ════════════
# 替代 approve_topic 在新流程里的位置.状态翻转那一段(approve_topic 步骤 1/2)
# 不再需要,因为 admin 直建主题已经落 submission_status=approved.start 只负责
# 触发后续 5 个副作用(跑分 / plan / 文案 / 邮件).
#
# 幂等规则:同 topic 已有 ready/generating 的 plan 时,GET 行为(返回最新一条);
# 只有显式 ?force=true 才重新触发.前端「重新启动」按钮带 force=true.


def _validate_topic_runnable(t: AiTelemetryTopicORM) -> None:
    """启动前校验:画像必填齐 + ≥1 个 selected query + ≥1 engine.沿用 submit 那套逻辑."""
    try:
        profile_raw = json.loads(t.profile_json or "{}")
    except Exception:  # noqa: BLE001
        profile_raw = {}
    if not isinstance(profile_raw, dict):
        profile_raw = {}
    missing: list[str] = []
    for f in PROFILE_REQUIRED_FIELDS:
        v = profile_raw.get(f)
        if v is None or v == "" or v == [] or v == {}:
            missing.append(f)
    if missing:
        raise HTTPException(422, {
            "code": "PROFILE_INCOMPLETE", "field": "profile",
            "message": "资料必填项缺失", "missing": missing,
        })

    try:
        qarr = json.loads(t.queries_json or "[]")
    except Exception:  # noqa: BLE001
        qarr = []
    selected_n = sum(
        1 for q in qarr
        if isinstance(q, dict) and q.get("text") and q.get("selected", True)
    )
    if selected_n < 1:
        raise HTTPException(422, {
            "code": "NO_SELECTED", "field": "queries",
            "message": "请至少勾选 1 个监测问题",
        })
    if selected_n > MAX_SELECTED_QUERIES:
        raise HTTPException(422, {
            "code": "TOO_MANY_SELECTED", "field": "queries",
            "message": f"最多 {MAX_SELECTED_QUERIES} 个监测问题,当前 {selected_n}",
        })

    try:
        engines = json.loads(t.engines_json or "[]")
    except Exception:  # noqa: BLE001
        engines = []
    if not isinstance(engines, list) or len(engines) < 1:
        raise HTTPException(422, {
            "code": "NO_ENGINE", "field": "engines",
            "message": "请至少选择 1 个引擎",
        })


@topics_router.post("/{topic_id}/start", response_model=TopicExecutionPlanOut)
def start_topic(
    topic_id: int,
    background: BackgroundTasks,
    force: bool = False,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """启动项目(去审核流).

    新流程:
    - 启动只触发**监控运行 + 落 draft plan**,**不**生成文章
    - 运营到执行计划页编辑发文表,点确认 → POST /execution-plan/confirm 才出文章
    - 默认幂等:同 topic 已有 draft/confirmed 的 plan → 直接返回最新一条
    - ?force=true → 跳过幂等,强制再触发一次(对应「重新启动」按钮)
    - 校验:画像必填齐 + ≥1 selected query + ≥1 engine
    """
    t = _load_topic_or_404(db, topic_id)
    _validate_topic_runnable(t)

    if not force:
        existing = (
            db.query(AiTelemetryTopicExecutionPlanORM)
              .filter(AiTelemetryTopicExecutionPlanORM.topic_id == topic_id)
              .order_by(AiTelemetryTopicExecutionPlanORM.id.desc())
              .first()
        )
        # 兼容老 status 值 ready / generating
        if existing and existing.status in ("draft", "confirmed", "ready", "generating"):
            return _to_plan_out(db, existing)

    # 若 topic 还在 draft(用户自建未提交),启动顺便翻成 approved.
    # admin 直建本来就是 approved,此处幂等.
    if t.submission_status != "approved":
        prev = t.submission_status
        t.submission_status = "approved"
        t.approved_at = datetime.utcnow()
        t.rejected_at = None
        t.reviewer_id = admin.id
        _append_changelog(t, actor_id=admin.id, actor_role="admin",
                          field="submission_status", before=prev, after="approved",
                          note="start_topic")
    db.commit()
    db.refresh(t)

    plan = _create_draft_plan(db, t, admin.id, background)
    return _to_plan_out(db, plan)
