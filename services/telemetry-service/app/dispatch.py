"""调度中心(dispatch center)— pull 模型的 worker 接口 + 管理接口.

多机 browser-service worker 部署后只配 DISPATCH_CENTER_URL + DISPATCH_TOKEN,
启动即 register,然后周期 heartbeat + claim(领任务)+ result(交结果)。中心负责:
- worker 注册表(browser_workers)
- 任务队列(dispatch_tasks)的原子领取:Postgres FOR UPDATE SKIP LOCKED 防多 worker 重复领
- 每引擎日上限在 claim 侧执行(deepseek≤50/天 等),disabled/draining worker 领空
- result 落库走与 push 路径完全一致的 detect_hit → save_response → update_query_hit

鉴权:所有 /dispatch/* 路由校验 X-Dispatch-Token == env DISPATCH_TOKEN(未设则开放,dev)。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import bindparam, text

from .scheduler import _day_start_utc, _engine_daily_cap
from .storage import (
    ApiTenantORM, DispatchTaskORM, JobORM, ResponseORM, TopicORM, UsageLedgerORM, WorkerORM,
    db_session, engine as _db_engine, parse_target, save_response,
)
from .tracking import detect_hit, update_query_hit_after_response
from .yuanbao_search import yuanbao_api_enabled


def _api_queue_engines() -> tuple[str, ...]:
    """由中心进程内(API)处理、不交给浏览器 worker 的引擎(据 env 动态判定)。

    元宝:配了 TENCENT_SEARCH_API_KEY → 搜索+deepseek RAG;
    豆包:配了 ARK_API_KEY + DOUBAO_BOT_ID → 火山方舟 ARK API。
    与 runner._call_browser / scheduler._is_browser_engine 的判定保持一致。
    """
    out: list[str] = []
    if yuanbao_api_enabled():
        out.append("yuanbao")
    if os.environ.get("ARK_API_KEY") and os.environ.get("DOUBAO_BOT_ID"):
        out.append("doubao")
    return tuple(out)


def _worker_claimable(engines: list[str]) -> list[str]:
    """从 worker 可领的引擎里剔除「中心 API 处理」的引擎。"""
    api = set(_api_queue_engines())
    return [e for e in engines if e not in api] if api else engines

log = logging.getLogger("telemetry-service.dispatch")

DISPATCH_TOKEN = os.environ.get("DISPATCH_TOKEN", "").strip()
WORKER_OFFLINE_SEC = int(os.environ.get("DISPATCH_WORKER_OFFLINE_SEC", "90"))
# 外部 jobs 每引擎最多吃掉该引擎日上限的这个比例(天花板 ceiling),其余给内部舆情兜底
JOBS_EXTERNAL_ENGINE_SHARE = float(os.environ.get("JOBS_EXTERNAL_ENGINE_SHARE", "0.5"))
# 给外部预留的底量(floor):内部舆情封顶在 cap×(1-RESERVE),这部分日额度永远留给外部,
# 避免外部 job 被内部积压饿死。默认 0.2(给外部留 20%)。设 0 则回到"内部可吃满"的旧行为。
JOBS_EXTERNAL_ENGINE_RESERVE = float(os.environ.get("JOBS_EXTERNAL_ENGINE_RESERVE", "0.2"))
# 每引擎单价(credits / 成功 query),稀缺/贵的引擎更高。可被 ENGINE_PRICE_JSON 覆盖。
_DEFAULT_PRICE = {"deepseek": 2, "qwen": 1, "wenxin": 1, "yuanbao": 1, "doubao": 1,
                  "chatgpt": 5, "claude": 5, "gemini": 3, "copilot": 3, "grok": 3}
ENGINE_PRICE = {**_DEFAULT_PRICE, **json.loads(os.environ.get("ENGINE_PRICE_JSON", "{}"))}
GATEWAY_WEBHOOK_SECRET = os.environ.get("GATEWAY_WEBHOOK_SECRET", "").strip()
_IS_PG = _db_engine.dialect.name == "postgresql"


def _engine_price(engine: str) -> int:
    return int(ENGINE_PRICE.get(engine, 1))


def _fire_webhook(url: str, payload: dict) -> None:
    """best-effort 异步回调:HMAC-SHA256 签名放 X-Signature,短超时,失败只记日志。"""
    def _send() -> None:
        try:
            import httpx  # 局部导入,避免无 httpx 环境 import 失败
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if GATEWAY_WEBHOOK_SECRET:
                sig = hmac.new(GATEWAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
                headers["X-Signature"] = f"sha256={sig}"
            httpx.post(url, content=body, headers=headers, timeout=8)
        except Exception as e:  # noqa: BLE001
            log.warning("[dispatch] webhook %s failed: %s", url, e)
    threading.Thread(target=_send, daemon=True).start()


def _require_token(x_dispatch_token: str = Header(default="")) -> None:
    if DISPATCH_TOKEN and x_dispatch_token != DISPATCH_TOKEN:
        raise HTTPException(401, "bad dispatch token")


router = APIRouter(prefix="/dispatch", dependencies=[Depends(_require_token)])


# ── 请求/响应模型 ──────────────────────────────────────────────────
class RegisterBody(BaseModel):
    worker_uid: Optional[str] = None
    hostname: str = ""
    label: str = ""
    region: str = ""
    exit_ip: str = ""
    engines: list[str] = []
    max_concurrency: int = 3
    version: str = ""


class HeartbeatBody(BaseModel):
    worker_uid: str
    in_flight: int = 0
    breaker: dict = {}          # {engine: until_epoch} 本地熔断态(仅展示用)
    exit_ip: str = ""


class ClaimBody(BaseModel):
    worker_uid: str
    engines: list[str] = []
    free_slots: int = 1


class ClaimedTask(BaseModel):
    task_id: int
    engine: str
    query: str
    kind: str = "telemetry"      # telemetry=内部 dispatch_tasks / job=外部 browser_jobs
    run_id: int = 0              # 仅 telemetry 有意义,job 恒 0(worker 不用)
    topic_id: int = 0


class ResultBody(BaseModel):
    worker_uid: str = ""
    task_id: int
    kind: str = "telemetry"      # worker 原样回传 claim 时拿到的 kind,中心据此路由落库
    answer: str = ""
    citations: list[dict] = []
    source_url: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None


# ── worker 生命周期 ────────────────────────────────────────────────
@router.post("/register")
def register(body: RegisterBody) -> dict:
    uid = (body.worker_uid or "").strip() or uuid.uuid4().hex
    now = datetime.utcnow()
    with db_session() as s:
        w = s.query(WorkerORM).filter(WorkerORM.worker_uid == uid).one_or_none()
        if w is None:
            w = WorkerORM(worker_uid=uid, enabled=True, registered_at=now)
            s.add(w)
        w.hostname = body.hostname or w.hostname
        w.label = body.label or w.label
        w.region = body.region or w.region
        w.exit_ip = body.exit_ip or w.exit_ip
        w.engines_json = json.dumps(body.engines or [], ensure_ascii=False)
        w.max_concurrency = body.max_concurrency or 3
        w.version = body.version or w.version
        w.status = "online"
        w.last_heartbeat_at = now
    log.info("[dispatch] worker registered uid=%s host=%s ip=%s engines=%s",
             uid, body.hostname, body.exit_ip, body.engines)
    return {"worker_uid": uid, "heartbeat_sec": WORKER_OFFLINE_SEC // 3 or 30}


@router.post("/heartbeat")
def heartbeat(body: HeartbeatBody) -> dict:
    now = datetime.utcnow()
    with db_session() as s:
        w = s.query(WorkerORM).filter(WorkerORM.worker_uid == body.worker_uid).one_or_none()
        if w is None:
            raise HTTPException(404, "worker not registered")
        w.last_heartbeat_at = now
        if body.exit_ip:
            w.exit_ip = body.exit_ip
        if w.status not in ("draining", "disabled"):
            w.status = "online"
        w.meta_json = json.dumps({"in_flight": body.in_flight, "breaker": body.breaker},
                                  ensure_ascii=False)
        enabled = bool(w.enabled) and w.status != "draining"
    return {"ok": True, "enabled": enabled}


@router.post("/claim", response_model=list[ClaimedTask])
def claim(body: ClaimBody) -> list[ClaimedTask]:
    n = max(0, min(body.free_slots, 50))
    claim_engines = _worker_claimable(body.engines)   # 元宝(API)不给 worker 领
    if n == 0 or not claim_engines:
        return []
    now_utc = datetime.now(timezone.utc)
    day_start = _day_start_utc(now_utc)
    with db_session() as s:
        w = s.query(WorkerORM).filter(WorkerORM.worker_uid == body.worker_uid).one_or_none()
        if w is None or not w.enabled or w.status == "draining":
            return []                       # 未注册 / 被禁用 / 排空中 → 不派活
        # 今日各引擎已发起数:内部舆情(ai_telemetry_responses)+ 外部 jobs(已领取的)
        # 都消耗同一账号池、同一引擎日上限,所以两边都要计入才不会把池子打穿。
        tele_rows = s.execute(text(
            "SELECT engine, COUNT(*) n FROM ai_telemetry_responses "
            "WHERE created_at >= :ds GROUP BY engine"
        ), {"ds": day_start}).all()
        job_rows = s.execute(text(
            "SELECT engine, COUNT(*) n FROM browser_jobs "
            "WHERE claimed_at >= :ds GROUP BY engine"
        ), {"ds": day_start}).all()
        tele_used = {r.engine: r.n for r in tele_rows}
        job_used = {r.engine: r.n for r in job_rows}
        used = {e: tele_used.get(e, 0) + job_used.get(e, 0)
                for e in set(tele_used) | set(job_used)}
        cap = _engine_daily_cap
        # 1) 内部舆情优先,但封顶在 cap×(1-RESERVE) —— 留出 RESERVE 那部分给外部(floor)。
        #    内部按自身用量(tele_used)判定,这样它吃不到预留给外部的额度。
        internal_allowed = [e for e in claim_engines
                            if tele_used.get(e, 0) < cap(e) * (1 - JOBS_EXTERNAL_ENGINE_RESERVE)]
        tasks = _claim_rows(s, internal_allowed, n, body.worker_uid) if internal_allowed else []
        # 2) 还有空槽 → 外部 jobs 填:外部用量 < cap×SHARE(天花板)且引擎总量 < cap(不打穿池子)。
        #    因内部已封顶在 (1-RESERVE),外部总能拿到至少 RESERVE 那部分,不会被饿死。
        remaining = n - len(tasks)
        if remaining > 0:
            ext_engines = [e for e in claim_engines
                           if job_used.get(e, 0) < cap(e) * JOBS_EXTERNAL_ENGINE_SHARE
                           and used.get(e, 0) < cap(e)]
            if ext_engines:
                tasks += _claim_job_rows(s, ext_engines, remaining, body.worker_uid)
    return [ClaimedTask(**t) for t in tasks]


def _claim_rows(s, engines: list[str], n: int, uid: str) -> list[dict]:
    """原子领取 n 条 queued 任务并置 claimed。Postgres 用 SKIP LOCKED 防并发重复领。"""
    now = datetime.utcnow()
    if _IS_PG:
        sql = text(
            "WITH picked AS ("
            "  SELECT id FROM dispatch_tasks "
            "  WHERE status='queued' AND engine IN :engines "
            "  ORDER BY priority, id "
            "  FOR UPDATE SKIP LOCKED LIMIT :n"
            ") "
            "UPDATE dispatch_tasks t "
            "SET status='claimed', claimed_by=:uid, claimed_at=:now, attempts=attempts+1 "
            "FROM picked WHERE t.id = picked.id "
            "RETURNING t.id, t.run_id, t.topic_id, t.engine, t.query"
        ).bindparams(bindparam("engines", expanding=True))
        rows = s.execute(sql, {"engines": engines, "n": n, "uid": uid, "now": now}).all()
        return [{"task_id": r.id, "run_id": r.run_id, "topic_id": r.topic_id,
                 "engine": r.engine, "query": r.query} for r in rows]
    # SQLite / 其它(本地单 worker 验证)— 无 SKIP LOCKED,SELECT 后逐条更新
    picked = (s.query(DispatchTaskORM)
              .filter(DispatchTaskORM.status == "queued",
                      DispatchTaskORM.engine.in_(engines))
              .order_by(DispatchTaskORM.priority, DispatchTaskORM.id)
              .limit(n).all())
    out = []
    for t in picked:
        t.status = "claimed"; t.claimed_by = uid; t.claimed_at = now; t.attempts = (t.attempts or 0) + 1
        out.append({"task_id": t.id, "run_id": t.run_id, "topic_id": t.topic_id,
                    "engine": t.engine, "query": t.query})
    return out


def _claim_job_rows(s, engines: list[str], n: int, uid: str) -> list[dict]:
    """原子领取 n 条外部 browser_jobs(域中性,无 run_id/topic_id)。与 _claim_rows 同机制。"""
    if n <= 0 or not engines:
        return []
    now = datetime.utcnow()
    if _IS_PG:
        sql = text(
            "WITH picked AS ("
            "  SELECT id FROM browser_jobs "
            "  WHERE status='queued' AND engine IN :engines "
            "  ORDER BY priority, id "
            "  FOR UPDATE SKIP LOCKED LIMIT :n"
            ") "
            "UPDATE browser_jobs t "
            "SET status='claimed', claimed_by=:uid, claimed_at=:now, attempts=attempts+1 "
            "FROM picked WHERE t.id = picked.id "
            "RETURNING t.id, t.engine, t.query"
        ).bindparams(bindparam("engines", expanding=True))
        rows = s.execute(sql, {"engines": engines, "n": n, "uid": uid, "now": now}).all()
        return [{"task_id": r.id, "engine": r.engine, "query": r.query, "kind": "job"}
                for r in rows]
    picked = (s.query(JobORM)
              .filter(JobORM.status == "queued", JobORM.engine.in_(engines))
              .order_by(JobORM.priority, JobORM.id)
              .limit(n).all())
    out = []
    for j in picked:
        j.status = "claimed"; j.claimed_by = uid; j.claimed_at = now; j.attempts = (j.attempts or 0) + 1
        out.append({"task_id": j.id, "engine": j.engine, "query": j.query, "kind": "job"})
    return out


@router.post("/result")
def result(body: ResultBody) -> dict:
    """交结果:按 kind 路由。job 就地存本表(无业务语义);telemetry 走命中判定落库。"""
    if body.kind == "job":
        return _result_job(body)
    with db_session() as s:
        task = s.get(DispatchTaskORM, body.task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        topic = s.get(TopicORM, task.topic_id)
        target, aliases = parse_target(topic) if topic else ("", [])
        error = (body.error or "").strip() or None
        hit, excerpt = (False, None)
        if not error:
            hit, excerpt = detect_hit(body.answer, target, aliases)
        r = save_response(
            s, run_id=task.run_id, topic_id=task.topic_id, engine=task.engine,
            query=task.query, answer=body.answer, citations=body.citations,
            video_url=body.video_url, error=error, hit=hit, hit_excerpt=excerpt,
            source_url=body.source_url,
        )
        if not error and topic is not None:
            update_query_hit_after_response(s, response=r, topic=topic)
        # 失败且仍有重试余量 → 退回队列(下次任意 worker 再领);否则定状态收尾
        if error and (task.attempts or 0) < (task.max_attempts or 1):
            task.status = "queued"; task.claimed_by = None; task.claimed_at = None
            task.error = error
            requeued = True
        else:
            task.status = "failed" if error else "done"
            task.finished_at = datetime.utcnow()
            task.error = error
            requeued = False
    return {"ok": True, "hit": hit, "requeued": requeued}


def _result_job(body: ResultBody) -> dict:
    """外部 job 交结果:就地写 browser_jobs,不碰任何舆情表。终态时计量计费 + 回调。"""
    error = (body.error or "").strip() or None
    webhook: Optional[tuple[str, dict]] = None
    with db_session() as s:
        job = s.get(JobORM, body.task_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if error and (job.attempts or 0) < (job.max_attempts or 1):
            job.status = "queued"; job.claimed_by = None; job.claimed_at = None
            job.error = error
            return {"ok": True, "requeued": True}      # 还要重试,先不计费/不回调

        # 终态:落结果
        ok = not error
        job.status = "done" if ok else "failed"
        job.answer = body.answer or ""
        job.citations_json = json.dumps(body.citations or [], ensure_ascii=False)
        job.source_url = body.source_url
        job.video_url = body.video_url
        job.error = error
        job.finished_at = datetime.utcnow()

        # 计量计费(P2):成功才计费 + 扣额度;失败只记一行 billable=False
        cost = _engine_price(job.engine) if ok else 0
        if job.tenant_id:
            try:
                tid = int(job.tenant_id)
            except (TypeError, ValueError):
                tid = None
            if tid is not None:
                s.add(UsageLedgerORM(tenant_id=tid, job_id=job.id, engine=job.engine,
                                     billable=ok, cost=cost))
                if ok and cost:
                    t = s.get(ApiTenantORM, tid)
                    if t is not None:
                        t.credit_balance = (t.credit_balance or 0) - cost
        if job.callback_url:
            webhook = (job.callback_url, {
                "job_id": job.id, "status": job.status, "engine": job.engine,
                "answer": job.answer, "error": job.error,
                "citations": json.loads(job.citations_json or "[]"),
                "video_url": job.video_url,
            })
    if webhook:                                        # 出 session 再触发,不占着事务
        _fire_webhook(*webhook)
    return {"ok": True, "requeued": False}


# ── 外部 job 队列接口(P0:内部/admin 经 X-Dispatch-Token 入队 + 查结果)──────────
# 公开多租户网关(API Key 鉴权 + 配额 + 计费)是 P1,届时在 /v1 前置一层后转发到这里。
class EnqueueJobBody(BaseModel):
    engine: str
    query: str
    priority: int = 10
    tenant_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    callback_url: Optional[str] = None
    max_attempts: int = 2


@router.post("/jobs")
def enqueue_job(body: EnqueueJobBody) -> dict:
    if not body.engine or not body.query.strip():
        raise HTTPException(400, "engine and query are required")
    with db_session() as s:
        if body.idempotency_key:
            ex = (s.query(JobORM)
                  .filter(JobORM.idempotency_key == body.idempotency_key).one_or_none())
            if ex is not None:
                return {"job_id": ex.id, "status": ex.status, "dedup": True}
        j = JobORM(
            tenant_id=body.tenant_id, engine=body.engine, query=body.query.strip()[:2048],
            priority=body.priority, status="queued", max_attempts=max(1, body.max_attempts),
            idempotency_key=body.idempotency_key or None, callback_url=body.callback_url,
        )
        s.add(j); s.flush()
        jid = j.id
    return {"job_id": jid, "status": "queued"}


@router.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    with db_session() as s:
        j = s.get(JobORM, job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return {
            "job_id": j.id, "tenant_id": j.tenant_id, "engine": j.engine, "query": j.query,
            "status": j.status, "attempts": j.attempts,
            "answer": j.answer or "", "citations": json.loads(j.citations_json or "[]"),
            "source_url": j.source_url, "video_url": j.video_url, "error": j.error,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }


# ── 管理接口(后端 require_admin 代理调用)────────────────────────────
@router.get("/workers")
def list_workers() -> list[dict]:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=WORKER_OFFLINE_SEC)
    day_start_naive = _day_start_utc(datetime.now(timezone.utc))
    with db_session() as s:
        workers = s.query(WorkerORM).order_by(WorkerORM.id).all()
        # 每 worker 今日完成数 + 在飞行数(从 dispatch_tasks 的 claimed_by 统计)
        done_rows = s.execute(text(
            "SELECT claimed_by, COUNT(*) n FROM dispatch_tasks "
            "WHERE finished_at >= :ds AND status IN ('done','failed') GROUP BY claimed_by"
        ), {"ds": day_start_naive}).all()
        done_today = {r.claimed_by: r.n for r in done_rows}
        inflight_rows = s.execute(text(
            "SELECT claimed_by, COUNT(*) n FROM dispatch_tasks "
            "WHERE status='claimed' GROUP BY claimed_by"
        )).all()
        inflight = {r.claimed_by: r.n for r in inflight_rows}
        out = []
        for w in workers:
            online = bool(w.last_heartbeat_at and w.last_heartbeat_at >= cutoff)
            try:
                meta = json.loads(w.meta_json or "{}")
            except Exception:  # noqa: BLE001
                meta = {}
            out.append({
                "id": w.id, "worker_uid": w.worker_uid, "hostname": w.hostname,
                "label": w.label, "region": w.region, "exit_ip": w.exit_ip,
                "engines": json.loads(w.engines_json or "[]"),
                "max_concurrency": w.max_concurrency,
                "status": "online" if online else "offline",
                "raw_status": w.status, "enabled": bool(w.enabled),
                "version": w.version,
                "last_heartbeat_at": w.last_heartbeat_at.isoformat() if w.last_heartbeat_at else None,
                "done_today": done_today.get(w.worker_uid, 0),
                "in_flight": inflight.get(w.worker_uid, 0),
                "breaker": meta.get("breaker", {}),
            })
    return out


@router.get("/queue/stats")
def queue_stats() -> dict:
    day_start = _day_start_utc(datetime.now(timezone.utc))
    with db_session() as s:
        by = s.execute(text(
            "SELECT engine, status, COUNT(*) n FROM dispatch_tasks GROUP BY engine, status"
        )).all()
        queue: dict[str, dict] = {}
        for r in by:
            queue.setdefault(r.engine, {})[r.status] = r.n
        used_rows = s.execute(text(
            "SELECT engine, COUNT(*) n FROM ai_telemetry_responses "
            "WHERE created_at >= :ds GROUP BY engine"
        ), {"ds": day_start}).all()
        used_today = {r.engine: r.n for r in used_rows}
    caps = {e: (None if _engine_daily_cap(e) == float("inf") else int(_engine_daily_cap(e)))
            for e in set(list(queue.keys()) + list(used_today.keys()))}
    return {"queue": queue, "used_today": used_today, "daily_cap": caps}


class WorkerActionResult(BaseModel):
    ok: bool
    status: str


@router.post("/workers/{worker_uid}/{action}", response_model=WorkerActionResult)
def worker_action(worker_uid: str, action: str) -> WorkerActionResult:
    if action not in ("enable", "disable", "drain"):
        raise HTTPException(400, "action must be enable|disable|drain")
    with db_session() as s:
        w = s.query(WorkerORM).filter(WorkerORM.worker_uid == worker_uid).one_or_none()
        if w is None:
            raise HTTPException(404, "worker not found")
        if action == "enable":
            w.enabled = True
            w.status = "online" if w.last_heartbeat_at else "offline"
        elif action == "disable":
            w.enabled = False
            w.status = "disabled"
        else:  # drain：保留 enabled,但停止派活,跑完在飞行的
            w.status = "draining"
        status = w.status
    return WorkerActionResult(ok=True, status=status)


# ── 中心 API 引擎处理器(元宝等不走浏览器 worker 的引擎)──────────────────
def _claim_one_api_job() -> Optional[tuple[int, str, str]]:
    """领一条 queued 的 API 引擎 job(元宝/豆包),置 claimed,返回 (id, engine, query)。"""
    engines = _api_queue_engines()
    if not engines:
        return None
    now = datetime.utcnow()
    with db_session() as s:
        if _IS_PG:
            row = s.execute(text(
                "WITH picked AS ("
                "  SELECT id FROM browser_jobs "
                "  WHERE status='queued' AND engine IN :engines "
                "  ORDER BY priority, id FOR UPDATE SKIP LOCKED LIMIT 1"
                ") "
                "UPDATE browser_jobs t "
                "SET status='claimed', claimed_by='telemetry-api', claimed_at=:now, attempts=attempts+1 "
                "FROM picked WHERE t.id=picked.id RETURNING t.id, t.engine, t.query"
            ).bindparams(bindparam("engines", expanding=True)),
                {"engines": list(engines), "now": now}).first()
            return (row.id, row.engine, row.query) if row else None
        j = (s.query(JobORM)
             .filter(JobORM.status == "queued", JobORM.engine.in_(engines))
             .order_by(JobORM.priority, JobORM.id).first())
        if j is None:
            return None
        j.status = "claimed"; j.claimed_by = "telemetry-api"; j.claimed_at = now
        j.attempts = (j.attempts or 0) + 1
        return (j.id, j.engine, j.query)


async def api_jobs_loop(stop: asyncio.Event) -> None:
    """后台循环:领取并处理 API 引擎(元宝/豆包)的外部 job。

    按引擎经 runner._call_browser 统一分发(元宝→搜索RAG、豆包→ARK),
    再交结果复用 _result_job(计费/回调)。无 API 引擎启用时不启动。
    """
    engines = _api_queue_engines()
    if not engines:
        log.info("[api-jobs] 无 API 引擎启用(元宝/豆包 key 均未配),processor 不启动")
        return
    from .runner import _call_browser   # 延迟导入,避免 import 期循环
    log.info("[api-jobs] processor started, engines=%s", engines)
    async with httpx.AsyncClient() as client:
        while not stop.is_set():
            try:
                claimed = _claim_one_api_job()
            except Exception as e:  # noqa: BLE001
                log.warning("[api-jobs] claim failed: %s", e); claimed = None
            if not claimed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=3)
                except asyncio.TimeoutError:
                    pass
                continue
            jid, engine, query = claimed
            try:
                res = await _call_browser(client, engine, query)
            except Exception as e:  # noqa: BLE001
                res = {"answer": "", "citations": [], "error": f"{engine} exception: {e}"}
            try:
                _result_job(ResultBody(worker_uid="telemetry-api", task_id=jid, kind="job",
                                       answer=res.get("answer", ""), citations=res.get("citations", []),
                                       source_url=res.get("source_url"), video_url=res.get("video_url"),
                                       error=res.get("error")))
            except Exception as e:  # noqa: BLE001
                log.warning("[api-jobs] result job %s failed: %s", jid, e)
    log.info("[api-jobs] processor stopped")
