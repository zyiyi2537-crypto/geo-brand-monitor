from datetime import datetime
from typing import Optional
import uuid

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from geo.api.auth import get_current_user
from geo.database import SessionLocal, settings
from geo.models.payment import PaymentSessionORM
from geo.models.membership import MembershipORM
from geo.models.user import UserORM
from geo.services.membership_service import membership_service
from geo.utils.error_handler import AppException

router = APIRouter()

MOLTSPAY_WALLET = getattr(settings, "MOLTSPAY_WALLET_ADDRESS", "")
MOLTSPAY_CHAIN = getattr(settings, "MOLTSPAY_CHAIN", "base")

SLUG_TO_SERVICE_ID = {
    "pro": "membership-detector",
    "starter": "membership-starter",
    "growth": "membership-growth",
}


class CreateMoltsPayRequest(BaseModel):
    slug: str


class FulfillRequest(BaseModel):
    user_id: int
    membership_slug: str


@router.post("/moltspay/create")
async def create_moltspay_payment(
    body: CreateMoltsPayRequest,
    current_user: UserORM = Depends(get_current_user),
):
    if not getattr(settings, "MOLTSPAY_ENABLED", False):
        raise AppException(status_code=503, message="MoltsPay is not enabled")

    db = SessionLocal()
    try:
        membership = (
            db.query(MembershipORM).filter(MembershipORM.slug == body.slug).first()
        )
        if not membership:
            raise AppException(status_code=404, message=f"Membership '{body.slug}' not found")
        if membership.price <= 0:
            raise AppException(status_code=400, message="Free tier does not require payment")

        service_id = SLUG_TO_SERVICE_ID.get(body.slug)
        if not service_id:
            raise AppException(status_code=400, message=f"MoltsPay not available for plan '{body.slug}'")

        existing = (
            db.query(PaymentSessionORM)
            .filter(
                PaymentSessionORM.user_id == current_user.id,
                PaymentSessionORM.membership_id == membership.id,
                PaymentSessionORM.provider == "moltspay",
                PaymentSessionORM.status == "pending",
            )
            .order_by(PaymentSessionORM.created_at.desc())
            .first()
        )
        if existing:
            age_minutes = (datetime.utcnow() - existing.created_at).total_seconds() / 60
            if age_minutes < 30:
                return {
                    "payment_id": existing.id,
                    "user_id": current_user.id,
                    "amount_usdc": float(membership.price),
                    "chain": MOLTSPAY_CHAIN,
                    "service_id": service_id,
                    "wallet_address": MOLTSPAY_WALLET,
                    "status": "pending",
                }
            existing.status = "expired"
            db.commit()

        amount_cents = int(round(float(membership.price) * 100))

        row = PaymentSessionORM(
            stripe_session_id=f"moltspay_{uuid.uuid4().hex[:16]}",
            user_id=current_user.id,
            membership_id=membership.id,
            amount_cents=amount_cents,
            currency="usdc",
            status="pending",
            provider="moltspay",
            chain=MOLTSPAY_CHAIN,
            wallet_address=MOLTSPAY_WALLET,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        return {
            "payment_id": row.id,
            "user_id": current_user.id,
            "amount_usdc": float(membership.price),
            "chain": MOLTSPAY_CHAIN,
            "service_id": service_id,
            "wallet_address": MOLTSPAY_WALLET,
            "status": "pending",
        }
    finally:
        db.close()


@router.get("/moltspay/status/{payment_id}")
async def get_moltspay_status(
    payment_id: int,
    current_user: UserORM = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        row = (
            db.query(PaymentSessionORM)
            .filter(
                PaymentSessionORM.id == payment_id,
                PaymentSessionORM.user_id == current_user.id,
                PaymentSessionORM.provider == "moltspay",
            )
            .first()
        )
        if not row:
            raise AppException(status_code=404, message="Payment not found")

        return {
            "payment_id": row.id,
            "status": row.status,
            "tx_hash": row.tx_hash,
            "completed_at": str(row.completed_at) if row.completed_at else None,
        }
    finally:
        db.close()


@router.post("/moltspay/cancel/{payment_id}")
async def cancel_moltspay_payment(
    payment_id: int,
    current_user: UserORM = Depends(get_current_user),
):
    """Cancel a pending MoltsPay session so the caller can start fresh.

    Caller should only invoke this *before* they've signed the EIP-3009
    authorization on-chain. Canceling after the USDC transfer has been
    broadcast could strand a paid tx without a matching session to fulfill.
    """
    db = SessionLocal()
    try:
        row = (
            db.query(PaymentSessionORM)
            .filter(
                PaymentSessionORM.id == payment_id,
                PaymentSessionORM.user_id == current_user.id,
                PaymentSessionORM.provider == "moltspay",
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


@router.post("/moltspay/fulfill")
async def moltspay_fulfill(request: Request, body: FulfillRequest):
    client_ip = request.client.host if request.client else ""
    if client_ip not in ("127.0.0.1", "::1"):
        raise AppException(status_code=403, message="Forbidden")

    db = SessionLocal()
    try:
        membership = (
            db.query(MembershipORM).filter(MembershipORM.slug == body.membership_slug).first()
        )
        if not membership:
            raise AppException(status_code=404, message="Membership not found")

        row = (
            db.query(PaymentSessionORM)
            .filter(
                PaymentSessionORM.user_id == body.user_id,
                PaymentSessionORM.membership_id == membership.id,
                PaymentSessionORM.provider == "moltspay",
                PaymentSessionORM.status == "pending",
            )
            .order_by(PaymentSessionORM.created_at.desc())
            .first()
        )
        if not row:
            raise AppException(status_code=404, message="No pending MoltsPay session found")

        if row.status == "paid":
            return {"success": True, "payment_id": row.id}

        row.status = "paid"
        row.completed_at = datetime.utcnow()
        db.commit()

        membership_service.upgrade_membership(body.user_id, membership.id)

        return {"success": True, "payment_id": row.id}
    finally:
        db.close()


# USDC on Base mainnet
USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC = "https://mainnet.base.org"
# ERC-20 Transfer event topic
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class VerifyTxRequest(BaseModel):
    payment_id: int
    tx_hash: str


@router.post("/moltspay/verify")
async def verify_moltspay_tx(
    body: VerifyTxRequest,
    current_user: UserORM = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        row = (
            db.query(PaymentSessionORM)
            .filter(
                PaymentSessionORM.id == body.payment_id,
                PaymentSessionORM.user_id == current_user.id,
                PaymentSessionORM.provider == "moltspay",
            )
            .first()
        )
        if not row:
            raise AppException(status_code=404, message="Payment not found")
        if row.status == "paid":
            return {"success": True, "payment_id": row.id, "already_paid": True}

        # Check tx_hash not already used
        existing_tx = (
            db.query(PaymentSessionORM)
            .filter(
                PaymentSessionORM.tx_hash == body.tx_hash,
                PaymentSessionORM.status == "paid",
            )
            .first()
        )
        if existing_tx:
            raise AppException(status_code=400, message="Transaction already used")

        # Verify on-chain
        receipt = await _get_tx_receipt(body.tx_hash)
        if not receipt:
            raise AppException(status_code=400, message="Transaction not found on chain")

        status_hex = receipt.get("status", "0x0")
        if int(status_hex, 16) != 1:
            raise AppException(status_code=400, message="Transaction failed on chain")

        # Parse USDC Transfer events from logs
        expected_to = MOLTSPAY_WALLET.lower()
        expected_amount = row.amount_cents * 10000  # cents → 6-decimal USDC (e.g. 999 cents = 9990000)
        usdc_contract = USDC_CONTRACT.lower()

        transfer_matched = False
        for log in receipt.get("logs", []):
            if log.get("address", "").lower() != usdc_contract:
                continue
            topics = log.get("topics", [])
            if len(topics) < 3 or topics[0] != TRANSFER_TOPIC:
                continue
            to_addr = "0x" + topics[2][-40:]
            if to_addr.lower() != expected_to:
                continue
            amount = int(log.get("data", "0x0"), 16)
            if amount >= expected_amount:
                transfer_matched = True
                break

        if not transfer_matched:
            raise AppException(
                status_code=400,
                message="USDC transfer not found or amount mismatch",
            )

        # Fulfill
        row.status = "paid"
        row.tx_hash = body.tx_hash
        row.completed_at = datetime.utcnow()
        db.commit()

        membership_service.upgrade_membership(current_user.id, row.membership_id)

        return {"success": True, "payment_id": row.id}
    finally:
        db.close()


async def _get_tx_receipt(tx_hash: str) -> Optional[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            BASE_RPC,
            json={
                "jsonrpc": "2.0",
                "method": "eth_getTransactionReceipt",
                "params": [tx_hash],
                "id": 1,
            },
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("result")
