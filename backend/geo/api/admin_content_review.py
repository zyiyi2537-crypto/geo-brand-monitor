"""Phase D — Admin 内容审核 API.

文档生命周期:draft → pending_review → approved → published(或 rejected)

端点:
- GET    /admin/content-review/topics                — 列出有 docs 的 (account, topic) 二元组
- GET    /admin/content-review/topics/{topic_id}/docs?status=draft|all
- POST   /admin/content-review/docs/select           — 把勾选的 doc 切到 pending_review
- POST   /admin/content-review/docs/{id}/approve     — 单条通过
- POST   /admin/content-review/docs/{id}/reject      — 单条拒绝 + reason + 邮件
- POST   /admin/content-review/docs/{id}/publish     — 标记发布平台/媒体 + 邮件
"""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from geo.api.auth import require_admin
from geo.api.ai_telemetry import get_db
from geo.models.ai_telemetry import (
    AiTelemetryTopicORM, GeneratedDocOut, PublishPayload, RejectDocPayload,
    SelectDocsPayload, TopicGeneratedDocORM,
)
from geo.models.user import UserORM

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/content-review")


class TopicWithDocsItem(BaseModel):
    topic_id: int
    topic_name: str
    user_id: int
    user_email: str
    doc_count: int
    draft_count: int
    pending_review_count: int
    approved_count: int
    published_count: int
    rejected_count: int


@router.get("/topics", response_model=list[TopicWithDocsItem])
def list_topics_with_docs(
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """列出有内容文档的 topic(给前端下拉用)."""
    # 聚合 doc 数量
    docs = db.query(TopicGeneratedDocORM).all()
    if not docs:
        return []
    by_topic: dict[int, dict[str, int]] = {}
    for d in docs:
        b = by_topic.setdefault(d.topic_id, {
            "doc_count": 0, "draft": 0, "pending_review": 0,
            "approved": 0, "published": 0, "rejected": 0,
        })
        b["doc_count"] += 1
        b[d.status] = b.get(d.status, 0) + 1
    topic_ids = list(by_topic.keys())
    topics = {t.id: t for t in db.query(AiTelemetryTopicORM)
              .filter(AiTelemetryTopicORM.id.in_(topic_ids)).all()}
    user_ids = {t.user_id for t in topics.values()}
    emails: dict[int, str] = {}
    if user_ids:
        for u in db.query(UserORM).filter(UserORM.id.in_(user_ids)).all():
            emails[u.id] = u.email
    out: list[TopicWithDocsItem] = []
    for tid, b in by_topic.items():
        t = topics.get(tid)
        if not t:
            continue
        out.append(TopicWithDocsItem(
            topic_id=tid, topic_name=t.name,
            user_id=t.user_id, user_email=emails.get(t.user_id, ""),
            doc_count=b["doc_count"],
            draft_count=b.get("draft", 0),
            pending_review_count=b.get("pending_review", 0),
            approved_count=b.get("approved", 0),
            published_count=b.get("published", 0),
            rejected_count=b.get("rejected", 0),
        ))
    out.sort(key=lambda x: (-x.pending_review_count, -x.draft_count, x.topic_name))
    return out


@router.get("/topics/{topic_id}/docs", response_model=list[GeneratedDocOut])
def list_topic_docs(
    topic_id: int,
    status: Optional[str] = None,
    source: Optional[str] = None,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """列出某 topic 下的文档.

    status 过滤:
      - 不传:全部
      - "draft" / "pending_review" / "approved" / "rejected" / "published":精确匹配
      - "to_review":draft + pending_review(常用过滤,默认 admin 视角想看的)
    source 过滤:
      - 不传 / "all":全部
      - "ai" / "user":只看对应来源
    """
    q = db.query(TopicGeneratedDocORM).filter(TopicGeneratedDocORM.topic_id == topic_id)
    if status == "to_review":
        q = q.filter(TopicGeneratedDocORM.status.in_(["draft", "pending_review"]))
    elif status:
        q = q.filter(TopicGeneratedDocORM.status == status)
    if source in ("ai", "user"):
        q = q.filter(TopicGeneratedDocORM.source == source)
    rows = q.order_by(TopicGeneratedDocORM.id.desc()).all()
    return [GeneratedDocOut.from_orm_row(r) for r in rows]


@router.get("/docs/{doc_id}", response_model=GeneratedDocOut)
def get_doc(
    doc_id: int,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    d = db.get(TopicGeneratedDocORM, doc_id)
    if not d:
        raise HTTPException(404, "doc not found")
    return GeneratedDocOut.from_orm_row(d)


class AdminDocUpdatePayload(BaseModel):
    title: Optional[str] = None
    body_markdown: Optional[str] = None
    summary: Optional[str] = None


@router.patch("/docs/{doc_id}", response_model=GeneratedDocOut)
def admin_update_doc(
    doc_id: int,
    payload: AdminDocUpdatePayload,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 改 AI / user 稿正文.不限 source / status,纯人工修正用."""
    d = db.get(TopicGeneratedDocORM, doc_id)
    if not d:
        raise HTTPException(404, "doc not found")
    if payload.title is not None:
        d.title = payload.title.strip()[:200]
    if payload.body_markdown is not None:
        d.body_markdown = payload.body_markdown
    if payload.summary is not None:
        d.summary = payload.summary[:500]
    db.commit()
    db.refresh(d)
    return GeneratedDocOut.from_orm_row(d)


@router.post("/docs/select", status_code=204)
def select_docs_for_review(
    payload: SelectDocsPayload,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """把勾选的 draft docs 切到 pending_review."""
    rows = (
        db.query(TopicGeneratedDocORM)
          .filter(TopicGeneratedDocORM.id.in_(payload.doc_ids))
          .all()
    )
    n = 0
    for d in rows:
        if d.status == "draft":
            d.status = "pending_review"
            d.selected_for_review = True
            n += 1
    db.commit()
    log.info("content review: selected %d docs to pending_review", n)


@router.post("/docs/{doc_id}/approve", response_model=GeneratedDocOut)
def approve_doc(
    doc_id: int,
    background: BackgroundTasks,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    d = db.get(TopicGeneratedDocORM, doc_id)
    if not d:
        raise HTTPException(404, "doc not found")
    if d.status not in ("draft", "pending_review"):
        raise HTTPException(409, {"code": "WRONG_STATUS",
                                  "message": f"doc status={d.status},不可通过"})
    d.status = "approved"
    d.selected_for_review = True
    d.review_decision_at = datetime.utcnow()
    d.reviewer_id = admin.id
    d.reject_reason = None
    db.commit()
    db.refresh(d)
    _notify_user(db, background, d, decision="approved")
    return GeneratedDocOut.from_orm_row(d)


@router.post("/docs/{doc_id}/regenerate", response_model=GeneratedDocOut)
def regenerate_doc(
    doc_id: int,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """重新生成单篇 doc — 同步跑一次 LLM(~30-60s),覆写正文后返回新 doc.

    用 doc 自带的监测问题 / 创作方向 / 文案类型 / 模板复现原生成路径.
    已通过 / 已发布的稿不允许重生(避免擦掉已采用内容).
    """
    d = db.get(TopicGeneratedDocORM, doc_id)
    if not d:
        raise HTTPException(404, "doc not found")
    if d.status in ("approved", "published"):
        raise HTTPException(409, {"code": "WRONG_STATUS",
                                  "message": f"doc status={d.status},不可重新生成"})
    from geo.services.content_generator import regenerate_doc as _regen
    try:
        _regen(db, d)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("regenerate doc %d failed: %s", doc_id, e)
        raise HTTPException(502, {"code": "REGEN_FAILED", "message": str(e)[:300]})
    return GeneratedDocOut.from_orm_row(d)


@router.post("/docs/{doc_id}/reject", response_model=GeneratedDocOut)
def reject_doc(
    doc_id: int,
    payload: RejectDocPayload,
    background: BackgroundTasks,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    d = db.get(TopicGeneratedDocORM, doc_id)
    if not d:
        raise HTTPException(404, "doc not found")
    if d.status not in ("draft", "pending_review"):
        raise HTTPException(409, {"code": "WRONG_STATUS",
                                  "message": f"doc status={d.status},不可拒绝"})
    d.status = "rejected"
    d.selected_for_review = True
    d.review_decision_at = datetime.utcnow()
    d.reviewer_id = admin.id
    d.reject_reason = payload.reason or None
    db.commit()
    db.refresh(d)
    _notify_user(db, background, d, decision="rejected", reject_reason=payload.reason or None)
    return GeneratedDocOut.from_orm_row(d)


@router.post("/docs/{doc_id}/publish", response_model=GeneratedDocOut)
async def publish_doc(
    doc_id: int,
    payload: PublishPayload,
    background: BackgroundTasks,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """标记发布目标 + (可选)推到 Mediumsly。

    publish_targets_json 永远写(老语义不变,只是"标注已发到哪里");
    push_to_mediumsly=true 时,额外调 Mediumsly 内部 API,把返回的 post id/url
    写到 doc 的 mediumsly_* 列。Mediumsly 推送失败不会回滚 GEO 这边的 publish,
    错误存到 mediumsly_last_error 让 admin 重试。
    """
    d = db.get(TopicGeneratedDocORM, doc_id)
    if not d:
        raise HTTPException(404, "doc not found")
    if d.status != "approved":
        raise HTTPException(409, {"code": "NEED_APPROVED",
                                  "message": "请先通过审核再选发布平台"})
    try:
        targets = json.loads(d.publish_targets_json or "[]")
    except Exception:  # noqa: BLE001
        targets = []
    if not isinstance(targets, list):
        targets = []
    now_iso = datetime.utcnow().isoformat()
    new_targets = [
        {
            "platform": t.platform,
            "media": t.media,
            "url": (t.url or "").strip(),
            "marked_at": now_iso,
            "marked_by": admin.id,
        }
        for t in payload.publish_targets
    ]
    targets.extend(new_targets)
    d.publish_targets_json = json.dumps(targets, ensure_ascii=False)
    d.status = "published"

    # ── Mediumsly 同步推送(可选)──────────────────────────────
    if payload.push_to_mediumsly:
        # 延迟 import:不勾选时不必加载 httpx / publisher 模块。
        from geo.services import mediumsly_publisher

        topic = db.get(AiTelemetryTopicORM, d.topic_id)
        user = db.get(UserORM, topic.user_id) if topic else None
        if not user or not user.email:
            d.mediumsly_last_error = "Topic owner or email missing — cannot push"
        else:
            try:
                result = await mediumsly_publisher.push(d, user, topic)
                d.mediumsly_post_id   = result.post_id
                d.mediumsly_url       = result.url
                d.mediumsly_pushed_at = datetime.utcnow()
                d.mediumsly_last_error = None
            except mediumsly_publisher.MediumslyPostGone:
                # Mediumsly 那边被手动删了 — 清空 id,下次重试自动走 POST 重建
                d.mediumsly_post_id = None
                d.mediumsly_last_error = "Mediumsly post was deleted upstream — id cleared, retry to re-create"
            except mediumsly_publisher.MediumslyError as e:
                # 记录错误,不打断 GEO 自己的 publish 流程
                d.mediumsly_last_error = f"{e.code or 'ERROR'}: {e}"
                log.warning("[mediumsly_publisher] doc=%s push failed: %s", d.id, d.mediumsly_last_error)

    db.commit()
    db.refresh(d)
    _notify_user(db, background, d, decision="published", publish_targets=new_targets)
    return GeneratedDocOut.from_orm_row(d)


class PlatformReviewPayload(BaseModel):
    status: str                       # passed / rejected
    reason: Optional[str] = None      # rejected 时的平台拒稿原因(规则学习素材)


@router.post("/docs/{doc_id}/platform-review", response_model=GeneratedDocOut)
def set_platform_review(
    doc_id: int,
    payload: PlatformReviewPayload,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """2026-06-12 — 回填平台方审核结果(发布后平台过审/被拒).

    rejected 的 reason 会被 /admin/platform-rules/learn 聚合,LLM 提炼成
    该平台审核规则增量。只允许对已 published 的稿子回填。
    """
    d = db.get(TopicGeneratedDocORM, doc_id)
    if not d:
        raise HTTPException(404, "doc not found")
    if d.status != "published":
        raise HTTPException(409, {"code": "NEED_PUBLISHED",
                                  "message": "先标记发布,再回填平台审核结果"})
    if payload.status not in ("passed", "rejected"):
        raise HTTPException(422, "status must be passed / rejected")
    if payload.status == "rejected" and not (payload.reason or "").strip():
        raise HTTPException(422, {"code": "NEED_REASON",
                                  "message": "平台被拒必须填写拒稿原因(规则学习的素材)"})
    d.platform_review_status = payload.status
    d.platform_reject_reason = (payload.reason or "").strip() or None
    db.commit()
    db.refresh(d)
    return GeneratedDocOut.from_orm_row(d)


def _notify_user(db: Session, background: BackgroundTasks, doc: TopicGeneratedDocORM,
                  *, decision: str, reject_reason: str | None = None,
                  publish_targets: list[dict] | None = None) -> None:
    topic = db.get(AiTelemetryTopicORM, doc.topic_id)
    if not topic:
        return
    user = db.get(UserORM, topic.user_id)
    if not user or not user.email:
        return
    background.add_task(_send_safe,
                        to=user.email, doc_title=doc.title or doc.source_query_text or f"#{doc.id}",
                        decision=decision, reject_reason=reject_reason,
                        publish_targets=publish_targets)


def _send_safe(*, to: str, doc_title: str, decision: str,
                reject_reason: str | None, publish_targets: list[dict] | None) -> None:
    try:
        from geo.services.email_service import email_service
        email_service.send_content_review_result_email(
            to=to, doc_title=doc_title, decision=decision,
            reject_reason=reject_reason, publish_targets=publish_targets,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("content review email failed: %s", e)


# ─────────────────────── URL 级 ROI 重算 ──────────────────────────

class RebuildCitedByPayload(BaseModel):
    topic_id: Optional[int] = None  # 不传 = 全 topic
    replace: bool = False            # 默认合并;True = 重算覆盖


@router.post("/rebuild-cited-by")
def rebuild_cited_by(
    payload: RebuildCitedByPayload,
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),  # noqa: ARG001  # 用 backfill 自带 session
):
    """把 ai_telemetry_responses.citations_json 跟 doc.publish_targets_json 取交集,
    回填 doc.cited_by_json。topic_id 不传则全量。

    幂等;admin / cron 都可调。
    """
    from geo.services.backfill_cited_by import run as run_backfill
    stats = run_backfill(topic_id=payload.topic_id, dry_run=False, replace=payload.replace)
    return stats
