"""内容模板 CRUD — 执行计划编辑器用.

scope:
- system:全局预置,只允许超管(暂以 admin 视为超管)编辑
- tenant:运营自己的模板;只本人 (created_by_id) 或同 tenant_id 能改
- topic: 挂在某 topic 的临时模板

锁定(locked=True)后,prompt_template / kind 字段进入只读;
其余元信息(name / target_platforms / length_*)仍可改.
被锁的模板仍可用于发文计划,LLM 调用每次按"当前 prompt"渲染.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from geo.api.auth import require_admin
from geo.api.ai_telemetry import get_db
from geo.models.ai_telemetry import (
    ContentTemplateCreate, ContentTemplateORM, ContentTemplateOut,
    ContentTemplateUpdate,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/content-templates")


def _to_out(t: ContentTemplateORM) -> ContentTemplateOut:
    try:
        platforms = json.loads(t.target_platforms_json or "[]")
    except Exception:  # noqa: BLE001
        platforms = []
    if not isinstance(platforms, list):
        platforms = []
    return ContentTemplateOut(
        id=t.id, scope=t.scope, tenant_id=t.tenant_id, topic_id=t.topic_id,
        name=t.name, kind=t.kind, prompt_template=t.prompt_template,
        target_platforms=[str(p) for p in platforms if p],
        length_min=t.length_min, length_max=t.length_max,
        locked=t.locked, locked_at=t.locked_at, locked_by_id=t.locked_by_id,
        created_by_id=t.created_by_id,
        created_at=t.created_at, updated_at=t.updated_at,
    )


@router.get("", response_model=list[ContentTemplateOut])
def list_templates(
    scope: Optional[str] = Query(None, description="system / tenant / topic;空则全部"),
    topic_id: Optional[int] = Query(None, description="scope=topic 时按 topic 过滤"),
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(ContentTemplateORM)
    if scope:
        if scope not in ("system", "tenant", "topic"):
            raise HTTPException(422, {"code": "INVALID_SCOPE", "message": "scope 必须是 system/tenant/topic"})
        q = q.filter(ContentTemplateORM.scope == scope)
    if topic_id is not None:
        q = q.filter(ContentTemplateORM.topic_id == topic_id)
    rows = q.order_by(ContentTemplateORM.scope.asc(), ContentTemplateORM.id.asc()).all()
    return [_to_out(t) for t in rows]


@router.post("", response_model=ContentTemplateOut)
def create_template(
    payload: ContentTemplateCreate,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.scope == "topic" and not payload.topic_id:
        raise HTTPException(422, {
            "code": "MISSING_TOPIC", "field": "topic_id",
            "message": "scope=topic 时必须带 topic_id",
        })
    if payload.length_min < 100 or payload.length_max > 5000 or payload.length_min > payload.length_max:
        raise HTTPException(422, {
            "code": "INVALID_LENGTH", "field": "length_min/max",
            "message": "长度范围非法(100 ≤ min ≤ max ≤ 5000)",
        })
    t = ContentTemplateORM(
        scope=payload.scope,
        tenant_id=getattr(admin, "id", None) if payload.scope == "tenant" else None,
        topic_id=payload.topic_id if payload.scope == "topic" else None,
        name=payload.name.strip()[:64],
        kind=payload.kind.strip()[:16],
        prompt_template=payload.prompt_template,
        target_platforms_json=json.dumps(payload.target_platforms or [], ensure_ascii=False),
        length_min=payload.length_min,
        length_max=payload.length_max,
        locked=False,
        created_by_id=admin.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _to_out(t)


@router.patch("/{template_id}", response_model=ContentTemplateOut)
def update_template(
    template_id: int,
    payload: ContentTemplateUpdate,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    t = db.get(ContentTemplateORM, template_id)
    if not t:
        raise HTTPException(404, "template not found")
    locked_fields = ("prompt_template", "kind")
    if t.locked:
        for f in locked_fields:
            if getattr(payload, f, None) is not None:
                raise HTTPException(409, {
                    "code": "TEMPLATE_LOCKED", "field": f,
                    "message": "模板已锁定,prompt_template / kind 不可改",
                })
    if payload.name is not None:
        t.name = payload.name.strip()[:64]
    if payload.kind is not None:
        t.kind = payload.kind.strip()[:16]
    if payload.prompt_template is not None:
        t.prompt_template = payload.prompt_template
    if payload.target_platforms is not None:
        t.target_platforms_json = json.dumps(payload.target_platforms, ensure_ascii=False)
    if payload.length_min is not None:
        t.length_min = payload.length_min
    if payload.length_max is not None:
        t.length_max = payload.length_max
    if t.length_min > t.length_max:
        raise HTTPException(422, {
            "code": "INVALID_LENGTH", "message": "length_min 不能大于 length_max",
        })
    t.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(t)
    return _to_out(t)


@router.post("/{template_id}/lock", response_model=ContentTemplateOut)
def lock_template(
    template_id: int,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    t = db.get(ContentTemplateORM, template_id)
    if not t:
        raise HTTPException(404, "template not found")
    if not t.locked:
        t.locked = True
        t.locked_at = datetime.utcnow()
        t.locked_by_id = admin.id
        t.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(t)
    return _to_out(t)
