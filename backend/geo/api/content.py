"""Phase D.1 — 用户侧内容 API.

合并原本前端分散的 /dashboard/compose 与 /dashboard/posts 两屏对应的能力:

  - GET    /api/content/topics/{topic_id}/docs?status=&source=  — 当前用户某 topic 下所有稿件
  - GET    /api/content/topics/{topic_id}/stats                  — 5 张统计卡聚合
  - POST   /api/content/topics/{topic_id}/docs                   — 用户提交自己写的文章
  - PATCH  /api/content/docs/{doc_id}                            — 用户编辑自己的 draft / rejected 稿
  - POST   /api/content/docs/{doc_id}/submit-review              — 把 draft 推 pending_review
  - PATCH  /api/content/topics/{topic_id}/auto-generate          — 设置 AI 自动生成排程
  - POST   /api/content/topics/{topic_id}/run-now                — 立即按当前配置跑一批
  - GET    /api/content/docs/{doc_id}                            — 单条详情

权限:所有端点都要求 owner = current_user(topic.user_id == current_user.id).
admin 可越权访问由 /api/admin/content-review/* 提供,这里不做。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from geo.api.auth import get_current_user
from geo.api.ai_telemetry import get_db
from geo.models.ai_telemetry import (
    AiTelemetryTopicORM, AutoGenerateConfigPayload,
    GeneratedDocOut, TopicGeneratedDocORM,
    UserDocSubmitPayload, UserDocUpdatePayload,
)
from geo.services.content_generator import schedule_generation

log = logging.getLogger(__name__)

router = APIRouter(prefix="/content")


_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _own_topic_or_404(
    db: Session, topic_id: int, user_id: int, *, allow_admin_user=None,
) -> AiTelemetryTopicORM:
    """常规 owner-only;传 allow_admin_user(is_admin=True)时放行 admin 跨用户只读。"""
    t = db.get(AiTelemetryTopicORM, topic_id)
    if not t:
        raise HTTPException(404, "topic not found")
    if t.user_id != user_id:
        if not (allow_admin_user is not None and getattr(allow_admin_user, "is_admin", False)):
            raise HTTPException(404, "topic not found")
    return t


def _own_doc_or_404(
    db: Session, doc_id: int, user_id: int, *, allow_admin_user=None,
) -> TopicGeneratedDocORM:
    d = db.get(TopicGeneratedDocORM, doc_id)
    if not d:
        raise HTTPException(404, "doc not found")
    t = db.get(AiTelemetryTopicORM, d.topic_id)
    if not t:
        raise HTTPException(404, "doc not found")
    if t.user_id != user_id:
        if not (allow_admin_user is not None and getattr(allow_admin_user, "is_admin", False)):
            raise HTTPException(404, "doc not found")
    return d


# ─────────────────────── 列表 / 详情 ──────────────────────────

class ContentStats(BaseModel):
    draft: int
    pending_review: int
    approved: int
    rejected: int
    published: int
    total: int
    ai_count: int
    user_count: int


@router.get("/topics/{topic_id}/docs", response_model=list[GeneratedDocOut])
def list_my_docs(
    topic_id: int,
    status: Optional[str] = None,
    source: Optional[str] = None,
    query_hit: Optional[str] = None,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """投放战报页 / Content 列表通用接口。

    - status: 单状态 / `to_review` / None=全部
    - source: ai / user
    - query_hit: `hit` = AI 真实引用过 doc 的投放 URL(看 cited_by_json);
                 `miss` = 有投放 URL 但还没被引;None 不筛
    """
    _own_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    q = db.query(TopicGeneratedDocORM).filter(TopicGeneratedDocORM.topic_id == topic_id)
    if status:
        if status == "to_review":
            q = q.filter(TopicGeneratedDocORM.status.in_(["draft", "pending_review"]))
        else:
            q = q.filter(TopicGeneratedDocORM.status == status)
    if source in ("ai", "user"):
        q = q.filter(TopicGeneratedDocORM.source == source)
    rows = q.order_by(TopicGeneratedDocORM.id.desc()).all()

    if query_hit in ("hit", "miss"):
        def _has_publish_url(r: TopicGeneratedDocORM) -> bool:
            return bool(r.publish_targets_json and r.publish_targets_json not in ("", "[]"))

        def _is_cited(r: TopicGeneratedDocORM) -> bool:
            raw = getattr(r, "cited_by_json", None) or "{}"
            if raw in ("", "{}"):
                return False
            try:
                data = json.loads(raw)
            except Exception:  # noqa: BLE001
                return False
            return isinstance(data, dict) and any(data.values())

        if query_hit == "hit":
            rows = [r for r in rows if _is_cited(r)]
        else:
            rows = [r for r in rows if _has_publish_url(r) and not _is_cited(r)]

    return [GeneratedDocOut.from_orm_row(r) for r in rows]


@router.get("/topics/{topic_id}/stats", response_model=ContentStats)
def topic_stats(
    topic_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _own_topic_or_404(db, topic_id, current_user.id, allow_admin_user=current_user)
    rows = (
        db.query(TopicGeneratedDocORM)
          .filter(TopicGeneratedDocORM.topic_id == topic_id)
          .all()
    )
    stats = ContentStats(
        draft=0, pending_review=0, approved=0, rejected=0, published=0,
        total=len(rows), ai_count=0, user_count=0,
    )
    for d in rows:
        st = (d.status or "").lower()
        if st == "draft":
            stats.draft += 1
        elif st == "pending_review":
            stats.pending_review += 1
        elif st == "approved":
            stats.approved += 1
        elif st == "rejected":
            stats.rejected += 1
        elif st == "published":
            stats.published += 1
        if (d.source or "ai") == "user":
            stats.user_count += 1
        else:
            stats.ai_count += 1
    return stats


@router.get("/docs/{doc_id}", response_model=GeneratedDocOut)
def get_doc(
    doc_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = _own_doc_or_404(db, doc_id, current_user.id, allow_admin_user=current_user)
    return GeneratedDocOut.from_orm_row(d)


# ─────────────────────── 用户提交 / 编辑 ──────────────────────

@router.post("/topics/{topic_id}/docs", response_model=GeneratedDocOut)
def submit_user_doc(
    topic_id: int,
    payload: UserDocSubmitPayload,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = _own_topic_or_404(db, topic_id, current_user.id)
    if (t.submission_status or "draft") != "approved":
        raise HTTPException(409, {
            "code": "TOPIC_NOT_APPROVED",
            "message": "主题资料还未审核通过,暂不能投稿",
        })
    d = TopicGeneratedDocORM(
        topic_id=topic_id,
        title=payload.title.strip(),
        body_markdown=payload.body_markdown,
        summary=(payload.summary or "")[:500],
        source_query_text=(payload.source_query_text or "").strip(),
        status="pending_review" if payload.submit_for_review else "draft",
        selected_for_review=bool(payload.submit_for_review),
        llm_model="",
        source="user",
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return GeneratedDocOut.from_orm_row(d)


@router.patch("/docs/{doc_id}", response_model=GeneratedDocOut)
def update_user_doc(
    doc_id: int,
    payload: UserDocUpdatePayload,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = _own_doc_or_404(db, doc_id, current_user.id)
    if d.source != "user":
        raise HTTPException(403, {
            "code": "AI_DOC_READONLY",
            "message": "AI 生成的稿件不能由用户直接编辑,请联系管理员",
        })
    if d.status not in ("draft", "rejected"):
        raise HTTPException(409, {
            "code": "WRONG_STATUS",
            "message": f"稿件 status={d.status},无法编辑",
        })
    if payload.title is not None:
        d.title = payload.title.strip()
    if payload.body_markdown is not None:
        d.body_markdown = payload.body_markdown
    if payload.summary is not None:
        d.summary = payload.summary[:500]
    if payload.source_query_text is not None:
        d.source_query_text = payload.source_query_text.strip()
    db.commit()
    db.refresh(d)
    return GeneratedDocOut.from_orm_row(d)


@router.post("/docs/{doc_id}/submit-review", response_model=GeneratedDocOut)
def submit_doc_for_review(
    doc_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把 draft / rejected 稿子推到 pending_review。

    用户可以重提自己被驳回的稿;AI 稿也可以由用户主动送审(不能编辑但能选择是否送审)。
    """
    d = _own_doc_or_404(db, doc_id, current_user.id)
    if d.status not in ("draft", "rejected"):
        raise HTTPException(409, {
            "code": "WRONG_STATUS",
            "message": f"稿件 status={d.status},无法提交审核",
        })
    d.status = "pending_review"
    d.selected_for_review = True
    d.reject_reason = None
    db.commit()
    db.refresh(d)
    return GeneratedDocOut.from_orm_row(d)


class RejectPayload(BaseModel):
    reason: str = ""


@router.post("/docs/{doc_id}/approve", response_model=GeneratedDocOut)
def approve_my_doc(
    doc_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户自审通过自己主题下的稿件(draft / pending_review → approved)。审核通过后可进入发布。"""
    from datetime import datetime

    d = _own_doc_or_404(db, doc_id, current_user.id)
    if d.status not in ("draft", "pending_review"):
        raise HTTPException(409, {"code": "WRONG_STATUS", "message": f"稿件 status={d.status},不可通过"})
    d.status = "approved"
    d.selected_for_review = True
    d.review_decision_at = datetime.utcnow()
    d.reviewer_id = current_user.id
    d.reject_reason = None
    db.commit()
    db.refresh(d)
    return GeneratedDocOut.from_orm_row(d)


@router.post("/docs/{doc_id}/reject", response_model=GeneratedDocOut)
def reject_my_doc(
    doc_id: int,
    payload: RejectPayload,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户自审驳回自己主题下的稿件(draft / pending_review → rejected,带原因)。驳回后可编辑重提。"""
    from datetime import datetime

    d = _own_doc_or_404(db, doc_id, current_user.id)
    if d.status not in ("draft", "pending_review"):
        raise HTTPException(409, {"code": "WRONG_STATUS", "message": f"稿件 status={d.status},不可驳回"})
    d.status = "rejected"
    d.review_decision_at = datetime.utcnow()
    d.reviewer_id = current_user.id
    d.reject_reason = (payload.reason or "").strip()[:500]
    db.commit()
    db.refresh(d)
    return GeneratedDocOut.from_orm_row(d)


# ─────────────────────── AI 自动生成排程 ──────────────────────

@router.patch("/topics/{topic_id}/auto-generate")
def configure_auto_generate(
    topic_id: int,
    payload: AutoGenerateConfigPayload,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = _own_topic_or_404(db, topic_id, current_user.id)
    if not _HH_MM_RE.match(payload.time):
        raise HTTPException(422, "time must be HH:MM 24h format")
    t.auto_generate_enabled = bool(payload.enabled)
    t.auto_generate_time = payload.time
    t.auto_generate_count = max(1, min(20, int(payload.count)))
    if payload.publish_enabled is not None:
        t.auto_publish_enabled = bool(payload.publish_enabled)
    db.commit()
    db.refresh(t)
    return {
        "auto_generate_enabled": t.auto_generate_enabled,
        "auto_generate_time": t.auto_generate_time,
        "auto_generate_count": t.auto_generate_count,
        "auto_publish_enabled": t.auto_publish_enabled,
        "auto_generate_last_run_at":
            t.auto_generate_last_run_at.isoformat() if t.auto_generate_last_run_at else None,
    }


@router.post("/topics/{topic_id}/run-now", status_code=202)
def run_now(
    topic_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """立即按当前 auto_generate_count(或 3 兜底)从 selected query 池里抽 N 条生成。

    不会改 auto_generate_last_run_at(那是 cron 自动跑批的指标)。
    """
    t = _own_topic_or_404(db, topic_id, current_user.id)
    if (t.submission_status or "draft") != "approved":
        raise HTTPException(409, {
            "code": "TOPIC_NOT_APPROVED",
            "message": "主题资料还未审核通过,暂不能触发生成",
        })
    n = int(t.auto_generate_count or 3)
    schedule_generation(
        topic_id=topic_id, max_docs=n, mark_auto_run=False,
    )
    log.info("user run-now content gen topic=%d count=%d", topic_id, n)
    return {"queued": n, "topic_id": topic_id}
