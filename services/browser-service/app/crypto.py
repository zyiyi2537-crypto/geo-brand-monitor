"""凭证加密 —— AES(Fernet)对称加密,密钥从 env ENGINE_CRED_KEY 派生。

用于把账号凭证(identifier+password)加密后存进 engine_sessions.credentials,
供掉线自动续期时解密重登。明文密码只在内存/登录瞬间存在,落库的是密文。
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional


def _fernet():
    raw = os.environ.get("ENGINE_CRED_KEY", "").strip()
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    # 从任意 env 密钥派生 32 字节 urlsafe-base64 的 Fernet key
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def enabled() -> bool:
    return _fernet() is not None


def encrypt(plaintext: str) -> Optional[str]:
    f = _fernet()
    if not f or plaintext is None:
        return None
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> Optional[str]:
    f = _fernet()
    if not f or not ciphertext:
        return None
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
