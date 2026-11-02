from fastapi import APIRouter
from pydantic import BaseModel
from geo.models.user import Token, UserCreate
from geo.services.user_service import user_service
import jwt
from datetime import datetime, timedelta
import requests
from geo.database import settings
from geo.utils.error_handler import AppException

router = APIRouter()


class GoogleLoginRequest(BaseModel):
    google_token: str


GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
SECRET_KEY = settings.SECRET_KEY


@router.post("/google", response_model=Token)
async def google_login(payload: GoogleLoginRequest):
    """Google OAuth登录"""
    google_token = payload.google_token
    google_response = requests.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"id_token": google_token}
    )

    if not google_response.ok:
        raise AppException(status_code=401, message="Invalid Google token")

    user_info = google_response.json()

    if user_info.get("aud") != GOOGLE_CLIENT_ID:
        raise AppException(status_code=401, message="Invalid Google client ID")

    user = user_service.get_user_by_email(user_info["email"])
    if not user:
        # OAuth users never sign in with a password; use a random 32-byte
        # secret so the stored bcrypt hash is unguessable. The string is
        # discarded immediately after hashing.
        import secrets
        user = user_service.create_user(UserCreate(
            email=user_info["email"],
            name=user_info.get("name", "Google User"),
            password=secrets.token_urlsafe(32),
        ))

    access_token_expires = timedelta(minutes=30)
    access_token = jwt.encode(
        {"sub": user.email, "exp": datetime.utcnow() + access_token_expires},
        SECRET_KEY,
        algorithm="HS256"
    )

    return {"access_token": access_token, "token_type": "bearer"}
