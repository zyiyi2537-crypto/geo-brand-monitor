"""Token verification for the subscription-site identity bridge.

The subscription site signs standard HS256 JWTs with MONITOR_JWT_SECRET and
embeds the module with `?token=...` or calls the API with `Authorization:
Bearer ...`. Claims: sub (user id), tenant_id (optional, defaults to sub),
name (optional display), exp (required unix seconds). Verification is pure
stdlib so no crypto package is needed at runtime.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class AuthError(ValueError):
    """Raised when a request token is missing, malformed, or unverifiable."""


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise AuthError("token 编码无效") from exc


def verify_token(token: str, secret: str, *, now: float | None = None) -> dict:
    """Verify one HS256 JWT and return its claims."""
    if not token or not token.strip():
        raise AuthError("缺少访问令牌")
    if not secret:
        raise AuthError("服务未配置令牌密钥")
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise AuthError("访问令牌格式无效")
    header_raw, payload_raw, signature_raw = parts
    signing_input = f"{header_raw}.{payload_raw}".encode("ascii", "replace")
    try:
        header = json.loads(_b64url_decode(header_raw))
    except (json.JSONDecodeError, AuthError) as exc:
        raise AuthError("访问令牌头部无效") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise AuthError("访问令牌算法无效")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual = _b64url_decode(signature_raw)
    if not hmac.compare_digest(expected, actual):
        raise AuthError("访问令牌签名无效")
    try:
        claims = json.loads(_b64url_decode(payload_raw))
    except (json.JSONDecodeError, AuthError) as exc:
        raise AuthError("访问令牌内容无效") from exc
    if not isinstance(claims, dict):
        raise AuthError("访问令牌内容无效")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        raise AuthError("访问令牌缺少过期时间")
    if (now if now is not None else time.time()) >= exp:
        raise AuthError("访问令牌已过期")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthError("访问令牌缺少用户标识")
    return {
        "user_id": subject.strip(),
        "tenant_id": str(claims.get("tenant_id") or subject).strip(),
        "name": str(claims.get("name") or "").strip(),
        "exp": exp,
    }


def verify_admin(header_value: str, admin_token: str) -> None:
    """Verify the operator token on /api/admin/* endpoints."""
    if not admin_token:
        raise AuthError("服务未配置管理令牌")
    provided = header_value.strip() if isinstance(header_value, str) else ""
    if provided.startswith("Bearer "):
        provided = provided[7:].strip()
    if not provided or not hmac.compare_digest(provided, admin_token):
        raise AuthError("管理令牌无效")
