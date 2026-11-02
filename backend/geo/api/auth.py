from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from jwt import PyJWTError as JWTError
from datetime import datetime, timedelta
from pydantic import BaseModel, EmailStr
from geo.models.user import User, UserCreate, UserLogin, Token
from geo.services.user_service import user_service
from geo.services.email_service import email_service
from geo.utils.error_handler import AppException
from geo.database import settings

router = APIRouter()


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# Security configuration — key comes from .env (settings.SECRET_KEY).
# Never hard-code a fallback here: any committed placeholder becomes a
# known signing key for anyone with the source (the repo is public),
# letting them forge a JWT for any account.
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
# 7 days. Short TTLs (30m) silently convert every long-idle tab into a
# "zombie login" — UI still shows the email (read from localStorage.user)
# while every authed API call 401s. Proper refresh-token rotation is a
# later phase; 7d is a reasonable stop-gap for a SaaS dashboard.
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
RESET_TOKEN_EXPIRE_MINUTES = 15

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_reset_token(data: dict):
    expires_delta = timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    return create_access_token(data, expires_delta)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise AppException(status_code=401, message="Could not validate credentials")
    except JWTError:
        raise AppException(status_code=401, message="Could not validate credentials")
    user = user_service.get_user_by_username(username)
    if user is None:
        raise AppException(status_code=401, message="Could not validate credentials")
    return user


async def require_admin(current_user = Depends(get_current_user)):
    """Reject non-admin users with 403. Wrap any admin-only endpoint with this."""
    if not getattr(current_user, "is_admin", False):
        raise AppException(status_code=403, message="Admin only")
    return current_user

@router.post("/register", response_model=User)
async def register(user: UserCreate):
    """Register a new user"""
    # Check if user already exists
    existing_user = user_service.get_user_by_email(user.email)
    if existing_user:
        raise AppException(status_code=400, message="Email already registered")
    
    # Limit password length to 72 bytes for bcrypt
    user_data = user.model_dump()
    user_data["password"] = user_data["password"][:72]
    user_with_truncated_password = UserCreate(**user_data)
    
    # Create user (password is hashed in user_service)
    new_user = user_service.create_user(user_with_truncated_password)
    return new_user

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login and get access token"""
    # Find user by username (email)
    user = user_service.get_user_by_email(form_data.username)
    if not user:
        raise AppException(status_code=401, message="Incorrect email or password")
    
    # Verify password
    if not user_service.verify_password(form_data.password, user.password_hash):
        raise AppException(status_code=401, message="Incorrect email or password")
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user

@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """Send password reset email"""
    email = body.email
    user = user_service.get_user_by_email(email)
    if not user:
        raise AppException(status_code=404, message="Email not found")

    reset_token = create_reset_token({"sub": user.email, "type": "reset"})

    email_sent = email_service.send_password_reset_email(email, reset_token)
    if not email_sent:
        raise AppException(status_code=500, message="Failed to send password reset email")

    return {"message": "Password reset email sent"}

@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """Reset password"""
    token = body.token
    new_password = body.new_password
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    email: str = payload.get("sub")
    token_type: str = payload.get("type")
    
    if email is None or token_type != "reset":
        raise AppException(status_code=400, message="Invalid reset token")
    
    # Find user by email
    user = user_service.get_user_by_email(email)
    if not user:
        raise AppException(status_code=404, message="User not found")
    
    # Create a UserCreate object to update the password
    user_update = UserCreate(
        email=user.email,
        name=user.name,
        password=new_password
    )
    
    # Update user password
    updated_user = user_service.update_user(user.id, user_update)
    if not updated_user:
        raise AppException(status_code=404, message="User not found")
    
    return {"message": "Password reset successfully"}