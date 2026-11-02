"""2026-06-12 — 平台审核规则库 API(admin).

每个发布平台一份"审核红线"文本,生成文章时按发文行 platform 注入 prompt。
两步闭环:
  1. 静态规则库:admin 手动编辑 / AI 按公开平台规范生成初稿(seed)
  2. 从拒稿学习:聚合该平台 platform_reject_reason,LLM 提炼规则增量写入
     pending_rules_text,admin 采纳(approve-pending)后并入 rules_text 生效

端点(prefix /admin/platform-rules,require_admin):
- GET    /                      — 全部平台规则(默认平台没行也返回空壳)
- PUT    /{platform}            — upsert rules_text(可同时清 pending)
- POST   /{platform}/seed       — LLM 生成该平台规则初稿(只返回草稿文本,不落库)
- POST   /learn                 — 全平台:聚合拒稿原因 → LLM 提炼增量 → pending
- POST   /{platform}/approve-pending — pending 并入 rules_text 并清空
"""
import logging
import os
from datetime import datetime
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from geo.api.auth import require_admin
from geo.api.ai_telemetry import get_db
from geo.models.ai_telemetry import PlatformRuleORM, TopicGeneratedDocORM

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/platform-rules")

# 与 admin_review.DEFAULT_PUBLISH_PLATFORMS 一致;没建行的默认平台也在列表里返回空壳
DEFAULT_PLATFORMS = ["公众号", "小红书", "抖音", "视频号", "搜狐号", "知乎"]

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_TIMEOUT = 120


class PlatformRuleOut(BaseModel):
    platform: str
    rules_text: str = ""
    pending_rules_text: str = ""
    learned_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # 该平台已回填的拒稿数(学习素材量,前端展示用)
    rejected_count: int = 0


class RuleUpdatePayload(BaseModel):
    rules_text: str = Field("", max_length=20000)
    # true 时同时清空 pending(admin 改完规则后不想要旧增量)
    clear_pending: bool = False


def _llm_text(prompt: str) -> str:
    """单轮纯文本 LLM 调用(deepseek 优先,fallback openrouter)."""
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if ds_key:
        url = f"{DEEPSEEK_BASE_URL}/chat/completions"
        model = "deepseek-chat"
        headers = {"Authorization": f"Bearer {ds_key}", "Content-Type": "application/json"}
    elif or_key:
        url = OPENROUTER_URL
        model = "deepseek/deepseek-chat"
        headers = {"Authorization": f"Bearer {or_key}", "Content-Type": "application/json",
                   "HTTP-Referer": "https://www.vigilath.com",
                   "X-Title": "GEO Platform Rules"}
    else:
        raise HTTPException(503, "DEEPSEEK_API_KEY / OPENROUTER_API_KEY 都未配置")
    r = requests.post(url, headers=headers, timeout=LLM_TIMEOUT, json={
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    })
    if r.status_code >= 400:
        raise HTTPException(502, f"LLM HTTP {r.status_code}: {r.text[:200]}")
    try:
        return str(r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"unexpected LLM response: {e}")


def _rejected_counts(db: Session) -> dict[str, int]:
    from sqlalchemy import func
    rows = (
        db.query(TopicGeneratedDocORM.platform, func.count(TopicGeneratedDocORM.id))
          .filter(TopicGeneratedDocORM.platform_review_status == "rejected")
          .group_by(TopicGeneratedDocORM.platform)
          .all()
    )
    return {str(p or ""): int(n) for p, n in rows}


def _to_out(row: PlatformRuleORM | None, platform: str, rejected: int) -> PlatformRuleOut:
    if row is None:
        return PlatformRuleOut(platform=platform, rejected_count=rejected)
    return PlatformRuleOut(
        platform=row.platform,
        rules_text=row.rules_text or "",
        pending_rules_text=row.pending_rules_text or "",
        learned_at=row.learned_at,
        updated_at=row.updated_at,
        rejected_count=rejected,
    )


@router.get("", response_model=list[PlatformRuleOut])
def list_platform_rules(
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = {r.platform: r for r in db.query(PlatformRuleORM).all()}
    rejected = _rejected_counts(db)
    # 默认平台 + 已建行的并集,默认平台顺序在前
    platforms = list(DEFAULT_PLATFORMS) + [p for p in rows if p not in DEFAULT_PLATFORMS]
    return [_to_out(rows.get(p), p, rejected.get(p, 0)) for p in platforms]


def _get_or_create(db: Session, platform: str) -> PlatformRuleORM:
    platform = platform.strip()
    if not platform or len(platform) > 32:
        raise HTTPException(422, "invalid platform")
    row = db.query(PlatformRuleORM).filter(PlatformRuleORM.platform == platform).first()
    if row is None:
        row = PlatformRuleORM(platform=platform)
        db.add(row)
    return row


@router.put("/{platform}", response_model=PlatformRuleOut)
def update_platform_rule(
    platform: str,
    payload: RuleUpdatePayload,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = _get_or_create(db, platform)
    row.rules_text = (payload.rules_text or "").strip()
    if payload.clear_pending:
        row.pending_rules_text = ""
    row.updated_at = datetime.utcnow()
    row.updated_by_id = admin.id
    db.commit()
    db.refresh(row)
    return _to_out(row, row.platform, _rejected_counts(db).get(row.platform, 0))


@router.post("/{platform}/seed", response_model=dict)
def seed_platform_rule(
    platform: str,
    _admin = Depends(require_admin),
):
    """LLM 按公开平台规范生成规则初稿 — 只返回草稿,前端填进编辑框由 admin 校对后保存."""
    platform = platform.strip()
    if not platform:
        raise HTTPException(422, "invalid platform")
    draft = _llm_text(
        f"你是内容平台合规专家。请整理「{platform}」平台对图文内容的审核红线清单,"
        f"供 AI 写稿时遵守(违反任何一条稿件会被平台拒审)。\n"
        f"涵盖维度:广告法用语(绝对化用语/功效承诺)、外链与联系方式政策、"
        f"诱导关注与导流限制、标题规范、敏感领域(医疗/金融/教育)表述、"
        f"图片与素材要求、字数与排版习惯。\n"
        f"输出要求:每条一行,以「- 」开头,只写可执行的禁止/必须项,"
        f"不超过 20 条,不要解释,不要标题。"
    )
    return {"platform": platform, "draft": draft}


@router.post("/learn", response_model=list[PlatformRuleOut])
def learn_from_rejections(
    _admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """全平台:聚合已回填的平台拒稿原因 → LLM 提炼规则增量 → 写 pending 待采纳.

    只处理有拒稿原因的平台;增量与现有 rules_text 一起给 LLM,要求只输出
    现有规则没覆盖的新条目,避免重复堆积。
    """
    docs = (
        db.query(TopicGeneratedDocORM)
          .filter(TopicGeneratedDocORM.platform_review_status == "rejected")
          .filter(TopicGeneratedDocORM.platform_reject_reason.isnot(None))
          .all()
    )
    by_platform: dict[str, list[str]] = {}
    for d in docs:
        p = (d.platform or "").strip()
        reason = (d.platform_reject_reason or "").strip()
        if p and reason:
            by_platform.setdefault(p, []).append(reason)

    out: list[PlatformRuleOut] = []
    rejected = {p: len(v) for p, v in by_platform.items()}
    for platform, reasons in by_platform.items():
        row = _get_or_create(db, platform)
        uniq = list(dict.fromkeys(reasons))[-50:]   # 去重,最多取最近 50 条
        bullets = "\n".join(f"- {s[:300]}" for s in uniq)
        existing = (row.rules_text or "").strip() or "(暂无)"
        increment = _llm_text(
            f"你是内容平台合规专家。下面是「{platform}」平台真实的拒稿原因记录,"
            f"请提炼成可执行的审核规则条目,供 AI 写稿时遵守。\n\n"
            f"【现有规则(已生效,不要重复输出)】\n{existing}\n\n"
            f"【拒稿原因记录】\n{bullets}\n\n"
            f"输出要求:只输出现有规则没覆盖的新规则,每条一行以「- 」开头,"
            f"合并同类原因,不超过 10 条;没有新规则就输出「(无新增)」。"
        )
        if increment and "(无新增)" not in increment:
            row.pending_rules_text = increment.strip()
        row.learned_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
        out.append(_to_out(row, platform, rejected.get(platform, 0)))
    if not out:
        raise HTTPException(404, "没有任何平台有已回填的拒稿原因,无可学习素材")
    return out


@router.post("/{platform}/approve-pending", response_model=PlatformRuleOut)
def approve_pending(
    platform: str,
    admin = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(PlatformRuleORM).filter(PlatformRuleORM.platform == platform.strip()).first()
    if not row or not (row.pending_rules_text or "").strip():
        raise HTTPException(404, "该平台没有待采纳的规则增量")
    base = (row.rules_text or "").strip()
    row.rules_text = (base + "\n" + row.pending_rules_text.strip()).strip()
    row.pending_rules_text = ""
    row.updated_at = datetime.utcnow()
    row.updated_by_id = admin.id
    db.commit()
    db.refresh(row)
    return _to_out(row, row.platform, _rejected_counts(db).get(row.platform, 0))
