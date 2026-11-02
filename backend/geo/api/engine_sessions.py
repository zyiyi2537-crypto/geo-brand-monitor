"""Engine session pool — upload (harvester) + check-out/check-in (browser-service).

三个角色:
  1. **harvester** (scripts/harvest_sessions.py 用户机器上跑):
       POST /api/engine-sessions/upload  +  header X-Harvest-Token
  2. **browser-service** (vm03 跑 search 前 fetch session):
       POST /api/engine-sessions/check-out  +  header X-Service-Token
       POST /api/engine-sessions/check-in   +  header X-Service-Token
  3. **dashboard / 运维** (查池子健康):
       GET  /api/engine-sessions/pool-status  (无 auth,只读统计)

环境变量(deploy 时配):
  ENGINE_SESSION_HARVEST_TOKEN  — 给所有用户分发,upload 鉴权
  ENGINE_SESSION_SERVICE_TOKEN  — backend ↔ browser-service 之间的内部 token
  ENGINE_SESSION_VALID_ENGINES  — 逗号分隔,默认 doubao,qwen,deepseek,wenxin,yuanbao
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from geo.database import SessionLocal
from geo.models.engine_sessions import (
    EngineSessionORM,
    FailureType,
    PoolStatusEntry,
    SessionCheckIn,
    SessionCheckedOut,
    SessionUploadIn,
    extract_account_handle,
    extract_account_id,
)


router = APIRouter()


# ── DB session helper ───────────────────────────────────────────────


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Auth helpers ────────────────────────────────────────────────────


def _require_harvest_token(x_harvest_token: Optional[str] = Header(None)) -> None:
    expected = (os.environ.get("ENGINE_SESSION_HARVEST_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(503, "harvest endpoint disabled (server token not configured)")
    if not x_harvest_token or x_harvest_token != expected:
        raise HTTPException(401, "invalid X-Harvest-Token")


def _require_service_token(x_service_token: Optional[str] = Header(None)) -> None:
    expected = (os.environ.get("ENGINE_SESSION_SERVICE_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(503, "service endpoints disabled (server token not configured)")
    if not x_service_token or x_service_token != expected:
        raise HTTPException(401, "invalid X-Service-Token")


def _require_upload_token(
    x_harvest_token: Optional[str] = Header(None),
    x_service_token: Optional[str] = Header(None),
) -> None:
    """upload 接受 harvest token(采集端)或 service token(内网 authorizer 自动登录)。"""
    harvest = (os.environ.get("ENGINE_SESSION_HARVEST_TOKEN") or "").strip()
    service = (os.environ.get("ENGINE_SESSION_SERVICE_TOKEN") or "").strip()
    if harvest and x_harvest_token == harvest:
        return
    if service and x_service_token == service:
        return
    raise HTTPException(401, "invalid X-Harvest-Token / X-Service-Token")


# ── Config ──────────────────────────────────────────────────────────


def _valid_engines() -> set[str]:
    raw = os.environ.get("ENGINE_SESSION_VALID_ENGINES") or "doubao,qwen,deepseek,wenxin,yuanbao"
    return {e.strip() for e in raw.split(",") if e.strip()}


_CAPTCHA_QUARANTINE_THRESHOLD = 3   # 累计被挑 CAPTCHA 3 次 → quarantine
# 身份绑定:check-out 带 worker_id 时给账号打租约,粘在该 worker/IP 上这么久;
# 活跃 worker 每次 check-out 会续租,挂掉的 worker 租约到期后账号释放给别人。
_LEASE_TTL_HOURS = int(os.environ.get("ENGINE_SESSION_LEASE_TTL_HOURS", "6"))


def _local_today() -> str:
    """本地(北京)日期字符串,用于单账号每日用量归零。"""
    return (datetime.utcnow() + timedelta(hours=8)).date().isoformat()


# 单账号每日 check-out 默认上限(0=不限)。env ENGINE_SESSION_DAILY_CAP_<ENGINE> 覆盖,
# 每账号 daily_cap 列再覆盖 env。doubao 走 ARK API 无号限 → 0。
_DEFAULT_DAILY_CAP = {
    "deepseek": 30, "qwen": 30, "wenxin": 30, "yuanbao": 30, "doubao": 0,
}


def _session_daily_cap(engine: str) -> int:
    """引擎级单账号每日 check-out 默认上限;0 = 不限。
    env ENGINE_SESSION_DAILY_CAP_<ENGINE> 覆盖默认值;每账号 daily_cap 列再覆盖 env。"""
    ov = os.environ.get(f"ENGINE_SESSION_DAILY_CAP_{engine.upper()}")
    if ov and ov.isdigit():
        return int(ov)
    return _DEFAULT_DAILY_CAP.get(engine.lower(), 0)

# ── Quarantine policy(D2 — P1 失败信号 enum 化)──────────────────
#
# 各 FailureType 触发 quarantine 的政策:
#   - threshold: 累计达 N 次 quarantine
#   - immediate: 单次就 quarantine(像 login_lost 这种不可逆 fail)
#   - skip: 不计入 session 账,通常是 worker 端问题(crash)
#
# policy=None 表示 SUCCESS,重置所有 fail_counts(防止旧失败累积到永远)。
_QUARANTINE_POLICY: dict[FailureType, dict] = {
    FailureType.SUCCESS:        {"reset": True},
    FailureType.CAPTCHA:        {"threshold": 3, "legacy_col": "captcha_count"},
    FailureType.LOGIN_LOST:     {"immediate": True},
    FailureType.EMPTY_ANSWER:   {"threshold": 5},
    FailureType.DOM_NOT_FOUND:  {"threshold": 3, "alert": True},  # alert: 可能引擎改版
    FailureType.TIMEOUT:        {"threshold": 5},
    FailureType.CRASH:          {"skip": True},
    FailureType.RATE_LIMITED:   {"cooldown": True},   # 风控限流/禁言:冷却该号到 mute_until,不隔离不罚
}

# RATE_LIMITED 默认冷却(没带 rate_limited_until 时):env ENGINE_RATE_LIMIT_COOLDOWN_SEC,默认 6h
_RATE_LIMIT_COOLDOWN_SEC = int(os.environ.get("ENGINE_RATE_LIMIT_COOLDOWN_SEC", str(6 * 3600)))


# ── Endpoints ───────────────────────────────────────────────────────


@router.post("/engine-sessions/upload", status_code=201)
def upload_session(
    payload: SessionUploadIn,
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_upload_token),
):
    """Harvester 上传一份新登录拿到的 storage_state。

    账号识别两级:先按 storage_state 提取的稳定身份 account_id 匹配
    (extract_account_id,不依赖人填),提不到/没匹配上再按
    (engine, source_label) 匹配。认出老账号就原地续期(刷新
    storage_state / captured_at / expires_at,状态回 active,清失败计数),
    而不是落一条新行 —— 否则老账号永远挂着"过期",池子越积越多。
    同账号的其他历史重复行(早期多次上传产生)顺手删掉。
    两级都识别不了才插入新行。
    """
    if payload.engine not in _valid_engines():
        raise HTTPException(400, f"unsupported engine: {payload.engine!r}")
    cookies = payload.storage_state.get("cookies") or []
    if not cookies:
        raise HTTPException(400, "storage_state has no cookies — likely not logged in")

    now = datetime.utcnow()
    label = (payload.source_label or "").strip() or None
    handle = ((payload.account_handle or "").strip()
              or extract_account_handle(payload.engine, payload.storage_state))
    account_id = extract_account_id(payload.engine, payload.storage_state)

    matches: list[EngineSessionORM] = []
    if account_id:
        matches = (
            db.query(EngineSessionORM)
            .filter(EngineSessionORM.engine == payload.engine)
            .filter(EngineSessionORM.account_id == account_id)
            .order_by(EngineSessionORM.captured_at.desc(), EngineSessionORM.id.desc())
            .all()
        )
    if not matches and label:
        # 老行还没有 account_id(历史数据)/ 这家引擎提取不到 → 退回 label 匹配
        matches = (
            db.query(EngineSessionORM)
            .filter(EngineSessionORM.engine == payload.engine)
            .filter(EngineSessionORM.source_label == label)
            .order_by(EngineSessionORM.captured_at.desc(), EngineSessionORM.id.desc())
            .all()
        )
        if account_id:
            # label 匹配出的行如果已绑了别的 account_id,说明同 label 换了账号 → 不算同账号
            matches = [m for m in matches if not m.account_id or m.account_id == account_id]

    row = matches[0] if matches else None
    for stale in matches[1:]:
        db.delete(stale)

    renewed = row is not None
    if renewed:
        row.account_id = account_id or row.account_id
        row.account_handle = handle or row.account_handle
        row.source_label = label or row.source_label
        row.storage_state = json.dumps(payload.storage_state, ensure_ascii=False)
        row.user_agent = payload.user_agent
        row.platform = payload.platform
        row.captured_at = now
        row.expires_at = now + timedelta(days=payload.ttl_days)
        row.status = "active"
        # 新登录 = 干净的开始:清验证码 / 失败累计;use_count 保留(跨账号负载均衡用)
        row.captcha_count = 0
        row.fail_counts_json = "{}"
        row.last_fail_type = None
        row.last_fail_at = None
        if payload.auth_type:
            row.auth_type = payload.auth_type
        if payload.credentials:                 # 只在带凭证时更新,避免清掉已存的
            row.credentials = payload.credentials
    else:
        row = EngineSessionORM(
            engine=payload.engine,
            source_label=label,
            account_id=account_id,
            account_handle=handle,
            storage_state=json.dumps(payload.storage_state, ensure_ascii=False),
            user_agent=payload.user_agent,
            platform=payload.platform,
            captured_at=now,
            expires_at=now + timedelta(days=payload.ttl_days),
            status="active",
            auth_type=payload.auth_type,
            credentials=payload.credentials,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "engine": row.engine,
            "expires_at": row.expires_at.isoformat(), "renewed": renewed,
            "account_id": row.account_id, "account_handle": row.account_handle}


@router.get("/engine-sessions/refresh-candidates")
def refresh_candidates(
    engine: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_service_token),
):
    """掉线(quarantined)且有加密凭证的密码型账号 —— 守护进程据此自动重登续期。
    返回 [{id, engine, credentials(密文)}];browser-service 解密后重跑登录、re-upload 续期。"""
    q = (db.query(EngineSessionORM)
         .filter(EngineSessionORM.status == "quarantined")
         .filter(EngineSessionORM.auth_type == "password")
         .filter(EngineSessionORM.credentials != None))  # noqa: E711
    if engine:
        q = q.filter(EngineSessionORM.engine == engine)
    rows = q.order_by(EngineSessionORM.last_fail_at.asc().nullsfirst()).limit(max(1, min(limit, 100))).all()
    return [{"id": r.id, "engine": r.engine, "credentials": r.credentials,
             "account_handle": r.account_handle} for r in rows]


@router.post("/engine-sessions/check-out", response_model=SessionCheckedOut)
def check_out(
    engine: str,
    worker_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_service_token),
):
    """browser-service 拿一条 active session。

    身份绑定(2026-06):带 worker_id 时优先回该 worker 上次用的那条(sticky lease),
    让账号粘在固定 worker / 出口 IP 上,降低按 IP 风控;自己没有就领一条空闲 / 租约
    过期的并绑给自己;都被别人占着才退回"最少被用"抢一条。不带 worker_id → 老策略。

    基础过滤:active + captcha_count < 阈值 + 未过期。排序:use_count ASC, last_used ASC。
    """
    if engine not in _valid_engines():
        raise HTTPException(400, f"unsupported engine: {engine!r}")

    now = datetime.utcnow()
    today = _local_today()
    cap = _session_daily_cap(engine)

    def _base():
        q = (
            db.query(EngineSessionORM)
            # 行级锁 + 跳过已被其它并发 check-out 锁住的行:消除"两个 worker .first() 拿到
            # 同一条、双重租用 + use_count 漏计"的竞态(Postgres 生效;SQLite 写串行下 no-op)。
            .with_for_update(skip_locked=True)
            .filter(EngineSessionORM.engine == engine)
            .filter(EngineSessionORM.status == "active")
            .filter(EngineSessionORM.captcha_count < _CAPTCHA_QUARANTINE_THRESHOLD)
            .filter((EngineSessionORM.expires_at == None) | (EngineSessionORM.expires_at > now))  # noqa: E711
        )
        # 管理侧"停用"/ 限流冷却中的号排除 —— 让 unschedulable_until / rate_limited_until 真正生效
        q = q.filter(
            (EngineSessionORM.unschedulable_until == None)        # noqa: E711
            | (EngineSessionORM.unschedulable_until <= now)
        ).filter(
            (EngineSessionORM.rate_limited_until == None)         # noqa: E711
            | (EngineSessionORM.rate_limited_until <= now)
        )
        # 单账号每日硬上限:每账号 daily_cap 覆盖引擎默认 cap(coalesce);0=不限。
        # 排除"今天已达上限"的号(used_date!=今天 或 从没用过 → 视为未达上限)。
        eff_cap = func.coalesce(EngineSessionORM.daily_cap, cap)
        q = q.filter(
            (EngineSessionORM.used_date == None)                  # noqa: E711
            | (EngineSessionORM.used_date != today)
            | (eff_cap == 0)
            | (EngineSessionORM.used_today < eff_cap)
        )
        return q

    _least = (EngineSessionORM.use_count.asc(), EngineSessionORM.last_used_at.asc().nullsfirst())

    if worker_id is not None:
        # 0) 显式钉给本 worker 的账号(preferred_worker_id)优先 —— 落实"账号↔固定IP/平台"拓扑
        row = _base().filter(EngineSessionORM.preferred_worker_id == worker_id).order_by(*_least).first()
        # 1) 我上次绑的账号(sticky)
        if row is None:
            row = _base().filter(EngineSessionORM.leased_by_worker_id == worker_id).order_by(*_least).first()
        if row is None:
            # 2) 空闲 / 租约过期的 → 领来绑给我
            row = (_base()
                   .filter((EngineSessionORM.leased_by_worker_id == None)  # noqa: E711
                           | (EngineSessionORM.leased_until == None)       # noqa: E711
                           | (EngineSessionORM.leased_until < now))
                   .order_by(*_least).first())
        if row is None:
            # 3) 都被别人占着 → 退回最少被用,抢一条
            row = _base().order_by(*_least).first()
        if row is not None:
            row.leased_by_worker_id = worker_id
            row.leased_until = now + timedelta(hours=_LEASE_TTL_HOURS)
    else:
        row = _base().order_by(*_least).first()

    if row is None:
        raise HTTPException(404, f"no active session available for engine={engine}")

    # 即刻 +1 use_count + last_used_at,避免并发 check-out 同一条
    row.use_count = (row.use_count or 0) + 1
    row.last_used_at = now
    # 单账号每日计数:跨天归零,否则 +1(精确控制每号每天用量)
    if row.used_date != today:
        row.used_date = today
        row.used_today = 1
    else:
        row.used_today = (row.used_today or 0) + 1
    db.commit()
    db.refresh(row)

    return SessionCheckedOut(
        id=row.id,
        engine=row.engine,
        source_label=row.source_label,
        storage_state=json.loads(row.storage_state),
        use_count=row.use_count,
        egress=row.egress,
    )


@router.post("/engine-sessions/check-in")
def check_in(
    payload: SessionCheckIn,
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_service_token),
):
    """browser-service 报告 session 用完 + 本次 FailureType。

    SUCCESS  → 重置 fail_counts(防止历史失败永远累积)
    CAPTCHA  → captcha_count++,阈值 3 → quarantine
    LOGIN_LOST → 立即 quarantine(session 已失效,不留)
    EMPTY_ANSWER / TIMEOUT → fail_counts[type]++,阈值 5 → quarantine
    DOM_NOT_FOUND → fail_counts[type]++,阈值 3 → quarantine + alert
    CRASH    → skip(不计 session 账,认为是 worker 端问题)

    Backward-compat:旧 worker 仍发 captcha_triggered=true/false,SessionCheckIn
    的 validator 已经把它翻译成 result=CAPTCHA/SUCCESS,这里只看 payload.result.
    """
    row = db.query(EngineSessionORM).get(payload.id)
    if row is None:
        raise HTTPException(404, f"session id={payload.id} not found")

    result = payload.result
    policy = _QUARANTINE_POLICY.get(result, {})

    # 解析现有 fail_counts(SQLite 存 JSON string)
    try:
        fc = json.loads(row.fail_counts_json or "{}")
    except json.JSONDecodeError:
        fc = {}

    if policy.get("reset"):
        # SUCCESS:清空累积失败,但保留 captcha_count(captcha 是独立 counter)
        fc = {}
    elif policy.get("cooldown"):
        # RATE_LIMITED:被风控限流/禁言 → 冷却该号(rate_limited_until),不隔离、不罚 fail_counts。
        # 带了 mute_until(unix 秒)就用它,否则用默认冷却。check_out 会跳过冷却中的号。
        if payload.rate_limited_until:
            row.rate_limited_until = datetime.utcfromtimestamp(payload.rate_limited_until)
        else:
            row.rate_limited_until = datetime.utcnow() + timedelta(seconds=_RATE_LIMIT_COOLDOWN_SEC)
        row.last_fail_type = result.value
        row.last_fail_at = datetime.utcnow()
    elif policy.get("skip"):
        # CRASH:认为是 worker 端问题,不动 session 账
        pass
    elif policy.get("immediate"):
        # LOGIN_LOST:立即 quarantine
        row.status = "quarantined"
        fc[result.value] = fc.get(result.value, 0) + 1
        row.last_fail_type = result.value
        row.last_fail_at = datetime.utcnow()
    else:
        # 累计型:计数 + 达阈值 quarantine
        fc[result.value] = fc.get(result.value, 0) + 1
        row.last_fail_type = result.value
        row.last_fail_at = datetime.utcnow()
        # captcha 用历史独立列,其他用 fail_counts_json
        if policy.get("legacy_col") == "captcha_count":
            row.captcha_count = (row.captcha_count or 0) + 1
            count_for_threshold = row.captcha_count
        else:
            count_for_threshold = fc[result.value]
        threshold = policy.get("threshold")
        if threshold is not None and count_for_threshold >= threshold:
            row.status = "quarantined"

    row.fail_counts_json = json.dumps(fc)

    # 出口 IP 回报(best-effort):worker 按 egress 代理解析到的实际出口 IP
    if payload.exit_ip:
        row.exit_ip = payload.exit_ip
        row.exit_ip_at = datetime.utcnow()

    # 身份绑定(2026-06):check-in 不清租约 —— 让账号继续粘在该 worker/IP 上,
    # 下次同 worker check-out 优先拿回它(sticky)。挂掉的 worker 由 leased_until
    # 到期(_LEASE_TTL_HOURS)自动释放;quarantine / 过期的会被基础过滤排除,租约无害。

    db.commit()
    return {
        "id": row.id,
        "status": row.status,
        "use_count": row.use_count,
        "captcha_count": row.captcha_count,
        "fail_counts": fc,
        "last_fail_type": row.last_fail_type,
    }


@router.get("/engine-sessions/pool-status", response_model=List[PoolStatusEntry])
def pool_status(db: Session = Depends(get_db)):
    """Dashboard 用:每个 engine 当前 active / quarantined / expired 各几条。"""
    now = datetime.utcnow()
    out: List[PoolStatusEntry] = []
    for engine in sorted(_valid_engines()):
        rows = db.query(EngineSessionORM).filter(EngineSessionORM.engine == engine).all()
        active = sum(1 for r in rows if r.status == "active" and (r.expires_at is None or r.expires_at > now))
        quarantined = sum(1 for r in rows if r.status == "quarantined")
        expired = sum(1 for r in rows if r.expires_at is not None and r.expires_at <= now)
        oldest_active = (
            db.query(func.min(EngineSessionORM.captured_at))
            .filter(EngineSessionORM.engine == engine)
            .filter(EngineSessionORM.status == "active")
            .scalar()
        )
        out.append(PoolStatusEntry(
            engine=engine,
            active=active,
            quarantined=quarantined,
            expired=expired,
            oldest_active_captured_at=oldest_active,
        ))
    return out
