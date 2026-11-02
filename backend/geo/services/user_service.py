from typing import Optional, List
from geo.models.user import User, UserCreate, UserORM
from geo.database import SessionLocal
import bcrypt
import json

class UserService:
    def __init__(self):
        pass
    
    def create_user(self, user: UserCreate) -> User:
        """Create a new user"""
        db = SessionLocal()
        try:
            # Limit password length to 72 bytes for bcrypt
            password = user.password[:72]
            # Hash the password
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Name 在 API 入口可选,users.name 列也是 nullable.
            # 不要 fallback 到 email — 那样 admin 画像列表里"没填名称"
            # 的客户会展示成邮箱,看起来像数据重复.让 NULL 保持 NULL,
            # 前端 `a.name || '—'` 会渲染成占位符.
            db_user = UserORM(
                email=user.email,
                name=(user.name.strip() if user.name and user.name.strip() else None),
                password_hash=password_hash
            )
            
            # Add to database
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
            
            # Convert to Pydantic model
            return User(
                id=db_user.id,
                email=db_user.email,
                name=db_user.name,
                is_active=db_user.is_active
            )
        finally:
            db.close()
    
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        db = SessionLocal()
        try:
            db_user = db.query(UserORM).filter(UserORM.id == user_id).first()
            if db_user:
                return User(
                    id=db_user.id,
                    email=db_user.email,
                    name=db_user.name,
                    is_active=db_user.is_active
                )
            return None
        finally:
            db.close()
    
    def get_user_by_email(self, email: str) -> Optional[UserORM]:
        """Get user by email"""
        db = SessionLocal()
        try:
            return db.query(UserORM).filter(UserORM.email == email).first()
        finally:
            db.close()
    
    def get_user_by_username(self, username: str) -> Optional[UserORM]:
        """Get user by username (email)"""
        return self.get_user_by_email(username)
    
    def get_all_users(self) -> List[User]:
        """Get all users"""
        db = SessionLocal()
        try:
            db_users = db.query(UserORM).all()
            return [
                User(
                    id=user.id,
                    email=user.email,
                    name=user.name,
                    is_active=user.is_active
                )
                for user in db_users
            ]
        finally:
            db.close()
    
    def update_user(self, user_id: int, user_update: UserCreate) -> Optional[User]:
        """Update user"""
        db = SessionLocal()
        try:
            db_user = db.query(UserORM).filter(UserORM.id == user_id).first()
            if db_user:
                # Limit password length to 72 bytes for bcrypt
                password = user_update.password[:72]
                # Hash the password
                password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                
                db_user.email = user_update.email
                if user_update.name is not None:
                    db_user.name = user_update.name
                db_user.password_hash = password_hash
                
                db.commit()
                db.refresh(db_user)
                
                return User(
                    id=db_user.id,
                    email=db_user.email,
                    name=db_user.name,
                    is_active=db_user.is_active
                )
            return None
        finally:
            db.close()
    
    def delete_user(self, user_id: int) -> bool:
        """Delete user"""
        db = SessionLocal()
        try:
            db_user = db.query(UserORM).filter(UserORM.id == user_id).first()
            if db_user:
                db.delete(db_user)
                db.commit()
                return True
            return False
        finally:
            db.close()
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password"""
        try:
            # Limit password length to 72 bytes for bcrypt
            password = plain_password[:72]
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception as e:
            return False

# Create and export user_service instance
user_service = UserService()