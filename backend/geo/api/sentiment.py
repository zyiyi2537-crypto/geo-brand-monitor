"""舆情监测 API 路由.

负责:
1. 账号 CRUD(/api/sentiment/accounts/...)
2. 任务状态查询和手动触发(/run-status, /run-now)
3. 数据查询代理(从 sentinel-service 拿数据,加 auth + 整理)
4. 知识库 CRUD
5. 草稿生成

定时任务自动触发的部分见 services/sentiment_scheduler.py — 同样调
sentiment_pipeline.run_pipeline_for_account(),与本文件 /run-now 共用编排.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from geo.api.auth import get_current_user
from geo.database import SessionLocal
from geo.models.sentiment import (
    KeywordGroup, SentimentAccountCreate, SentimentAccountORM, SentimentAccountOut,
    SentimentAccountUpdate, SentimentKnowledgeORM, SentimentRunLogORM,
    SentimentPlatformORM, SentimentPlatformOut,
    RunStatusOut, KnowledgeOut, _as_utc, flatten_keyword_groups,
)
from geo.models.user import User
from geo.services import sentinel_client
from geo.services.sentinel_client import SentinelError
from geo.services.sentiment_pipeline import run_pipeline_for_account

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment")


# ─────────────────────────── DI helpers ────────────────────────


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_account_or_404(db: Session, account_id: int, user_id: int) -> SentimentAccountORM:
    acc = db.get(SentimentAccountORM, account_id)
    if not acc or acc.user_id != user_id:
        raise HTTPException(404, "account not found")
    return acc


def _ensure_membership_has_sentiment(user: User) -> None:
    """档位准入校验 — 没有舆情权限的会员报 402.

    MVP 不做严格校验,直接放行;接入会员体系后这里 JOIN memberships.
    """
    # TODO: 接入 membership_service.has_sentiment_enabled(user.id)
    # if not allowed: raise HTTPException(402, ...)
    pass


def _enforce_account_quota(db: Session, user_id: int) -> None:
    """档位上限校验 — starter=1, growth=3, scale=∞."""
    # TODO: 从 membership 拿配额
    cap = 999
    existing = db.query(SentimentAccountORM).filter_by(
        user_id=user_id, active=True,
    ).count()
    if existing >= cap:
        raise HTTPException(402, f"account quota exceeded ({cap})")


def _has_meaningful_change(acc: SentimentAccountORM, payload: SentimentAccountUpdate) -> bool:
    """关键词/intent/aliases 变了就值得重跑."""
    fields = ("target", "ticker", "intent")
    for f in fields:
        v = getattr(payload, f, None)
        if v is not None and getattr(acc, f) != v:
            return True
    list_fields = (
        ("keywords", "keywords_json"), ("excludes", "excludes_json"),
        ("aliases", "aliases_json"), ("media_allowlist", "media_allowlist_json"),
        ("weixin_album_urls", "weixin_album_urls_json"),
        ("newsnow_sources", "newsnow_sources_json"),
    )
    for in_name, db_name in list_fields:
        v = getattr(payload, in_name, None)
        if v is None:
            continue
        existing = json.loads(getattr(acc, db_name) or "[]")
        if set(v) != set(existing):
            return True
    if payload.keyword_groups is not None:
        new_terms = set(flatten_keyword_groups(payload.keyword_groups))
        existing_groups = json.loads(acc.keyword_groups_json or "[]")
        existing_terms = set(flatten_keyword_groups(
            [KeywordGroup.model_validate(g) for g in existing_groups]
        ))
        if new_terms != existing_terms:
            return True
    return False


def _resolve_keywords_for_storage(
    keywords: Optional[list[str]],
    keyword_groups: Optional[list[KeywordGroup]],
    fallback_keywords: list[str],
) -> list[str]:
    """决定 keywords_json 存什么 — keyword_groups 优先,扁平 keywords 兜底."""
    if keyword_groups is not None:
        return flatten_keyword_groups(keyword_groups)
    if keywords is not None:
        return keywords
    return fallback_keywords


# ─────────────────────────── 平台目录 ──────────────────────────


@router.get("/platforms", response_model=list[SentimentPlatformOut])
def list_platforms(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """媒体平台目录(全局只读).
    用户登录后即可拉,不限会员档位 — 这是用来渲染白名单选择器和文章页过滤器的元数据,
    不暴露用户私有信息。返回顺序:category 默认顺序 → 组内 sort_order。
    """
    category_rank = {
        "finance": 1, "social": 2, "forum": 3,
        "video": 4, "news": 5, "overseas": 6,
    }
    rows = (
        db.query(SentimentPlatformORM)
          .filter_by(enabled=True)
          .all()
    )
    rows.sort(key=lambda r: (category_rank.get(r.category, 99), r.sort_order, r.code))
    return [SentimentPlatformOut.from_orm_row(r) for r in rows]


# ─────────────────────────── 账号 CRUD ────────────────────────


@router.get("/accounts", response_model=list[SentimentAccountOut])
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SentimentAccountORM)
          .filter_by(user_id=current_user.id)
          .order_by(SentimentAccountORM.created_at.desc())
          .all()
    )
    return [SentimentAccountOut.from_orm_row(r) for r in rows]


@router.post("/accounts", response_model=SentimentAccountOut, status_code=201)
def create_account(
    payload: SentimentAccountCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建账号,可选立即触发首跑.

    流程:
    1. 校验会员档位
    2. 校验账号配额
    3. INSERT,状态机 = pending(若 run_now)
    4. BackgroundTasks 入队 first_run
    5. 返回账号实体(前端立刻跳工作台 + 进入轮询/手动刷新流程)
    """
    _ensure_membership_has_sentiment(current_user)
    _enforce_account_quota(db, current_user.id)

    # 唯一性:同一用户下同 ticker 只能一个 active
    dup = db.query(SentimentAccountORM).filter_by(
        user_id=current_user.id, ticker=payload.ticker,
    ).first()
    if dup:
        raise HTTPException(409, f"ticker {payload.ticker} already monitored")

    flat_keywords = _resolve_keywords_for_storage(
        payload.keywords, payload.keyword_groups, payload.keywords,
    )
    acc = SentimentAccountORM(
        user_id=current_user.id,
        target=payload.target,
        ticker=payload.ticker,
        aliases_json=json.dumps(payload.aliases, ensure_ascii=False),
        intent=payload.intent,
        keywords_json=json.dumps(flat_keywords, ensure_ascii=False),
        keyword_groups_json=json.dumps(
            [g.model_dump(exclude_none=True) for g in (payload.keyword_groups or [])],
            ensure_ascii=False,
        ),
        excludes_json=json.dumps(payload.excludes, ensure_ascii=False),
        media_allowlist_json=json.dumps(payload.media_allowlist, ensure_ascii=False),
        notify_emails_json=json.dumps([str(e) for e in payload.notify_emails], ensure_ascii=False),
        weixin_album_urls_json=json.dumps(payload.weixin_album_urls, ensure_ascii=False),
        newsnow_sources_json=json.dumps(payload.newsnow_sources, ensure_ascii=False),
        active=True,
        last_run_status="pending" if payload.run_now else None,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)

    if payload.run_now:
        log.info("[sentiment] queue first_run for account %s", acc.id)
        background_tasks.add_task(run_pipeline_for_account, acc.id, "first_run")

    return SentimentAccountOut.from_orm_row(acc)


@router.get("/accounts/{account_id}", response_model=SentimentAccountOut)
def get_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    acc = _get_account_or_404(db, account_id, current_user.id)
    return SentimentAccountOut.from_orm_row(acc)


@router.put("/accounts/{account_id}", response_model=SentimentAccountOut)
def update_account(
    account_id: int,
    payload: SentimentAccountUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """改账号配置,如果关键词/intent/aliases 变化则自动入队重跑."""
    acc = _get_account_or_404(db, account_id, current_user.id)
    rerun = _has_meaningful_change(acc, payload)

    if payload.target is not None: acc.target = payload.target
    if payload.ticker is not None: acc.ticker = payload.ticker
    if payload.aliases is not None: acc.aliases_json = json.dumps(payload.aliases, ensure_ascii=False)
    if payload.intent is not None: acc.intent = payload.intent
    if payload.excludes is not None: acc.excludes_json = json.dumps(payload.excludes, ensure_ascii=False)
    if payload.media_allowlist is not None:
        acc.media_allowlist_json = json.dumps(payload.media_allowlist, ensure_ascii=False)
    if payload.notify_emails is not None:
        acc.notify_emails_json = json.dumps([str(e) for e in payload.notify_emails], ensure_ascii=False)
    if payload.weixin_album_urls is not None:
        acc.weixin_album_urls_json = json.dumps(payload.weixin_album_urls, ensure_ascii=False)
    if payload.newsnow_sources is not None:
        acc.newsnow_sources_json = json.dumps(payload.newsnow_sources, ensure_ascii=False)
    if payload.active is not None: acc.active = payload.active

    # keyword_groups 变化时,优先以 group 为准重算 keywords_json;
    # 否则若客户端只传 keywords 就保留旧逻辑.
    if payload.keyword_groups is not None:
        acc.keyword_groups_json = json.dumps(
            [g.model_dump(exclude_none=True) for g in payload.keyword_groups],
            ensure_ascii=False,
        )
        acc.keywords_json = json.dumps(
            flatten_keyword_groups(payload.keyword_groups), ensure_ascii=False,
        )
    elif payload.keywords is not None:
        acc.keywords_json = json.dumps(payload.keywords, ensure_ascii=False)

    if rerun and acc.active:
        acc.last_run_status = "pending"
        background_tasks.add_task(run_pipeline_for_account, acc.id, "manual")

    db.commit()
    db.refresh(acc)
    return SentimentAccountOut.from_orm_row(acc)


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    acc = _get_account_or_404(db, account_id, current_user.id)
    db.delete(acc)
    db.commit()
    return None


# ─────────────────────────── 任务状态 / 手动触发 ────────────────


@router.get("/accounts/{account_id}/run-status", response_model=RunStatusOut)
def get_run_status(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """前端"手动刷新"时调这个看任务进展."""
    acc = _get_account_or_404(db, account_id, current_user.id)
    return RunStatusOut(
        status=acc.last_run_status,
        last_run_at=_as_utc(acc.last_run_at),
        error=acc.last_run_error,
    )


@router.post("/accounts/{account_id}/run-now")
def run_now(
    account_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户点"重试"或"立即跑一次"按钮时调."""
    acc = _get_account_or_404(db, account_id, current_user.id)
    if acc.last_run_status == "running":
        raise HTTPException(409, "task already running, please wait")

    acc.last_run_status = "pending"
    db.commit()
    background_tasks.add_task(run_pipeline_for_account, account_id, "manual")
    return {"queued": True}


@router.get("/accounts/{account_id}/run-logs")
def list_run_logs(
    account_id: int,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """任务执行历史(用于排障)."""
    _get_account_or_404(db, account_id, current_user.id)
    rows = (
        db.query(SentimentRunLogORM)
          .filter_by(account_id=account_id)
          .order_by(SentimentRunLogORM.id.desc())
          .limit(limit)
          .all()
    )
    return [
        {
            "id": r.id, "trigger": r.trigger, "started_at": r.started_at,
            "ended_at": r.ended_at, "status": r.status,
            "error": r.error, "duration_s": r.duration_s,
            "stats": json.loads(r.stats_json) if r.stats_json else None,
        } for r in rows
    ]


# ─────────────────────────── 数据查询(代理 sentinel-service)─


def _proxy(fn, *args, **kwargs):
    """统一处理 sentinel-service 错误.

    区分三类,避免把"上游报错"误显示成"服务连不上":
      - SentinelError          → 502,sentinel 业务失败(status=failed)
      - httpx.HTTPStatusError  → 502,sentinel 返回了 4xx/5xx(端点 bug / 数据问题),
                                  透出上游状态码 + 响应片段便于排障
      - 连接/超时类异常         → 503,sentinel 真正不可达
    """
    try:
        return fn(*args, **kwargs)
    except SentinelError as e:
        raise HTTPException(502, f"sentinel error: {e}") from e
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "")[:300]
        log.error("sentinel-service %s on %s: %s",
                  e.response.status_code, e.request.url, body)
        raise HTTPException(
            502, f"sentinel upstream {e.response.status_code}: {body}"
        ) from e
    except (httpx.TimeoutException, httpx.TransportError) as e:
        log.exception("sentinel-service unreachable: %s", e)
        raise HTTPException(503, "sentinel service unavailable") from e
    except Exception as e:
        log.exception("sentinel-service proxy error: %s", e)
        raise HTTPException(502, f"sentinel proxy error: {e}") from e


@router.get("/accounts/{account_id}/posts")
def proxy_posts(
    account_id: int, ticker: str,
    limit: int = 50, offset: int = 0, days: int = 1,
    start: Optional[str] = None, end: Optional[str] = None,
    sort_by: str = "newest",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """文章列表 + 分页 + 排序。

    时间过滤(基于 ingested_at):start/end (YYYY-MM-DD,闭区间) 优先,
    否则按 days(1=今日,N>1=最近 N 天,0=全部历史)。
    排序:sort_by(详见 sentinel-service /posts 接口)。
    """
    _get_account_or_404(db, account_id, current_user.id)
    return _proxy(
        sentinel_client.list_posts,
        account_id, ticker,
        limit=limit, days=days, offset=offset, start=start, end=end,
        sort_by=sort_by,
    )


@router.get("/accounts/{account_id}/briefs")
def proxy_briefs(
    account_id: int, ticker: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_account_or_404(db, account_id, current_user.id)
    return _proxy(sentinel_client.list_briefs, account_id, ticker)


@router.get("/accounts/{account_id}/briefs/{brief_id}")
def proxy_brief_detail(
    account_id: int, brief_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_account_or_404(db, account_id, current_user.id)
    return _proxy(sentinel_client.get_brief, account_id, brief_id)


@router.get("/accounts/{account_id}/drafts")
def proxy_drafts(
    account_id: int, ticker: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_account_or_404(db, account_id, current_user.id)
    return _proxy(sentinel_client.list_drafts, account_id, ticker)


@router.get("/accounts/{account_id}/today")
def proxy_today(
    account_id: int, ticker: str, days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tab 1 聚合数据 — KPI/趋势/风险分布/最新简报/Top5."""
    _get_account_or_404(db, account_id, current_user.id)
    return _proxy(sentinel_client.get_today, account_id, ticker, days)


# ─────────────────── newsnow 实时热点(不绑 account)──────────────


@router.get("/newsnow/sources")
def proxy_newsnow_sources(
    current_user: User = Depends(get_current_user),
):
    """newsnow 推荐源目录(静态)。仅要求登录,不绑 account。"""
    return _proxy(sentinel_client.list_newsnow_sources)


@router.get("/newsnow/hot")
def proxy_newsnow_hot(
    source: str, limit: int = 30,
    current_user: User = Depends(get_current_user),
):
    """指定 source 当前热榜(实时新闻 / 今日热点用)。"""
    return _proxy(sentinel_client.get_newsnow_hot, source, limit)


# ─────────────────────────── 草稿生成 ────────────────────────


class GenerateDraftRequest(BaseModel):
    account_id: int
    source: Optional[str] = None
    post_id: Optional[str] = None
    topic: Optional[str] = None
    situation: Optional[str] = None


@router.post("/drafts/generate")
def generate_draft(
    payload: GenerateDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """同步调用,等 LLM 返回(5-10 秒)."""
    acc = _get_account_or_404(db, payload.account_id, current_user.id)
    if not (payload.post_id or payload.topic):
        raise HTTPException(400, "post_id 或 topic 至少传一个")

    knowledge = {
        r.key: r.body
        for r in db.query(SentimentKnowledgeORM).filter_by(account_id=acc.id).all()
        if r.body
    }

    return _proxy(
        sentinel_client.run_respond,
        account_id=acc.id, ticker=acc.ticker,
        source=payload.source, post_id=payload.post_id,
        topic=payload.topic, situation=payload.situation,
        knowledge=knowledge or None,
    )


# ─────────────────────────── 知识库 ────────────────────────


VALID_KNOWLEDGE_KEYS = {"brand_voice", "legal_redlines", "response_playbook"}


@router.get("/accounts/{account_id}/knowledge", response_model=list[KnowledgeOut])
def list_knowledge(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_account_or_404(db, account_id, current_user.id)
    rows = db.query(SentimentKnowledgeORM).filter_by(account_id=account_id).all()
    return [KnowledgeOut(key=r.key, body=r.body, updated_at=r.updated_at) for r in rows]


class KnowledgeUpdate(BaseModel):
    body: str


@router.put("/accounts/{account_id}/knowledge/{key}", response_model=KnowledgeOut)
def upsert_knowledge(
    account_id: int, key: str, payload: KnowledgeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if key not in VALID_KNOWLEDGE_KEYS:
        raise HTTPException(400, f"key must be one of {VALID_KNOWLEDGE_KEYS}")
    _get_account_or_404(db, account_id, current_user.id)

    row = db.query(SentimentKnowledgeORM).filter_by(account_id=account_id, key=key).first()
    if row:
        row.body = payload.body
        row.updated_at = datetime.utcnow()
    else:
        row = SentimentKnowledgeORM(
            account_id=account_id, key=key, body=payload.body,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return KnowledgeOut(key=row.key, body=row.body, updated_at=row.updated_at)


# ─────────────────────────── 健康检查 ────────────────────────


@router.get("/health")
def health(current_user: User = Depends(get_current_user)):
    """转发 sentinel-service 健康状态."""
    try:
        upstream = sentinel_client.health()
        return {"status": "ok", "sentinel": upstream}
    except Exception as e:  # noqa: BLE001
        return {"status": "degraded", "sentinel_error": str(e)}
