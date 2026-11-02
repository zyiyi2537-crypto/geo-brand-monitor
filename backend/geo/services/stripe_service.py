"""Stripe Checkout integration for overseas / English-locale membership subscriptions.

Flow (hosted checkout):
    1. Frontend calls POST /api/payment/stripe/create-checkout-session with a
       membership slug. Backend creates a Stripe Checkout Session, persists a
       PaymentSessionORM row in 'pending' state, and returns the hosted URL.
    2. User is redirected to Stripe, completes payment, and is sent back to
       STRIPE_SUCCESS_URL?session_id=... (cancel → STRIPE_CANCEL_URL).
    3. Stripe fires 'checkout.session.completed' at our webhook. We verify the
       signature, flip the PaymentSessionORM row to 'paid', and call
       membership_service.upgrade_membership to activate the user's tier.
    4. As a safety net (webhook down / local dev without a tunnel), the
       success page can also call GET /api/payment/stripe/session/{id},
       which re-checks Stripe and fulfills inline if needed.
"""

from datetime import datetime
from typing import Optional, Dict, Any

import stripe

from geo.database import SessionLocal, settings
from geo.models.payment import PaymentSessionORM
from geo.models.membership import MembershipORM
from geo.models.user import UserORM
from geo.services.membership_service import membership_service
from geo.services.price_override import get_test_price_override
from geo.utils.error_handler import AppException


ZERO_DECIMAL_CURRENCIES = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
}


def _to_smallest_unit(amount: float, currency: str) -> int:
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return int(round(amount))
    return int(round(amount * 100))


def _ensure_configured() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise AppException(
            status_code=503,
            message="Stripe is not configured on this server (STRIPE_SECRET_KEY missing)",
        )
    stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeService:
    def create_checkout_session(
        self,
        user: UserORM,
        membership_slug: str,
        locale: str = "en",
    ) -> Dict[str, Any]:
        """Create a Stripe Checkout Session for a user + membership tier.

        Returns {"session_id": ..., "checkout_url": ...}. The caller is
        expected to redirect the browser to checkout_url.
        """
        _ensure_configured()

        db = SessionLocal()
        try:
            membership = (
                db.query(MembershipORM).filter(MembershipORM.slug == membership_slug).first()
            )
            if not membership:
                raise AppException(
                    status_code=404, message=f"Membership '{membership_slug}' not found"
                )
            if membership.tier_type != "saas":
                raise AppException(
                    status_code=400,
                    message=f"{membership.name} is a managed service — contact sales, not self-serve",
                )
            if membership.price <= 0:
                raise AppException(
                    status_code=400,
                    message="Free tier does not require payment",
                )

            # Reuse an existing open session for the same user + membership
            existing = (
                db.query(PaymentSessionORM)
                .filter(
                    PaymentSessionORM.user_id == user.id,
                    PaymentSessionORM.membership_id == membership.id,
                    PaymentSessionORM.status == "pending",
                )
                .order_by(PaymentSessionORM.created_at.desc())
                .first()
            )
            if existing:
                try:
                    remote = stripe.checkout.Session.retrieve(existing.stripe_session_id)
                    if remote.get("status") == "open":
                        return {"session_id": existing.stripe_session_id, "checkout_url": existing.checkout_url}
                except stripe.StripeError:
                    pass
                existing.status = "expired"
                db.commit()

            currency = (membership.currency or "usd").lower()
            amount_cents = _to_smallest_unit(float(membership.price), currency)

            override = get_test_price_override(user.email, currency)
            if override is not None:
                amount_cents = override

            stripe_locale = locale if locale in {"auto", "en", "zh"} else "auto"

            try:
                session = stripe.checkout.Session.create(
                    mode="payment",
                    payment_method_types=["card"],
                    line_items=[
                        {
                            "price_data": {
                                "currency": currency,
                                "product_data": {
                                    "name": f"{membership.name} — GEO Readiness Checker",
                                    "description": membership.description,
                                },
                                "unit_amount": amount_cents,
                            },
                            "quantity": 1,
                        }
                    ],
                    customer_email=user.email,
                    payment_intent_data={"receipt_email": user.email},
                    locale=stripe_locale,
                    success_url=(
                        f"{settings.STRIPE_SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}"
                    ),
                    cancel_url=settings.STRIPE_CANCEL_URL,
                    metadata={
                        "user_id": str(user.id),
                        "membership_id": str(membership.id),
                        "membership_slug": membership.slug,
                    },
                )
            except stripe.StripeError as e:
                raise AppException(
                    status_code=502, message=f"Stripe error: {str(e)}"
                )

            row = PaymentSessionORM(
                stripe_session_id=session.id,
                user_id=user.id,
                membership_id=membership.id,
                amount_cents=amount_cents,
                currency=currency,
                status="pending",
                checkout_url=session.url,
                created_at=datetime.utcnow(),
            )
            db.add(row)
            db.commit()

            return {"session_id": session.id, "checkout_url": session.url}
        finally:
            db.close()

    def verify_and_fulfill_session(
        self, session_id: str, caller_user_id: int
    ) -> Dict[str, Any]:
        """Retrieve a session from Stripe and fulfill it if it's paid.

        This is the safety-net path the success page hits: if the webhook
        already ran, we return the already-fulfilled state; if not, we
        activate the membership here and mark the row paid.

        Scoped to the caller: if the session doesn't belong to the caller
        (or doesn't exist in our DB), we 404. This prevents an authenticated
        user from probing another user's session state.
        """
        _ensure_configured()

        db = SessionLocal()
        try:
            row = (
                db.query(PaymentSessionORM)
                .filter(PaymentSessionORM.stripe_session_id == session_id)
                .first()
            )
            if row is None or row.user_id != caller_user_id:
                raise AppException(status_code=404, message="Session not found")
        finally:
            db.close()

        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError as e:
            raise AppException(status_code=502, message=f"Stripe error: {str(e)}")

        payment_status = session.get("payment_status")
        fulfilled = False
        if payment_status == "paid":
            fulfilled = self._fulfill_if_needed(session_id, session)

        db = SessionLocal()
        try:
            row = (
                db.query(PaymentSessionORM)
                .filter(PaymentSessionORM.stripe_session_id == session_id)
                .first()
            )
            return {
                "session_id": session_id,
                "payment_status": payment_status,
                "status": row.status if row else "unknown",
                "membership_id": row.membership_id if row else None,
                "fulfilled_now": fulfilled,
            }
        finally:
            db.close()

    def handle_webhook(self, payload: bytes, sig_header: Optional[str]) -> Dict[str, Any]:
        """Verify signature and dispatch the event. Called from the webhook route."""
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise AppException(
                status_code=503, message="Stripe webhook secret not configured"
            )
        if not sig_header:
            raise AppException(status_code=400, message="Missing Stripe signature header")

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise AppException(status_code=400, message="Invalid webhook payload")
        except stripe.SignatureVerificationError:
            raise AppException(status_code=400, message="Invalid webhook signature")

        event_type = event["type"]
        data = event["data"]["object"]

        if event_type == "checkout.session.completed":
            session_id = data.get("id")
            if session_id and data.get("payment_status") == "paid":
                self._fulfill_if_needed(session_id, data)
            return {"event": event_type, "session_id": session_id, "processed": True}

        if event_type == "checkout.session.expired":
            session_id = data.get("id")
            self._mark_expired(session_id)
            return {"event": event_type, "session_id": session_id, "processed": True}

        # Other event types are acknowledged but ignored (Stripe just needs a 200).
        return {"event": event_type, "processed": False}

    def _fulfill_if_needed(self, session_id: str, session_obj: Dict[str, Any]) -> bool:
        """Idempotently flip the row to paid and upgrade the user's membership.

        Returns True if this call did the fulfillment, False if it was already
        fulfilled (or the row is missing).
        """
        db = SessionLocal()
        try:
            row = (
                db.query(PaymentSessionORM)
                .filter(PaymentSessionORM.stripe_session_id == session_id)
                .first()
            )
            if row is None:
                return False
            if row.status == "paid":
                return False

            payment_intent = session_obj.get("payment_intent")
            if isinstance(payment_intent, dict):
                payment_intent = payment_intent.get("id")

            row.status = "paid"
            row.completed_at = datetime.utcnow()
            if payment_intent:
                row.stripe_payment_intent_id = payment_intent
            db.commit()

            membership_service.upgrade_membership(row.user_id, row.membership_id)
            return True
        finally:
            db.close()

    def _mark_expired(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        db = SessionLocal()
        try:
            row = (
                db.query(PaymentSessionORM)
                .filter(PaymentSessionORM.stripe_session_id == session_id)
                .first()
            )
            if row and row.status == "pending":
                row.status = "expired"
                db.commit()
        finally:
            db.close()


stripe_service = StripeService()
