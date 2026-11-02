"""对外多租户网关(/v1)— 把 browser_jobs 队列包装成公开商业 API。

鉴权:Authorization: Bearer sk-live-xxx → sha256 比对 api_keys → 载入 tenant。
配额:每租户每引擎日配额(从 browser_jobs 当日计数,失败不占),超额 429 + Retry-After。
隔离:GET /v1/jobs/{id} 只能看自己租户的 job;别的租户一律 404。
入队后复用 P0 的 JobORM,worker 侧零感知(claim 时内部舆情仍绝对优先)。

计费/账本(usage_ledger)、webhook firing、Stripe 是 P2;P1 用 browser_jobs.tenant_id
当用量来源,够跑通"鉴权→配额→异步 job→查结果"全链路。

ENV:
- GATEWAY_ADMIN_TOKEN   建租户/发 key 的管理口令(X-Admin-Token),未设则 admin 关闭
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .scheduler import _day_start_utc
from .storage import ApiKeyORM, ApiTenantORM, JobORM, UsageLedgerORM, db_session

# 当前 worker 机队支持的引擎(与 browser-service 适配器对齐)
ALL_ENGINES = (
    "deepseek", "qwen", "wenxin", "yuanbao", "doubao",
    "chatgpt", "claude", "gemini", "copilot", "grok",
)

GATEWAY_ADMIN_TOKEN = os.environ.get("GATEWAY_ADMIN_TOKEN", "").strip()

router = APIRouter(prefix="/v1", tags=["gateway"])


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def require_tenant(authorization: str = Header(default="")) -> dict:
    """解析 Bearer key → 返回租户快照(dict,脱离 session 不怕过期)。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer api key")
    raw = authorization[7:].strip()
    if not raw:
        raise HTTPException(401, "empty api key")
    h = _hash_key(raw)
    with db_session() as s:
        k = s.query(ApiKeyORM).filter(
            ApiKeyORM.key_hash == h, ApiKeyORM.status == "active").one_or_none()
        if k is None:
            raise HTTPException(401, "invalid api key")
        t = s.get(ApiTenantORM, k.tenant_id)
        if t is None or t.status != "active":
            raise HTTPException(403, "tenant suspended")
        k.last_used_at = datetime.utcnow()
        return {
            "tenant_id": t.id, "name": t.name, "tier": t.tier,
            "engines": json.loads(t.engines_json or "[]"),
            "quota": json.loads(t.daily_quota_json or "{}"),
            "quota_default": t.daily_quota_default,
            "key_id": k.id,
        }


def _allowed_engines(t: dict) -> list[str]:
    return t["engines"] or list(ALL_ENGINES)


def _engine_quota(t: dict, engine: str) -> int:
    return int(t["quota"].get(engine, t["quota_default"]))


def _used_today(s, tenant_id: int, engine: str, day_start) -> int:
    return s.execute(text(
        "SELECT COUNT(*) FROM browser_jobs "
        "WHERE tenant_id = :tid AND engine = :e AND created_at >= :ds AND status != 'failed'"
    ), {"tid": str(tenant_id), "e": engine, "ds": day_start}).scalar() or 0


# 内容审核(P2 基础版):命中即拒,保护共享账号池不被违规 query 连累封号。
# 真正上量应换成可插拔的 LLM 审核;这里先用黑名单 + 长度兜底,留好接口。
_BLOCKLIST = tuple(w for w in os.environ.get(
    "GATEWAY_BLOCKLIST", "制造炸弹,制毒,儿童色情,枪支购买").split(",") if w.strip())


def _moderate(query: str) -> Optional[str]:
    """返回拒绝原因;通过返回 None。"""
    if len(query) > 2000:
        return "query too long (>2000 chars)"
    low = query.lower()
    for w in _BLOCKLIST:
        if w.strip() and w.strip().lower() in low:
            return "query rejected by content policy"
    return None


# ── 公开端点 ────────────────────────────────────────────────────────
class CreateJobIn(BaseModel):
    engine: str
    query: str
    idempotency_key: Optional[str] = None
    callback_url: Optional[str] = None


@router.get("/engines")
def list_engines(t: dict = Depends(require_tenant)) -> dict:
    day_start = _day_start_utc(datetime.now(timezone.utc))
    allowed = _allowed_engines(t)
    out = []
    with db_session() as s:
        for e in allowed:
            q = _engine_quota(t, e)
            used = _used_today(s, t["tenant_id"], e, day_start)
            out.append({"engine": e, "daily_quota": q, "used_today": used,
                        "remaining": max(0, q - used)})
    return {"tier": t["tier"], "engines": out}


@router.post("/jobs")
def create_job(body: CreateJobIn, t: dict = Depends(require_tenant)) -> dict:
    engine = (body.engine or "").strip()
    query = (body.query or "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    if engine not in _allowed_engines(t):
        raise HTTPException(403, f"engine '{engine}' not enabled for this tenant")
    reason = _moderate(query)
    if reason:
        raise HTTPException(422, reason)

    now_utc = datetime.now(timezone.utc)
    day_start = _day_start_utc(now_utc)
    idem = f"{t['tenant_id']}:{body.idempotency_key}" if body.idempotency_key else None
    # pro 档 job 优先级高于 free(数字小=先领);两者都仍低于内部舆情(0/1)
    priority = 5 if t["tier"] != "free" else 10

    with db_session() as s:
        if idem:
            ex = s.query(JobORM).filter(JobORM.idempotency_key == idem).one_or_none()
            if ex is not None:
                return {"job_id": ex.id, "status": ex.status, "dedup": True}
        # 预付额度护栏:余额不足直接 402(实际扣费在 job 成功后由调度中心做)
        tnow = s.get(ApiTenantORM, t["tenant_id"])
        if tnow is not None and (tnow.credit_balance or 0) <= 0:
            raise HTTPException(402, "insufficient credits")
        used = _used_today(s, t["tenant_id"], engine, day_start)
        quota = _engine_quota(t, engine)
        if used >= quota:
            retry = int((_day_start_utc(now_utc).replace(tzinfo=timezone.utc)
                         .timestamp() + 86400) - now_utc.timestamp())
            raise HTTPException(429, f"daily quota reached for '{engine}' ({used}/{quota})",
                                headers={"Retry-After": str(max(1, retry))})
        # 每租户 RPM 限流(防突发滥用):最近 60s 该租户请求数 ≥ 上限 → 429
        rpm = int(os.environ.get("GATEWAY_TENANT_RPM", "60"))
        if rpm > 0:
            recent = (s.query(JobORM)
                      .filter(JobORM.tenant_id == str(t["tenant_id"]))
                      .filter(JobORM.created_at >= datetime.utcnow() - timedelta(seconds=60))
                      .count())
            if recent >= rpm:
                raise HTTPException(429, f"rate limit: {rpm}/min reached",
                                    headers={"Retry-After": "60"})
        j = JobORM(tenant_id=str(t["tenant_id"]), engine=engine, query=query[:2048],
                   priority=priority, status="queued", max_attempts=2,
                   idempotency_key=idem, callback_url=body.callback_url)
        s.add(j); s.flush()
        jid = j.id
    return {"job_id": jid, "status": "queued"}


@router.get("/usage")
def usage(t: dict = Depends(require_tenant)) -> dict:
    """租户用量 + 余额:总计费次数/credits、当日各引擎计数。"""
    day_start = _day_start_utc(datetime.now(timezone.utc))
    with db_session() as s:
        tnow = s.get(ApiTenantORM, t["tenant_id"])
        balance = (tnow.credit_balance if tnow else 0)
        agg = s.execute(text(
            "SELECT COALESCE(SUM(CASE WHEN billable THEN 1 ELSE 0 END),0) billable_n, "
            "COALESCE(SUM(cost),0) spent FROM usage_ledger WHERE tenant_id = :tid"
        ), {"tid": t["tenant_id"]}).one()
        today = s.execute(text(
            "SELECT engine, COUNT(*) n FROM browser_jobs "
            "WHERE tenant_id = :tid AND created_at >= :ds AND status != 'failed' GROUP BY engine"
        ), {"tid": str(t["tenant_id"]), "ds": day_start}).all()
        return {
            "credit_balance": balance,
            "billable_total": int(agg.billable_n), "credits_spent_total": int(agg.spent),
            "today_by_engine": {r.engine: r.n for r in today},
        }


@router.get("/jobs/{job_id}")
def get_job(job_id: int, t: dict = Depends(require_tenant)) -> dict:
    with db_session() as s:
        j = s.get(JobORM, job_id)
        # 隔离:别的租户的 job 一律当不存在,不泄露存在性
        if j is None or j.tenant_id != str(t["tenant_id"]):
            raise HTTPException(404, "job not found")
        return {
            "job_id": j.id, "engine": j.engine, "query": j.query, "status": j.status,
            "answer": j.answer or "", "citations": json.loads(j.citations_json or "[]"),
            "source_url": j.source_url, "video_url": j.video_url, "error": j.error,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }


# ── 管理端点(P1 临时:X-Admin-Token 建租户 + 发 key;P2 换正式控制台)──────
class CreateTenantIn(BaseModel):
    name: str
    tier: str = "free"
    engines: list[str] = []          # 白名单,空=全放开
    daily_quota_default: int = 20
    daily_quota: dict = {}           # {engine: n} 覆盖默认


def _require_admin(x_admin_token: str = Header(default="")) -> None:
    if not GATEWAY_ADMIN_TOKEN or x_admin_token != GATEWAY_ADMIN_TOKEN:
        raise HTTPException(401, "bad admin token")


@router.post("/admin/tenants", dependencies=[Depends(_require_admin)])
def create_tenant(body: CreateTenantIn) -> dict:
    raw = "sk-live-" + secrets.token_urlsafe(32)
    with db_session() as s:
        t = ApiTenantORM(
            name=body.name, tier=body.tier,
            engines_json=json.dumps(body.engines or [], ensure_ascii=False),
            daily_quota_json=json.dumps(body.daily_quota or {}, ensure_ascii=False),
            daily_quota_default=body.daily_quota_default,
        )
        s.add(t); s.flush()
        k = ApiKeyORM(tenant_id=t.id, key_prefix=raw[:12], key_hash=_hash_key(raw),
                      name="default")
        s.add(k); s.flush()
        tid, kid = t.id, k.id
    return {"tenant_id": tid, "key_id": kid, "api_key": raw,
            "note": "api_key 仅此一次明文返回,请妥存"}


class TopUpIn(BaseModel):
    amount: int


@router.post("/admin/tenants/{tenant_id}/credits", dependencies=[Depends(_require_admin)])
def top_up(tenant_id: int, body: TopUpIn) -> dict:
    """充值额度(P2 占位:正式应由 Stripe 支付成功回调触发,这里手动加)。"""
    if body.amount == 0:
        raise HTTPException(400, "amount must be non-zero")
    with db_session() as s:
        t = s.get(ApiTenantORM, tenant_id)
        if t is None:
            raise HTTPException(404, "tenant not found")
        t.credit_balance = (t.credit_balance or 0) + body.amount
        bal = t.credit_balance
    return {"tenant_id": tenant_id, "credit_balance": bal}


# ── 运营面板用:列表 / 更新 / 调用流水 / 重发 key ────────────────────────
@router.get("/admin/tenants", dependencies=[Depends(_require_admin)])
def admin_list_tenants() -> dict:
    day_start = _day_start_utc(datetime.now(timezone.utc))
    with db_session() as s:
        tenants = s.query(ApiTenantORM).order_by(ApiTenantORM.id).all()
        today_rows = s.execute(text(
            "SELECT tenant_id, COUNT(*) n FROM browser_jobs "
            "WHERE created_at >= :ds AND status != 'failed' GROUP BY tenant_id"
        ), {"ds": day_start}).all()
        today = {r.tenant_id: r.n for r in today_rows}          # tenant_id 是字符串
        bill_rows = s.execute(text(
            "SELECT tenant_id, COUNT(*) n, COALESCE(SUM(cost),0) c FROM usage_ledger "
            "WHERE billable GROUP BY tenant_id"
        )).all()
        bill = {r.tenant_id: (r.n, r.c) for r in bill_rows}     # tenant_id 是整数
        key_rows = s.execute(text(
            "SELECT tenant_id, COUNT(*) n FROM api_keys WHERE status='active' GROUP BY tenant_id"
        )).all()
        keys = {r.tenant_id: r.n for r in key_rows}
        out = []
        for t in tenants:
            bn, bc = bill.get(t.id, (0, 0))
            out.append({
                "id": t.id, "name": t.name, "status": t.status, "tier": t.tier,
                "engines": json.loads(t.engines_json or "[]"),
                "daily_quota_default": t.daily_quota_default,
                "daily_quota": json.loads(t.daily_quota_json or "{}"),
                "credit_balance": t.credit_balance,
                "active_keys": keys.get(t.id, 0),
                "calls_today": today.get(str(t.id), 0),
                "billable_total": int(bn), "credits_spent_total": int(bc),
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
        return {"tenants": out}


class UpdateTenantIn(BaseModel):
    status: Optional[str] = None
    tier: Optional[str] = None
    engines: Optional[list[str]] = None
    daily_quota_default: Optional[int] = None
    daily_quota: Optional[dict] = None


@router.patch("/admin/tenants/{tenant_id}", dependencies=[Depends(_require_admin)])
def admin_update_tenant(tenant_id: int, body: UpdateTenantIn) -> dict:
    with db_session() as s:
        t = s.get(ApiTenantORM, tenant_id)
        if t is None:
            raise HTTPException(404, "tenant not found")
        if body.status is not None:
            if body.status not in ("active", "suspended"):
                raise HTTPException(400, "status must be active|suspended")
            t.status = body.status
        if body.tier is not None:
            t.tier = body.tier
        if body.engines is not None:
            t.engines_json = json.dumps(body.engines, ensure_ascii=False)
        if body.daily_quota_default is not None:
            t.daily_quota_default = body.daily_quota_default
        if body.daily_quota is not None:
            t.daily_quota_json = json.dumps(body.daily_quota, ensure_ascii=False)
    return {"ok": True}


@router.post("/admin/tenants/{tenant_id}/keys", dependencies=[Depends(_require_admin)])
def admin_reissue_key(tenant_id: int) -> dict:
    """给租户新发一把 key(旧 key 不动,需要时另行吊销)。明文只此一次返回。"""
    raw = "sk-live-" + secrets.token_urlsafe(32)
    with db_session() as s:
        t = s.get(ApiTenantORM, tenant_id)
        if t is None:
            raise HTTPException(404, "tenant not found")
        k = ApiKeyORM(tenant_id=tenant_id, key_prefix=raw[:12], key_hash=_hash_key(raw),
                      name="reissued")
        s.add(k); s.flush()
        kid = k.id
    return {"tenant_id": tenant_id, "key_id": kid, "api_key": raw,
            "note": "api_key 仅此一次明文返回,请妥存"}


@router.post("/admin/keys/{key_id}/revoke", dependencies=[Depends(_require_admin)])
def admin_revoke_key(key_id: int) -> dict:
    with db_session() as s:
        k = s.get(ApiKeyORM, key_id)
        if k is None:
            raise HTTPException(404, "key not found")
        k.status = "revoked"
    return {"ok": True}


@router.get("/admin/jobs", dependencies=[Depends(_require_admin)])
def admin_list_jobs(tenant_id: Optional[int] = None, limit: int = 50) -> dict:
    """最近调用流水(运营看板)。可按租户过滤。"""
    n = max(1, min(limit, 200))
    with db_session() as s:
        q = s.query(JobORM).order_by(JobORM.id.desc())
        if tenant_id is not None:
            q = q.filter(JobORM.tenant_id == str(tenant_id))
        rows = q.limit(n).all()
        return {"jobs": [{
            "id": j.id, "tenant_id": j.tenant_id, "engine": j.engine,
            "query": (j.query or "")[:200], "status": j.status,
            "error": j.error,
            # 返回内容(运营页展开查看)— answer 截断防列表过大,citations 全带
            "answer": (j.answer or "")[:3000],
            "citations": json.loads(j.citations_json or "[]"),
            "source_url": j.source_url, "video_url": j.video_url,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        } for j in rows]}
