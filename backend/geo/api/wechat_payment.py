"""WeChat Pay API routes.

Endpoints:
    POST /wechat/create       — Create a Native Pay prepay order (returns QR code_url)
    GET  /wechat/status/{id}  — Poll payment status (frontend polling)
    POST /wechat/notify       — WeChat async notification callback (no auth)
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from geo.api.auth import get_current_user
from geo.database import SessionLocal, settings
from geo.models.payment import PaymentSessionORM
from geo.models.user import UserORM
from geo.services.wechat_pay_service import wechat_pay_service
from geo.utils.error_handler import AppException

router = APIRouter()


class CreateWechatPayRequest(BaseModel):
    slug: str


@router.post("/wechat/create")
async def create_wechat_payment(
    body: CreateWechatPayRequest,
    current_user: UserORM = Depends(get_current_user),
):
    """Create a WeChat Native Pay order. Returns code_url for QR code rendering."""
    return wechat_pay_service.create_native_order(
        user=current_user,
        membership_slug=body.slug,
    )


@router.get("/wechat/status/{payment_id}")
async def get_wechat_status(
    payment_id: int,
    current_user: UserORM = Depends(get_current_user),
):
    """Poll payment status. Optionally queries WeChat API as safety net."""
    db = SessionLocal()
    try:
        row = (
            db.query(PaymentSessionORM)
            .filter(
                PaymentSessionORM.id == payment_id,
                PaymentSessionORM.user_id == current_user.id,
                PaymentSessionORM.provider == "wechat",
            )
            .first()
        )
        if not row:
            raise AppException(status_code=404, message="Payment not found")

        # If still pending, try querying WeChat API as a safety net
        if row.status == "pending" and row.stripe_session_id:
            try:
                wx_result = wechat_pay_service.query_order(row.stripe_session_id)
                if wx_result.get("trade_state") == "SUCCESS":
                    wechat_pay_service._fulfill_if_needed(row.stripe_session_id)
                    # Re-query — _fulfill_if_needed uses its own DB session
                    db.expire(row)
                    row = (
                        db.query(PaymentSessionORM)
                        .filter(PaymentSessionORM.id == payment_id)
                        .first()
                    )
            except Exception:
                pass  # Safety net — don't fail the polling endpoint

        return {
            "payment_id": row.id,
            "status": row.status,
            "completed_at": str(row.completed_at) if row.completed_at else None,
        }
    finally:
        db.close()


@router.post("/wechat/cancel/{payment_id}")
async def cancel_wechat_payment(
    payment_id: int,
    current_user: UserORM = Depends(get_current_user),
):
    """Cancel a pending WeChat Pay session so the caller can initiate a fresh
    one. Safe — QR not scanned means no money has moved. Only affects rows
    owned by the caller that are still pending.
    """
    db = SessionLocal()
    try:
        row = (
            db.query(PaymentSessionORM)
            .filter(
                PaymentSessionORM.id == payment_id,
                PaymentSessionORM.user_id == current_user.id,
                PaymentSessionORM.provider == "wechat",
            )
            .first()
        )
        if not row:
            raise AppException(status_code=404, message="Payment not found")
        if row.status != "pending":
            raise AppException(
                status_code=400,
                message=f"Cannot cancel a {row.status} payment",
            )
        row.status = "canceled"
        db.commit()
        return {"payment_id": row.id, "status": row.status}
    finally:
        db.close()


@router.post("/wechat/notify")
async def wechat_notify(request: Request):
    """WeChat Pay V3 async notification callback.

    No auth required — WeChat sends this directly. The service layer
    verifies the notification by decrypting with the APIv3 key.
    """
    body = await request.body()
    headers = dict(request.headers)
    result = wechat_pay_service.handle_notify(body, headers)
    return result
