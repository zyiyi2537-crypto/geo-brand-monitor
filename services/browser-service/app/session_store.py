"""Session persistence for browser engine adapters.

Stores and retrieves full Playwright storage_state (cookies + localStorage)
per-engine so sessions survive across runs without requiring re-login.

Playwright storage_state format:
{
  "cookies": [...],
  "origins": [
    {
      "origin": "https://chat.deepseek.com",
      "localStorage": [{"name": "key", "value": "val"}, ...]
    }
  ]
}

**Pool mode (2026-05-18+)**:
  当配置了 ENGINE_SESSION_POOL_URL + ENGINE_SESSION_SERVICE_TOKEN 时,
  `load_storage_state(engine)` 优先从中央 pool check-out 一条 active session
  (`POST {url}/api/engine-sessions/check-out?engine=<engine>`),失败再退化到
  本地文件。check-out 返回的 session_id 由 `report_session_outcome(engine, ok)`
  通过 `POST .../check-in` 报回去 — 没挑 CAPTCHA → noop;挑了 → captcha_count
  +1, 达阈值自动 quarantine。

  对外接口不变(load_storage_state 还是返回 dict),所以 engine adapters
  不用改;但每个 adapter 应该在 search 结束时调一次
  `report_session_outcome(engine_name, captcha_triggered)` 让 pool 学习。
"""

from __future__ import annotations

import json
import logging
import locale
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import Lock
from uuid import uuid4
from threading import local as _thread_local
from typing import Optional

import httpx


_log = logging.getLogger(__name__)


_SESSION_DIR = Path(os.environ.get(
    "BROWSER_SESSION_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data", "browser_sessions"),
))

# Pool config — 未设置就关闭 pool 模式,行为跟以前 100% 一致(只读本地文件)
_POOL_URL = (os.environ.get("ENGINE_SESSION_POOL_URL") or "").rstrip("/")
_POOL_TOKEN = (os.environ.get("ENGINE_SESSION_SERVICE_TOKEN") or "").strip()
_POOL_HTTP_TIMEOUT = float(os.environ.get("ENGINE_SESSION_POOL_TIMEOUT", "5"))

# 身份绑定:check-out 时带本 worker 的稳定 id(由 WORKER_UID crc32),池子据此
# 把账号"粘"在固定 worker/出口 IP 上(sticky lease),降低 deepseek 等按 IP 风控。
# 未设 WORKER_UID(如手动调用)→ None,池子退回"最少被用"老策略。
import zlib as _zlib
_uid = (os.environ.get("WORKER_UID") or "").strip()
_WORKER_POOL_ID = (_zlib.crc32(_uid.encode("utf-8")) & 0x7FFFFFFF) if _uid else None

# 记录最近一次 check-out 的 session_id,供 report_session_outcome 用。
# 用 thread-local 是因为 browser-service 是 thread-pool 模型,每个并发 search
# 在自己的 thread 里。AsyncIO 单进程下也成立 — Playwright async 不会在
# load_storage_state ↔ report_session_outcome 之间切线程。
_last_checkout: _thread_local = _thread_local()
_LOCAL_LOCK = Lock()
_FORCED_LOCAL_ACCOUNT: ContextVar[tuple[str, str] | None] = ContextVar(
    "forced_local_account", default=None
)
_ACCOUNT_INDEX_PATH = _SESSION_DIR / "accounts.json"
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")

# Local account cooldowns prevent a challenged or expired account from being
# selected again on the next question. A login-lost account needs a fresh login.
_LOCAL_COOLDOWN_SECONDS = {
    "captcha": 30 * 60,
    "rate_limited": 60 * 60,
    "empty_answer": 2 * 60,
    "timeout": 60,
    "crash": 60,
}


def _ensure_dir() -> None:
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _read_session_json(path: Path):
    """Read current UTF-8 states and legacy Windows-codepage session files."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode(locale.getpreferredencoding(False))
    return json.loads(text)


def _account_id(account_id: str) -> str:
    account_id = str(account_id or "").strip()
    if not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise ValueError("账号编号只能包含英文字母、数字、下划线和连字符")
    return account_id


def _account_path(engine_name: str, account_id: str) -> Path:
    account_id = _account_id(account_id)
    if account_id == "default":
        return _SESSION_DIR / f"{engine_name}.json"
    return _SESSION_DIR / f"{engine_name}__{account_id}.json"


def _read_account_index() -> dict:
    try:
        data = json.loads(_ACCOUNT_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("engines"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "engines": {}}


def _write_account_index(data: dict) -> None:
    _ensure_dir()
    pending = _ACCOUNT_INDEX_PATH.with_name(f"accounts.{uuid4().hex}.tmp")
    try:
        pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(pending, _ACCOUNT_INDEX_PATH)
    finally:
        pending.unlink(missing_ok=True)


def _account_paths(engine_name: str) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    legacy = _SESSION_DIR / f"{engine_name}.json"
    if legacy.is_file():
        paths["default"] = legacy
    prefix = f"{engine_name}__"
    for path in _SESSION_DIR.glob(f"{engine_name}__*.json"):
        account_id = path.stem[len(prefix):]
        if _ACCOUNT_ID_RE.fullmatch(account_id) and account_id != "default":
            paths[account_id] = path
    return paths


def list_local_accounts(engine_name: str) -> list[dict]:
    """Return local account metadata without loading or leasing a session."""
    with _LOCAL_LOCK:
        index = _read_account_index()
        records = index.setdefault("engines", {}).setdefault(engine_name, {})
        paths = _account_paths(engine_name)
        if "default" in paths and "default" not in records:
            records["default"] = {"label": "默认账号", "status": "active"}
            _write_account_index(index)
        account_ids = set(records) | set(paths)
        result = []
        now = time.time()
        for account_id in sorted(account_ids, key=lambda value: (value != "default", value)):
            if not _ACCOUNT_ID_RE.fullmatch(account_id):
                continue
            record = records.get(account_id) or {}
            cooldown_until = float(record.get("cooldown_until") or 0)
            status = record.get("status", "active" if account_id in paths else "pending")
            if cooldown_until > now and status == "active":
                display_status = "cooldown"
            elif account_id not in paths and status == "active":
                display_status = "missing"
            else:
                display_status = status
            result.append({
                "engine": engine_name,
                "account_id": account_id,
                "label": record.get("label") or ("默认账号" if account_id == "default" else account_id),
                "status": display_status,
                "cooldown_until": cooldown_until,
                "use_count": int(record.get("use_count") or 0),
                "failure_count": int(record.get("failure_count") or 0),
                "exists": account_id in paths,
            })
        return result


def create_local_account(engine_name: str, label: str) -> dict:
    """Reserve a new local account identifier for a manual login window."""
    label = str(label or "").strip()
    if not label:
        raise ValueError("请填写账号名称")
    with _LOCAL_LOCK:
        index = _read_account_index()
        records = index.setdefault("engines", {}).setdefault(engine_name, {})
        used = set(records) | set(_account_paths(engine_name))
        number = 1
        while f"acct-{number:03d}" in used:
            number += 1
        account_id = f"acct-{number:03d}"
        records[account_id] = {
            "label": label,
            "status": "pending",
            "use_count": 0,
            "failure_count": 0,
            "cooldown_until": 0,
        }
        _write_account_index(index)
        return {"engine": engine_name, "account_id": account_id, "label": label,
                "status": "pending", "exists": False, "use_count": 0,
                "failure_count": 0, "cooldown_until": 0}


def delete_local_account(engine_name: str, account_id: str) -> None:
    account_id = _account_id(account_id)
    with _LOCAL_LOCK:
        _account_path(engine_name, account_id).unlink(missing_ok=True)
        index = _read_account_index()
        records = index.setdefault("engines", {}).setdefault(engine_name, {})
        records.pop(account_id, None)
        _write_account_index(index)


@contextmanager
def use_local_account(engine_name: str, account_id: str):
    """Pin session loading to one account while verifying it."""
    token = _FORCED_LOCAL_ACCOUNT.set((engine_name, _account_id(account_id)))
    try:
        yield
    finally:
        _FORCED_LOCAL_ACCOUNT.reset(token)


def _read_local_state(path: Path) -> Optional[dict]:
    try:
        data = _read_session_json(path)
        if isinstance(data, dict) and "cookies" in data:
            return _normalize_storage_state(data)
        if isinstance(data, list):
            return {"cookies": data, "origins": []}
    except (json.JSONDecodeError, OSError, UnicodeError):
        return None
    return None


def _local_checkout(engine_name: str, account_id: str | None = None) -> Optional[dict]:
    """Load a local account, choosing the least recently used active account."""
    with _LOCAL_LOCK:
        paths = _account_paths(engine_name)
        if account_id is not None:
            path = paths.get(_account_id(account_id))
            state = _read_local_state(path) if path else None
            if state is not None:
                slots = getattr(_last_checkout, "local_by_engine", None)
                if slots is None:
                    slots = {}
                    _last_checkout.local_by_engine = slots
                slots[engine_name] = account_id
            return state

        index = _read_account_index()
        records = index.setdefault("engines", {}).setdefault(engine_name, {})
        now = time.time()
        candidates = []
        for candidate_id, path in paths.items():
            record = records.get(candidate_id) or {}
            if record.get("status") in {"disabled", "needs_login", "invalid_file"}:
                continue
            if float(record.get("cooldown_until") or 0) > now:
                continue
            candidates.append((float(record.get("last_used_at") or 0), candidate_id != "default",
                               candidate_id, path))
        for _last_used, _not_default, candidate_id, path in sorted(candidates):
            state = _read_local_state(path)
            if state is None:
                records.setdefault(candidate_id, {})["status"] = "invalid_file"
                continue
            record = records.setdefault(candidate_id, {})
            record.setdefault("label", "默认账号" if candidate_id == "default" else candidate_id)
            record["status"] = "active"
            record["use_count"] = int(record.get("use_count") or 0) + 1
            record["last_used_at"] = now
            _write_account_index(index)
            slots = getattr(_last_checkout, "local_by_engine", None)
            if slots is None:
                slots = {}
                _last_checkout.local_by_engine = slots
            slots[engine_name] = candidate_id
            _log.info("[local-session-pool] engine=%s account=%s use_count=%s",
                      engine_name, candidate_id, record["use_count"])
            return state
        _write_account_index(index)
        if paths:
            _log.warning("[local-session-pool] engine=%s has no account outside cooldown or login-required state",
                         engine_name)
        return None


def get_local_account_count(engine_name: str) -> int:
    now = time.time()
    accounts = list_local_accounts(engine_name)
    return sum(1 for item in accounts if item["exists"]
               and item["status"] not in {"disabled", "needs_login", "invalid_file", "missing", "pending"}
               and item["cooldown_until"] <= now)


def has_local_accounts(engine_name: str) -> bool:
    return bool(_account_paths(engine_name))


def get_last_local_account_id(engine_name: str) -> str | None:
    slots = getattr(_last_checkout, "local_by_engine", None) or {}
    return slots.get(engine_name)


def is_local_account_available(engine_name: str, account_id: str | None) -> bool:
    if not account_id:
        return False
    account_id = _account_id(account_id)
    with _LOCAL_LOCK:
        if account_id not in _account_paths(engine_name):
            return False
        record = (_read_account_index().get("engines", {}).get(engine_name, {}).get(account_id) or {})
        return (record.get("status", "active") not in {"disabled", "needs_login", "invalid_file"}
                and float(record.get("cooldown_until") or 0) <= time.time())


def set_local_account_result(engine_name: str, account_id: str, result: str) -> None:
    """Record an explicit account verification result."""
    account_id = _account_id(account_id)
    with _LOCAL_LOCK:
        index = _read_account_index()
        record = index.setdefault("engines", {}).setdefault(engine_name, {}).setdefault(account_id, {})
        now = time.time()
        if result == "success":
            record["status"] = "active"
            record["cooldown_until"] = 0
        elif result in {"login_lost", "invalid_file"}:
            record["status"] = "needs_login"
            record["cooldown_until"] = 0
            record["failure_count"] = int(record.get("failure_count") or 0) + 1
        elif result == "challenge":
            record["status"] = "active"
            record["cooldown_until"] = now + _LOCAL_COOLDOWN_SECONDS["captcha"]
            record["failure_count"] = int(record.get("failure_count") or 0) + 1
        else:
            return
        record["last_result"] = result
        record["last_result_at"] = now
        _write_account_index(index)


# ── Pool client ─────────────────────────────────────────────────────


def _pool_enabled() -> bool:
    return bool(_POOL_URL and _POOL_TOKEN)


def _normalize_storage_state(state: Optional[dict]) -> Optional[dict]:
    """把 origins[].localStorage / sessionStorage 从对象 {k:v} 归一化成 Playwright 要求的
    数组 [{name,value}]。扩展导出的登录态常是 JS 原生对象格式,不归一化时 new_context 会报
    `storageState.origins[0].localStorage: expected array, got object`,导致整条引擎热会话起不来。
    防御性:已坏的会话加载即修,无需重新上传账号。"""
    if not isinstance(state, dict):
        return state
    for origin in state.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        for key in ("localStorage", "sessionStorage"):
            v = origin.get(key)
            if isinstance(v, dict):
                origin[key] = [{"name": str(k), "value": "" if val is None else str(val)}
                               for k, val in v.items()]
    return state


def _pool_checkout(engine_name: str) -> Optional[dict]:
    """Try to fetch a session from central pool. Returns storage_state dict or None.

    On success, stashes (engine, id) in thread-local so report_session_outcome
    knows which row to update.
    """
    if not _pool_enabled():
        return None
    try:
        params = {"engine": engine_name}
        if _WORKER_POOL_ID is not None:
            params["worker_id"] = _WORKER_POOL_ID
        with httpx.Client(timeout=_POOL_HTTP_TIMEOUT) as client:
            r = client.post(
                f"{_POOL_URL}/api/engine-sessions/check-out",
                params=params,
                headers={"X-Service-Token": _POOL_TOKEN},
            )
        if r.status_code == 404:
            _log.info("[session-pool] engine=%s: pool empty, fallback to local file", engine_name)
            return None
        if r.status_code != 200:
            _log.warning("[session-pool] engine=%s: check-out HTTP %d: %s",
                         engine_name, r.status_code, r.text[:200])
            return None
        data = r.json()
        sid = data.get("id")
        state = data.get("storage_state") or {}
        # Stash for later check-in (one slot per engine in thread-local)
        slots = getattr(_last_checkout, "by_engine", None)
        if slots is None:
            slots = {}
            _last_checkout.by_engine = slots
        slots[engine_name] = sid
        # 出口标记(egress):None=按引擎默认 / 'proxy'=走代理 / 'host'=本机IP
        egslots = getattr(_last_checkout, "egress_by_engine", None)
        if egslots is None:
            egslots = {}
            _last_checkout.egress_by_engine = egslots
        egslots[engine_name] = data.get("egress")
        _log.info("[session-pool] engine=%s: checked out id=%s use_count=%s egress=%s source=%r",
                  engine_name, sid, data.get("use_count"), data.get("egress"), data.get("source_label"))
        return _normalize_storage_state(state)
    except Exception as e:
        _log.warning("[session-pool] engine=%s: check-out failed: %s", engine_name, e)
        return None


# D2(2026-05-18):check-in 升级为 enum FailureType 上报,后端按类型应用不同
# quarantine 政策。旧调用点 `report_session_outcome(engine, captcha_triggered=bool)`
# 被翻译成 SUCCESS / CAPTCHA。新调用建议直接传 result 字符串。
_VALID_RESULTS = {
    "success", "captcha", "empty_answer", "login_lost",
    "dom_not_found", "timeout", "crash", "rate_limited",
}


def report_session_outcome(
    engine_name: str,
    captcha_triggered: bool | None = None,
    *,
    result: str | None = None,
    error_msg: str | None = None,
    rate_limited_until: float | None = None,
    exit_ip: str | None = None,
) -> None:
    """Notify pool that the session we just checked out was used.

    Two equivalent calling styles:
      - 旧: report_session_outcome("doubao", captcha_triggered=True)
            → 翻译成 result="captcha"
      - 新: report_session_outcome("doubao", result="empty_answer",
                                    error_msg="answer was empty after 60s")

    No-op if pool isn't configured or no check-out was recorded for this engine
    in the current thread (e.g. we fell back to file). Safe to call always.
    """
    local_slots = getattr(_last_checkout, "local_by_engine", None) or {}
    local_account_id = local_slots.pop(engine_name, None)
    if result is None:
        result = "captcha" if captcha_triggered is True else "success"
    if local_account_id is not None:
        with _LOCAL_LOCK:
            index = _read_account_index()
            record = (index.setdefault("engines", {}).setdefault(engine_name, {})
                      .setdefault(local_account_id, {}))
            now = time.time()
            if result == "success":
                record["status"] = "active"
                record["cooldown_until"] = 0
            elif result in {"login_lost", "invalid_file"}:
                record["status"] = "needs_login"
                record["cooldown_until"] = 0
                record["failure_count"] = int(record.get("failure_count") or 0) + 1
            else:
                record["status"] = "active"
                record["cooldown_until"] = now + _LOCAL_COOLDOWN_SECONDS.get(result, 60)
                record["failure_count"] = int(record.get("failure_count") or 0) + 1
            record["last_result"] = result
            record["last_result_at"] = now
            _write_account_index(index)
        _log.info("[local-session-pool] engine=%s account=%s result=%s cooldown_until=%s",
                  engine_name, local_account_id, result, record.get("cooldown_until"))

    if not _pool_enabled():
        return
    slots = getattr(_last_checkout, "by_engine", None) or {}
    sid = slots.pop(engine_name, None)
    if sid is None:
        return

    # 调用点签名翻译
    if result not in _VALID_RESULTS:
        _log.warning("[session-pool] engine=%s: invalid result=%r, downgrading to 'crash'",
                     engine_name, result)
        result = "crash"

    body = {"id": sid, "result": result}
    if error_msg:
        body["error_msg"] = error_msg[:500]  # 截断防爆 log
    if rate_limited_until is not None:
        body["rate_limited_until"] = rate_limited_until  # 风控冷却到期(如 deepseek mute_until)
    if exit_ip:
        body["exit_ip"] = exit_ip  # 实际出口 IP(按 egress 代理解析)
    try:
        with httpx.Client(timeout=_POOL_HTTP_TIMEOUT) as client:
            r = client.post(
                f"{_POOL_URL}/api/engine-sessions/check-in",
                headers={"X-Service-Token": _POOL_TOKEN, "Content-Type": "application/json"},
                json=body,
            )
        if r.status_code != 200:
            _log.warning("[session-pool] engine=%s: check-in HTTP %d: %s",
                         engine_name, r.status_code, r.text[:200])
        else:
            _log.info("[session-pool] engine=%s id=%s checked in (result=%s) → %s",
                      engine_name, sid, result, r.json())
    except Exception as e:
        _log.warning("[session-pool] engine=%s: check-in failed: %s", engine_name, e)


def get_last_checkout_id(engine_name: str):
    """返回当前线程上次 check-out 的 session id;按账号粘定代理(sticky)时用作 session 标识。
    没从池子 check-out(走本地文件兜底)时返回 None。"""
    slots = getattr(_last_checkout, "by_engine", None) or {}
    return slots.get(engine_name)


def get_last_egress(engine_name: str):
    """返回当前线程上次 check-out 的出口标记:None=按引擎默认 / 'proxy' / 'host'。"""
    slots = getattr(_last_checkout, "egress_by_engine", None) or {}
    return slots.get(engine_name)


def save_storage_state(engine_name: str, storage_state: dict, account_id: str | None = None) -> None:
    """Persist full storage_state atomically so interruption cannot truncate it."""
    if not isinstance(storage_state, dict):
        raise ValueError("storage_state 必须是对象")
    serialized = json.dumps(storage_state, ensure_ascii=False, indent=2)
    _ensure_dir()
    if account_id is None:
        forced = _FORCED_LOCAL_ACCOUNT.get()
        if forced and forced[0] == engine_name:
            account_id = forced[1]
        else:
            slots = getattr(_last_checkout, "local_by_engine", None) or {}
            account_id = slots.get(engine_name)
    account_id = account_id or "default"
    path = _account_path(engine_name, account_id)
    pending = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        pending.write_text(serialized, encoding="utf-8")
        json.loads(pending.read_text(encoding="utf-8"))
        os.replace(pending, path)
        with _LOCAL_LOCK:
            index = _read_account_index()
            record = index.setdefault("engines", {}).setdefault(engine_name, {}).setdefault(account_id, {})
            record.setdefault("label", "默认账号" if account_id == "default" else account_id)
            record["status"] = "active"
            record["cooldown_until"] = 0
            record.setdefault("use_count", 0)
            _write_account_index(index)
    finally:
        pending.unlink(missing_ok=True)


def load_storage_state(engine_name: str) -> Optional[dict]:
    """Load storage_state.

    优先级:
      1. 中央 pool(配了 ENGINE_SESSION_POOL_URL + token 才启用)
      2. 本地文件(legacy / pool 空 / pool 不可达 时兜底)

    Handles both new format (full storage_state with origins) and legacy
    format (plain cookie list) for backward compatibility.
    """
    forced = _FORCED_LOCAL_ACCOUNT.get()
    forced_id = forced[1] if forced and forced[0] == engine_name else None
    if forced_id is not None:
        return _local_checkout(engine_name, forced_id)

    # Path 1: central pool
    pooled = _pool_checkout(engine_name)
    if pooled is not None:
        return pooled

    # Path 2: local account pool. A forced account is used by verification and
    # manual recovery; normal requests choose least recently used active account.
    local = _local_checkout(engine_name, forced_id)
    if local is None and forced_id is None and has_local_accounts(engine_name):
        raise RuntimeError(f"{engine_name} 的本地账号都在冷却或需要重新登录，请稍后再试")
    return local


def peek_session_exists(engine_name: str) -> bool:
    """只读探测某引擎本地是否有登录态文件 —— **绝不 check-out**。

    给 `/sessions` 这类状态/健康查询用:`load_storage_state` 在 pool 模式下第一步
    就 `_pool_checkout`(租账号 + use_count++),而状态查询不会 check-in →
    每次轮询都泄漏一个租约、白烧当日配额。状态查询只该读不该租,故走本函数。

    返回的是"本机有无登录态文件"这个无副作用的存活信号;pool 模式下账号可用性的
    权威视图在中心的 /admin/engine-sessions(那边才反映池子真实状态)。
    """
    return bool(_account_paths(engine_name))


def clear_session(engine_name: str) -> None:
    """Remove saved session for the given engine."""
    with _LOCAL_LOCK:
        for path in _account_paths(engine_name).values():
            path.unlink(missing_ok=True)
        index = _read_account_index()
        index.setdefault("engines", {}).pop(engine_name, None)
        _write_account_index(index)


# Backward-compatible aliases
def load_cookies(engine_name: str) -> Optional[list]:
    """Load cookies only (backward compat). Returns cookie list or None."""
    state = load_storage_state(engine_name)
    if state:
        return state.get("cookies")
    return None


def save_cookies(engine_name: str, cookies: list) -> None:
    """Save cookies only (backward compat). Preserves existing localStorage."""
    existing = load_storage_state(engine_name) or {}
    existing["cookies"] = cookies
    if "origins" not in existing:
        existing["origins"] = []
    save_storage_state(engine_name, existing)


# ── Profile persistence (for cross-machine fingerprint consistency) ──


def save_engine_profile(engine_name: str, profile: dict) -> None:
    """Save fingerprint profile alongside storage_state for cross-machine reuse.

    CF-gated engines (ChatGPT / Gemini / Grok) require the same UA/platform
    profile at login time and runtime. The profile dict is saved next to the
    storage_state JSON so they can be uploaded together.
    """
    _ensure_dir()
    path = _SESSION_DIR / f"{engine_name}_profile.json"
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False))


def load_engine_profile(engine_name: str) -> Optional[dict]:
    """Load previously saved fingerprint profile, or None if not found."""
    path = _SESSION_DIR / f"{engine_name}_profile.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
