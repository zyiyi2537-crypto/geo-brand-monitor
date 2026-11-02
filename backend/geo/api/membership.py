from fastapi import APIRouter, Depends
from typing import List
from datetime import datetime
from geo.models.membership import (
    Membership,
    UserMembership,
    ContactSalesRequest,
    UsageResponse,
    SalesLeadORM,
)
from geo.services.membership_service import membership_service
from geo.services.quota_service import get_usage
from geo.database import SessionLocal
from geo.api.auth import get_current_user
from geo.models.user import User
from geo.services.email_service import email_service
from geo.utils.error_handler import AppException

router = APIRouter()

@router.get("/memberships", response_model=List[Membership])
async def get_memberships():
    """Get all membership tiers"""
    return membership_service.get_all_memberships()

@router.get("/memberships/{membership_id}", response_model=Membership)
async def get_membership(membership_id: int):
    """Get membership by ID"""
    membership = membership_service.get_membership_by_id(membership_id)
    if not membership:
        raise AppException(status_code=404, message="Membership not found")
    return membership

@router.get("/user-membership", response_model=UserMembership)
async def get_user_membership(current_user: User = Depends(get_current_user)):
    """Return the logged-in user's effective membership.

    `user_memberships` only stores paid subscription rows — free users have no
    row at all. The old behaviour of 404'ing in that case was wrong: a logged-in
    user should always have at least the free tier (login is not the gate, the
    monthly check quota is). Fall back to `get_effective_membership` (which
    resolves to the free tier when no active paid row exists) and synthesize a
    pseudo `UserMembership` with `id=0` so the response shape stays stable.
    """
    user_membership = membership_service.get_user_membership(current_user.id)
    if user_membership:
        return user_membership
    effective = membership_service.get_effective_membership(current_user.id)
    now = datetime.utcnow()
    return UserMembership(
        id=0,
        user_id=current_user.id,
        membership_id=effective.id,
        start_date=now,
        end_date=datetime(9999, 12, 31),
        is_active=True,
    )

@router.post("/cancel-membership")
async def cancel_membership(current_user: User = Depends(get_current_user)):
    """Cancel user's membership"""
    success = membership_service.cancel_membership(current_user.id)
    if not success:
        raise AppException(status_code=404, message="User membership not found")
    return {"message": "Membership canceled successfully"}


@router.get("/users/me/usage", response_model=UsageResponse)
async def get_my_usage(current_user: User = Depends(get_current_user)):
    """Return the current user's monthly check quota and remaining count."""
    membership = membership_service.get_effective_membership(current_user.id)
    quota, used, remaining, year_month = get_usage(current_user.id, membership)
    return UsageResponse(quota=quota, used=used, remaining=remaining, year_month=year_month)


@router.post("/contact-sales")
async def contact_sales(body: ContactSalesRequest):
    """Accept sales leads from the /products-services contact form.

    Writes the lead to sales_leads, notifies the internal sales inbox, and
    sends an acknowledgement to the submitter. Email failures are logged but
    not fatal — the lead is persisted first.
    """
    db = SessionLocal()
    lead_id = None
    try:
        lead = SalesLeadORM(
            name=body.name,
            email=body.email,
            website=body.website,
            tier_slug=body.tier_slug,
            message=body.message,
            created_at=datetime.utcnow(),
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        lead_id = lead.id
    finally:
        db.close()

    email_service.send_sales_notification_email(
        kind="sales-lead",
        name=body.name,
        email=body.email,
        website=body.website,
        message=body.message or "",
        tier_slug=body.tier_slug,
        submission_id=lead_id,
    )
    email_service.send_sales_lead_confirmation_email(
        body.email, body.name, body.tier_slug
    )

    return {
        "message": "咨询已提交，销售将在 1 个工作日内联系您。",
        "lead_id": lead_id,
    }


