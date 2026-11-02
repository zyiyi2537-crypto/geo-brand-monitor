"""Engine session pool — centralized Playwright storage_state storage.

每条记录 = 一个用户在一台机器上对某个 engine 完成的一次完整登录所产生的
完整 storage_state(cookies + localStorage + sessionStorage 全量)。
browser-service 从 pool 里 check-out 最少被用的一条,替换本地文件,
跑完 search 后 check-in 回报具体的 FailureType.

D1 schema 已扩展:fail_counts_json / lease / region / preferred_worker_id
(参见 backend/alembic/versions/a1b2c3d4e5f6_scheduler_p1_p3_p4.py)。

D2(本文件)实现 P1 — 失败信号 enum 化 + 各类型对应的 quarantine 策略。
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from geo.database import Base


class EngineSessionORM(Base):
    __tablename__ = "engine_sessions"
    __table_args__ = (
        Index("idx_engine_sessions_pool", "engine", "status", "captcha_count", "last_used_at"),
        Index("idx_sessions_lease", "engine", "status", "leased_until"),
        Index("idx_sessions_region", "engine", "status", "captured_from_region"),
        Index("idx_sessions_account", "engine", "account_id"),
    )

    id = Column(Integer, primary_key=True)
    engine = Column(String, nullable=False, index=True)            # doubao/qwen/deepseek/wenxin/yuanbao
    source_label = Column(String, nullable=True)                   # "alice-mac", "bob-win-laptop", ...
    # 账号身份(2026-06):从 storage_state 提取的稳定用户标识哈希
    # (格式 "<字段名>:<sha256前16>",见 extract_account_id);upsert 优先按它匹配
    account_id = Column(String, nullable=True)
    account_handle = Column(String, nullable=True)                 # 昵称/掩码手机号,纯展示
    storage_state = Column(Text, nullable=False)                   # JSON 字符串
    user_agent = Column(String, nullable=True)
    platform = Column(String, nullable=True)                       # "MacIntel" / "Linux x86_64" / ...
    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, nullable=False, default=0)
    captcha_count = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="active")      # active / quarantined / expired
    expires_at = Column(DateTime, nullable=True)

    # P1 失败信号(D2)
    last_fail_type = Column(String, nullable=True)
    last_fail_at = Column(DateTime, nullable=True)
    fail_counts_json = Column(Text, nullable=False, default="{}")

    # P3 lease + region affinity(D2 schema 已加,逻辑在 D4 落)
    leased_by_worker_id = Column(Integer, nullable=True)
    leased_until = Column(DateTime, nullable=True)
    captured_from_region = Column(String, nullable=True)
    captured_from_ip = Column(String, nullable=True)
    preferred_worker_id = Column(Integer, nullable=True)

    # 精确用量控制(2026-06):单账号每日 check-out 硬上限 + 出口 IP 绑定
    used_today = Column(Integer, nullable=False, default=0)   # 当天 check-out 次数(跨 used_date 自动归零)
    used_date = Column(String, nullable=True)                 # 'YYYY-MM-DD'(本地日);与 used_today 配套
    egress = Column(String, nullable=True)                    # None=按引擎默认(PROXY_ENGINES) / 'proxy'=走代理 / 'host'=本机IP
    daily_cap = Column(Integer, nullable=True)               # 单账号日上限覆盖;None=用 env 默认,0=不限
    exit_ip = Column(String, nullable=True)                  # 该账号实际出口 IP(check-in 时由 worker 解析回报)
    exit_ip_at = Column(DateTime, nullable=True)             # 出口 IP 最近一次解析时间

    # 授权方式 + 调度状态机(2026-06,对标 Sub2API)
    auth_type = Column(String, nullable=True)                 # password / apikey / qr / cookie;None=未知
    credentials = Column(Text, nullable=True)                 # AES 加密的 JSON 凭证(密码/key),供掉线自动续期
    rate_limited_until = Column(DateTime, nullable=True)      # 限流冷却到期(收到 429 后设)
    unschedulable_until = Column(DateTime, nullable=True)     # 临时不可调度到期(换号/维护中)
    priority = Column(Integer, nullable=False, default=50)    # 调度优先级,低值优先
    concurrency = Column(Integer, nullable=False, default=1)  # 单账号最大并发


# ── 账号身份提取(2026-06)────────────────────────────────────────
#
# 目标:同一个真实账号重新登录/重新上传时,能认出"这是老账号"去续期,
# 而不是落新行。靠 storage_state 里跨重新登录稳定的用户标识:
#
#   doubao   cookie uid_tt / uid_tt_ss(字节 passport 加密 uid)
#   qwen     cookie login_aliyunid_pk(阿里账号 PK);chat.qwen.ai 的 JWT token
#   yuanbao  cookie hy_user(腾讯混元用户 id)
#   deepseek localStorage userToken(若为 JWT 取 payload 用户字段)
#   wenxin   百度无明文 uid cookie(BDUSS 每次登录会变),走通用探测,
#            探不到 → upload 退回按 source_label 匹配
#
# 候选字段未经全量验证(用 scripts/scan_session_identity.py 扫现库校准);
# 提取错/提取不到的最坏结果只是退化回 label 匹配,不会把两个账号错并 ——
# 因为 account_id 带字段名前缀 + 值哈希,不同来源/不同值永不相等。

_IDENTITY_COOKIES: dict[str, tuple[str, ...]] = {
    "doubao":  ("uid_tt", "uid_tt_ss"),
    "qwen":    ("login_aliyunid_pk",),
    "yuanbao": ("hy_user",),
}

# JWT 形态 token 的常见存放 key(cookie 或 localStorage)
_TOKEN_KEYS = ("token", "userToken", "access_token")

# 用户对象 / JWT payload 里认作"用户 id"的字段,按优先级
_USER_ID_FIELDS = ("user_id", "userId", "uid", "sub", "openid", "open_id",
                   "account_id", "accountId", "id")


def _account_hash(field: str, value: str) -> str:
    """account_id 格式:"<来源字段>:<sha256前16>" — 不落明文,带来源可追溯。"""
    return f"{field}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def _jwt_user_claim(token: str) -> Optional[str]:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        pad = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(pad))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    for f in _USER_ID_FIELDS:
        v = payload.get(f)
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v)
    return None


def extract_account_id(engine: str, storage_state: dict) -> Optional[str]:
    """从 storage_state 提取稳定账号标识;提不到返回 None(调用方退回 label)。"""
    cookies = {c.get("name"): c.get("value")
               for c in (storage_state.get("cookies") or [])
               if c.get("name") and c.get("value")}
    ls: dict[str, str] = {}
    for o in storage_state.get("origins") or []:
        for item in o.get("localStorage") or []:
            if item.get("name") and item.get("value"):
                ls.setdefault(item["name"], item["value"])

    # 1) 引擎已知的稳定身份 cookie
    for name in _IDENTITY_COOKIES.get(engine, ()):
        v = cookies.get(name)
        if v:
            return _account_hash(f"cookie.{name}", v)

    # 2) JWT 形态 token → payload 里的用户字段(跨登录稳定,token 本身会变)
    for key in _TOKEN_KEYS:
        for src, store in (("ls", ls), ("cookie", cookies)):
            raw = store.get(key) or ""
            if raw.lstrip().startswith("{"):
                # localStorage 常见 {"value": "...", "__expires": ...} 包一层
                try:
                    raw = (json.loads(raw) or {}).get("value") or ""
                except Exception:
                    raw = ""
            claim = _jwt_user_claim(raw) if raw else None
            if claim:
                return _account_hash(f"{src}.{key}.jwt", claim)

    # 3) localStorage 里的用户信息 JSON({"userId": ...} 之类)
    for key, obj in _user_objects(ls):
        for f in _USER_ID_FIELDS:
            v = obj.get(f)
            if isinstance(v, (str, int)) and str(v).strip():
                return _account_hash(f"ls.{key}.{f}", str(v))

    return None


_HANDLE_FIELDS = ("nickname", "nickName", "nick", "screen_name", "userName",
                  "username", "name", "mobile", "phone", "email")


def _user_objects(ls: dict[str, str]):
    """localStorage 里 key 含 user/account 且值为 JSON object 的项,按 key 排序。"""
    for key in sorted(ls):
        if "user" not in key.lower() and "account" not in key.lower():
            continue
        raw = ls[key]
        if not raw.lstrip().startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            yield key, obj


def extract_account_handle(engine: str, storage_state: dict) -> Optional[str]:
    """从 localStorage 用户信息里挖昵称/手机号当展示名;采集端没传 handle 时兜底。"""
    ls: dict[str, str] = {}
    for o in storage_state.get("origins") or []:
        for item in o.get("localStorage") or []:
            if item.get("name") and item.get("value"):
                ls.setdefault(item["name"], item["value"])
    for _key, obj in _user_objects(ls):
        for f in _HANDLE_FIELDS:
            v = obj.get(f)
            if isinstance(v, (str, int)) and str(v).strip():
                return str(v).strip()[:64]
    return None


class FailureType(str, Enum):
    """check-in 时 worker 上报的本次使用结果.

    每个 type 有独立的 quarantine 政策(见 engine_sessions.py 的 _QUARANTINE_POLICY).
    """
    SUCCESS = "success"
    CAPTCHA = "captcha"
    EMPTY_ANSWER = "empty_answer"      # 返回空字符串,可能 UI 改版或 session 半失效
    LOGIN_LOST = "login_lost"          # 跳登录页 / 强制重登,session 彻底失效
    DOM_NOT_FOUND = "dom_not_found"    # 关键 selector 找不到,可能引擎改版
    TIMEOUT = "timeout"                # streaming 超过 max_wait
    CRASH = "crash"                    # 异常抛出,不计 session 账
    RATE_LIMITED = "rate_limited"      # 被引擎风控限流/禁言(deepseek "user is muted")→ 冷却到 mute_until,不罚号


# ── Pydantic schemas ───────────────────────────────────────────────


class SessionUploadIn(BaseModel):
    engine: str = Field(..., description="doubao/qwen/deepseek/wenxin/yuanbao")
    storage_state: dict = Field(..., description="Playwright storage_state full JSON")
    source_label: Optional[str] = Field(None, description="who+device, e.g. 'alice-mac'")
    account_handle: Optional[str] = Field(None, description="采集端抓的昵称/掩码手机号,纯展示")
    user_agent: Optional[str] = None
    platform: Optional[str] = None
    ttl_days: int = Field(7, ge=1, le=30, description="过期天数,默认 7,最多 30")
    auth_type: Optional[str] = Field(None, description="password/apikey/qr/cookie")
    credentials: Optional[str] = Field(None, description="AES 加密的凭证 JSON(供自动续期),不解密只存")


class SessionCheckedOut(BaseModel):
    """Returned to browser-service for use in a single /search call."""
    id: int
    engine: str
    source_label: Optional[str]
    storage_state: dict
    use_count: int
    egress: Optional[str] = None   # None=按引擎默认 / 'proxy'=走代理 / 'host'=本机IP;browser-service 据此决定出口


class SessionCheckIn(BaseModel):
    """check-in payload.

    New shape (D2+):
      {"id": 7, "result": "success" | "captcha" | ..., "error_msg": "..." | null}

    Backward-compat:旧 worker 仍发 {"id": 7, "captcha_triggered": true/false},
    自动翻译成 result=CAPTCHA / SUCCESS。允许过渡期 vm03 还没升级。
    """
    id: int
    result: FailureType = FailureType.SUCCESS
    error_msg: Optional[str] = None
    exit_ip: Optional[str] = None   # worker 按 egress 代理解析到的实际出口 IP(best-effort)
    rate_limited_until: Optional[float] = None  # RATE_LIMITED 时的冷却到期(unix 秒,如 deepseek mute_until)
    # 旧字段:不出现在新 API,只用于 deserialize 旧 worker payload
    captcha_triggered: Optional[bool] = None

    @model_validator(mode="after")
    def _translate_legacy(self) -> "SessionCheckIn":
        # 旧 worker 没设 result(默认 SUCCESS)但设了 captcha_triggered=true
        # → 视为 CAPTCHA。新 worker 用 result,captcha_triggered 不传。
        if self.captcha_triggered is True and self.result == FailureType.SUCCESS:
            self.result = FailureType.CAPTCHA
        return self


class PoolStatusEntry(BaseModel):
    engine: str
    active: int
    quarantined: int
    expired: int
    oldest_active_captured_at: Optional[datetime]
