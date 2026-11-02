"""embed token —— 1 年期账号 token 的签发与校验(agent integration API)。

- 独立签名密钥 `AGENT_EMBED_SECRET`(未配则从主 SECRET_KEY 派生),`aud="agent-embed"` 与登录 JWT 硬隔离。
- 载荷:iss / aud / sub(=account_id)/ tid / caps / iat / exp。
- 校验**必查 agent_tokens.enabled**(长期 token 的吊销命门),不能纯无状态。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from jwt import PyJWTError as JWTError
from sqlalchemy.orm import Session

from geo.database import settings
from geo.models.agent import AgentTokenORM

ALGORITHM = "HS256"
ISSUER = "vigilath-agent"
AUDIENCE = "agent-embed"


def _secret() -> str:
    # 独立密钥;未单独配置时从主 SECRET_KEY 派生一个不同值(仍靠 aud 硬隔离)。
    return (os.environ.get("AGENT_EMBED_SECRET") or "").strip() or f"{settings.SECRET_KEY}::agent-embed"


class EmbedAuthError(Exception):
    """对外 token 校验失败。code 直接映射 HTTP 状态。"""

    def __init__(self, code: int, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass
class EmbedClaims:
    account_id: int
    caps: list[str]
    tid: str
    origins: list[str]


def _parse_caps(raw: str | None) -> list[str]:
    return [c.strip() for c in (raw or "").split(",") if c.strip()]


def issue_token(
    db: Session,
    account_id: int,
    caps: list[str] | None = None,
    label: str = "",
    origins: list[str] | None = None,
    ttl_days: int = 365,
) -> tuple[str, str]:
    """领号:为账号签发 1 年期 token。返回 (token 明文, tid)。库里只存 tid + 元数据。"""
    caps = [c for c in (caps or ["read"]) if c in ("read", "write")] or ["read"]
    tid = "tok_" + uuid.uuid4().hex[:24]
    now = datetime.utcnow()
    exp = now + timedelta(days=ttl_days)

    db.add(AgentTokenORM(
        tid=tid,
        account_id=account_id,
        caps=",".join(caps),
        origins=",".join(origins or []),
        label=label,
        enabled=1,
        expires_at=exp,
        created_at=now,
    ))
    db.commit()

    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(account_id),
        "tid": tid,
        "caps": caps,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, _secret(), algorithm=ALGORITHM)
    return token, tid


def verify_token(db: Session, token: str) -> EmbedClaims:
    """每请求校验:验签 + aud + exp(jose 自动)→ 查 enabled → 返回 claims。失败抛 EmbedAuthError。"""
    if not token:
        raise EmbedAuthError(401, "missing token")
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER)
    except JWTError as e:
        raise EmbedAuthError(401, f"invalid_token: {e}")

    tid = payload.get("tid")
    sub = payload.get("sub")
    if not tid or not sub:
        raise EmbedAuthError(401, "invalid_token: missing tid/sub")

    # 长期 token 的吊销命门:必查库里这条还启用、未过期。
    row = db.query(AgentTokenORM).filter(AgentTokenORM.tid == tid).first()
    if row is None or row.enabled != 1:
        raise EmbedAuthError(401, "invalid_token: revoked or unknown")
    if row.expires_at and row.expires_at < datetime.utcnow():
        raise EmbedAuthError(401, "invalid_token: expired")

    # caps 以库为准(可在不重签 token 的情况下收窄);与 JWT 取交集,只收不放。
    db_caps = set(_parse_caps(row.caps))
    jwt_caps = set(payload.get("caps") or [])
    caps = sorted(db_caps & jwt_caps) if jwt_caps else sorted(db_caps)
    return EmbedClaims(
        account_id=int(sub),
        caps=caps,
        tid=tid,
        origins=_parse_caps(row.origins),
    )
