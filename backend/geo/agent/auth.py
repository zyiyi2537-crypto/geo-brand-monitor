"""Agent service 独立 JWT 校验 —— 复用主后端 SECRET_KEY + user_service,
但**不 import geo.api**(避免拖入为旧 FastAPI 写的整条路由层)。

与 geo/api/auth.py 的 get_current_user 同源:解 JWT(sub=username)→ user_service 取用户。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWTError as JWTError

from geo.database import settings
from geo.services.user_service import user_service

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    user = user_service.get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user
