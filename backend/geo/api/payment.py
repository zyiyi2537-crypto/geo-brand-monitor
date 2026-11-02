from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from typing import Optional

from geo.api.auth import get_current_user
from geo.database import settings
from geo.models.user import User
from geo.services.stripe_service import stripe_service

router = APIRouter()


class CreateCheckoutSessionRequest(BaseModel):
    slug: str
    locale: Optional[str] = "en"


@router.get("/stripe/config")
async def stripe_config():
    """Expose only the publishable key + test-mode flag to the frontend."""
    return {
        "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        "configured": bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_PUBLISHABLE_KEY),
    }


@router.post("/stripe/create-checkout-session")
async def create_checkout_session(
    body: CreateCheckoutSessionRequest,
    current_user: User = Depends(get_current_user),
):
    return stripe_service.create_checkout_session(
        user=current_user,
        membership_slug=body.slug,
        locale=body.locale or "en",
    )


@router.get("/stripe/session/{session_id}")
async def get_stripe_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """Safety-net: success page polls this to fulfill if webhook is lagging.

    Scoped to the caller's own sessions — probing another user's session_id
    returns 404 so we don't leak membership / payment state across accounts.
    """
    return stripe_service.verify_and_fulfill_session(
        session_id, caller_user_id=current_user.id
    )


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
):
    payload = await request.body()
    return stripe_service.handle_webhook(payload, stripe_signature)
