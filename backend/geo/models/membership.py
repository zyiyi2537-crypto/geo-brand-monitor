from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from geo.database import Base

# SQLAlchemy ORM Models
class MembershipORM(Base):
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    # ISO 4217 lowercased — drives the currency passed to Stripe Checkout.
    # 'cny' for domestic SaaS tiers, 'usd' for overseas service tiers.
    currency = Column(String(3), nullable=False, default="usd", server_default="usd")
    period = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    popular = Column(Boolean, default=False)
    features = Column(String, nullable=False)          # JSON string (展示用特性列表)
    not_included = Column(String, nullable=False)      # JSON string
    tier_type = Column(String, nullable=False, default="saas")          # 'saas' | 'service'
    monthly_check_quota = Column(Integer, nullable=False, default=3)    # 0 = 无限
    allowed_check_categories = Column(Text, nullable=True)              # JSON array, NULL = 全部 23 项
    features_json = Column(Text, nullable=True)                         # 人工服务 18 项结构化权益 JSON (service 档用)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class UserMembershipORM(Base):
    __tablename__ = "user_memberships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    membership_id = Column(Integer, ForeignKey("memberships.id"), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)

class UserCheckUsageORM(Base):
    __tablename__ = "user_check_usage"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    year_month = Column(String, primary_key=True)  # '2026-04'
    used_count = Column(Integer, nullable=False, default=0)

class AnonymousCheckUsageORM(Base):
    __tablename__ = "anonymous_check_usage"

    # Opaque per-browser identifier set by the backend as an HTTP cookie
    # (`geo_anon_id`). UUID4 fits in 36 chars; widen for safety. Composite PK
    # with year_month so monthly buckets reset naturally.
    client_id = Column(String(64), primary_key=True)
    year_month = Column(String, primary_key=True)  # '2026-04'
    used_count = Column(Integer, nullable=False, default=0)

class SalesLeadORM(Base):
    __tablename__ = "sales_leads"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    website = Column(String, nullable=True)
    tier_slug = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ContactSubmissionORM(Base):
    __tablename__ = "contact_submissions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    website = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Pydantic Models
class MembershipBase(BaseModel):
    name: str
    price: float
    currency: str = "usd"
    period: str
    description: str
    popular: bool = False

class MembershipCreate(MembershipBase):
    slug: str
    features: List[str]
    not_included: List[str]
    tier_type: str = "saas"
    monthly_check_quota: int = 3
    allowed_check_categories: Optional[List[str]] = None
    features_json: Optional[Dict[str, Any]] = None
    display_order: int = 0

class Membership(MembershipBase):
    id: int
    slug: str
    features: List[str]
    not_included: List[str]
    tier_type: str = "saas"
    monthly_check_quota: int = 3
    allowed_check_categories: Optional[List[str]] = None
    features_json: Optional[Dict[str, Any]] = None
    display_order: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ContactSalesRequest(BaseModel):
    name: str
    email: str
    website: Optional[str] = None
    tier_slug: Optional[str] = None
    message: Optional[str] = None

class UsageResponse(BaseModel):
    quota: int        # 0 = 无限
    used: int
    remaining: int    # -1 = 无限
    year_month: str

class UserMembership(BaseModel):
    id: int
    user_id: int
    membership_id: int
    start_date: datetime
    end_date: datetime
    is_active: bool = True
    
    class Config:
        from_attributes = True

class UserMembershipCreate(BaseModel):
    user_id: int
    membership_id: int
    start_date: datetime
    end_date: datetime

class MembershipUpgrade(BaseModel):
    user_id: int
    new_membership_id: int