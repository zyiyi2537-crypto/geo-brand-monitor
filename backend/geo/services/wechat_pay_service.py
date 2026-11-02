"""WeChat Pay Native (扫码支付) integration for domestic / Chinese-locale subscriptions.

Flow:
    1. Frontend calls POST /api/payment/wechat/create with a membership slug.
       Backend creates a WeChat Native Pay prepay order via the V3 API, persists
       a PaymentSessionORM row in 'pending' state, and returns the code_url
       (QR code content string).
    2. Frontend renders the code_url as a QR code. User scans with WeChat.
    3. WeChat fires a notification at our POST /api/payment/wechat/notify
       endpoint. We verify the V3 signature, flip the row to 'paid', and call
       membership_service.upgrade_membership().
    4. Safety net: the frontend polls GET /api/payment/wechat/status/{id},
       which can also query the WeChat API and fulfill if the webhook hasn't
       arrived yet.
"""

import base64
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from geo.database import SessionLocal, settings
from geo.models.membership import MembershipORM
from geo.models.payment import PaymentSessionORM
from geo.models.user import UserORM
from geo.services.membership_service import membership_service
from geo.services.price_override import get_test_price_override
from geo.utils.error_handler import AppException

logger = logging.getLogger("geo.wechat_pay")

WECHAT_API_BASE = "https://api.mch.weixin.qq.com"


def _load_private_key():
    """Load the merchant RSA private key from the PEM file."""
    path = settings.WECHAT_PAY_PRIVATE_KEY_PATH
    if not path:
        return None
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _ensure_configured() -> None:
    if not settings.WECHAT_PAY_ENABLED:
        raise AppException(status_code=503, message="WeChat Pay is not enabled")
    required = [
        settings.WECHAT_PAY_APP_ID,
        settings.WECHAT_PAY_MCH_ID,
        settings.WECHAT_PAY_API_KEY_V3,
        settings.WECHAT_PAY_CERT_SERIAL,
        settings.WECHAT_PAY_PRIVATE_KEY_PATH,
    ]
    if not all(required):
        raise AppException(
            status_code=503,
            message="WeChat Pay is not fully configured (missing credentials)",
        )


def _build_authorization(method: str, url_path: str, body: str) -> str:
    """Build the Authorization header value for WeChat Pay V3 API requests.

    Signature format (RFC):
        HTTP Method\n
        URL path (no host)\n
        Timestamp\n
        Nonce\n
        Body\n
    Signed with RSA-SHA256 using the merchant private key.
    """
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"

    private_key = _load_private_key()
    signature = private_key.sign(message.encode("utf-8"), PKCS1v15(), hashes.SHA256())
    signature_b64 = base64.b64encode(signature).decode("utf-8")

    return (
        f'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{settings.WECHAT_PAY_MCH_ID}",'
        f'nonce_str="{nonce}",'
        f'timestamp="{timestamp}",'
        f'serial_no="{settings.WECHAT_PAY_CERT_SERIAL}",'
        f'signature="{signature_b64}"'
    )


def _decrypt_resource(resource: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt the notification resource using AEAD_AES_256_GCM.

    WeChat V3 notifications encrypt the actual payment result inside
    resource.ciphertext, with resource.nonce and resource.associated_data.
    """
    api_key = settings.WECHAT_PAY_API_KEY_V3.encode("utf-8")
    nonce = resource["nonce"].encode("utf-8")
    associated_data = resource.get("associated_data", "").encode("utf-8")
    ciphertext = base64.b64decode(resource["ciphertext"])

    aesgcm = AESGCM(api_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data)
    return json.loads(plaintext.decode("utf-8"))


class WechatPayService:
    def create_native_order(
        self,
        user: UserORM,
        membership_slug: str,
    ) -> Dict[str, Any]:
        """Create a WeChat Native Pay prepay order.

        Returns {"payment_id": ..., "code_url": ..., "amount_cny": ..., "out_trade_no": ...}.
        The frontend renders code_url as a QR code for the user to scan.
        """
        _ensure_configured()

        db = SessionLocal()
        try:
            membership = (
                db.query(MembershipORM)
                .filter(MembershipORM.slug == membership_slug)
                .first()
            )
            if not membership:
                raise AppException(
                    status_code=404,
                    message=f"Membership '{membership_slug}' not found",
                )
            if membership.tier_type != "saas":
                raise AppException(
                    status_code=400,
                    message=f"{membership.name} is a managed service -- contact sales",
                )
            if membership.price <= 0:
                raise AppException(
                    status_code=400,
                    message="Free tier does not require payment",
                )

            # Reuse a recent pending session (< 90 min, within WeChat QR validity)
            existing = (
                db.query(PaymentSessionORM)
                .filter(
                    PaymentSessionORM.user_id == user.id,
                    PaymentSessionORM.membership_id == membership.id,
                    PaymentSessionORM.provider == "wechat",
                    PaymentSessionORM.status == "pending",
                )
                .order_by(PaymentSessionORM.created_at.desc())
                .first()
            )
            if existing:
                age_minutes = (datetime.utcnow() - existing.created_at).total_seconds() / 60
                if age_minutes < 90 and existing.checkout_url:
                    return {
                        "payment_id": existing.id,
                        "code_url": existing.checkout_url,
                        "amount_cny": existing.amount_cents / 100.0,
                        "out_trade_no": existing.stripe_session_id,
                    }
                existing.status = "expired"
                db.commit()

            # Amount in fen (分). membership.price is in the membership's currency.
            # For CNY memberships, price is in yuan; for USD, convert at a rough rate.
            currency = (membership.currency or "usd").lower()
            if currency == "cny":
                amount_fen = int(round(float(membership.price) * 100))
            else:
                # USD → CNY rough conversion (server-side, adjustable)
                usd_to_cny_rate = 7.2
                amount_fen = int(round(float(membership.price) * usd_to_cny_rate * 100))

            # WeChat always settles in CNY, regardless of the membership's
            # nominal currency — so look up the test-account override in CNY.
            override = get_test_price_override(user.email, "cny")
            if override is not None:
                logger.warning(
                    "WeChat test-price override: user=%s tier=%s amount %d fen -> %d fen",
                    user.email, membership_slug, amount_fen, override,
                )
                amount_fen = override

            out_trade_no = f"wechat_{uuid.uuid4().hex[:16]}"

            # Call WeChat V3 API: POST /v3/pay/transactions/native
            url_path = "/v3/pay/transactions/native"
            request_body = {
                "appid": settings.WECHAT_PAY_APP_ID,
                "mchid": settings.WECHAT_PAY_MCH_ID,
                "description": f"GEO Readiness Checker - {membership.name}"[:127],
                "out_trade_no": out_trade_no,
                "notify_url": settings.WECHAT_PAY_NOTIFY_URL,
                "amount": {
                    "total": amount_fen,
                    "currency": "CNY",
                },
            }
            body_str = json.dumps(request_body, ensure_ascii=False)
            authorization = _build_authorization("POST", url_path, body_str)

            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{WECHAT_API_BASE}{url_path}",
                    content=body_str,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Authorization": authorization,
                    },
                )

            if resp.status_code != 200:
                logger.error(
                    "WeChat prepay failed: status=%d body=%s",
                    resp.status_code,
                    resp.text,
                )
                raise AppException(
                    status_code=502,
                    message=f"WeChat Pay API error: {resp.status_code}",
                )

            result = resp.json()
            code_url = result.get("code_url")
            if not code_url:
                raise AppException(
                    status_code=502,
                    message="WeChat Pay did not return a code_url",
                )

            # Persist payment session
            row = PaymentSessionORM(
                stripe_session_id=out_trade_no,
                user_id=user.id,
                membership_id=membership.id,
                amount_cents=amount_fen,
                currency="cny",
                status="pending",
                provider="wechat",
                checkout_url=code_url,
                created_at=datetime.utcnow(),
            )
            db.add(row)
            db.commit()
            db.refresh(row)

            return {
                "payment_id": row.id,
                "code_url": code_url,
                "amount_cny": amount_fen / 100.0,
                "out_trade_no": out_trade_no,
            }
        finally:
            db.close()

    def handle_notify(
        self, body: bytes, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Process a WeChat Pay V3 notification.

        Verifies the signature (via decryption), fulfills the order.
        Returns a dict suitable for the 200 response body WeChat expects.
        """
        _ensure_configured()

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            raise AppException(status_code=400, message="Invalid notification payload")

        event_type = payload.get("event_type", "")
        resource = payload.get("resource")
        if not resource:
            raise AppException(status_code=400, message="Missing resource in notification")

        # Decrypt the resource to get the actual payment result
        try:
            result = _decrypt_resource(resource)
        except Exception as e:
            logger.error("WeChat notification decryption failed: %s", e)
            raise AppException(
                status_code=400,
                message="Failed to decrypt notification resource",
            )

        trade_state = result.get("trade_state")
        out_trade_no = result.get("out_trade_no")

        if trade_state == "SUCCESS" and out_trade_no:
            self._fulfill_if_needed(out_trade_no)

        return {"code": "SUCCESS", "message": "OK"}

    def query_order(self, out_trade_no: str) -> Dict[str, Any]:
        """Query order status from WeChat API. Used as a safety-net."""
        _ensure_configured()

        url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={settings.WECHAT_PAY_MCH_ID}"
        authorization = _build_authorization("GET", url_path, "")

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{WECHAT_API_BASE}{url_path}",
                headers={
                    "Accept": "application/json",
                    "Authorization": authorization,
                },
            )

        if resp.status_code != 200:
            return {"trade_state": "UNKNOWN"}

        return resp.json()

    def _fulfill_if_needed(self, out_trade_no: str) -> bool:
        """Idempotently mark the order as paid and upgrade membership.

        Returns True if this call performed the fulfillment.
        """
        db = SessionLocal()
        try:
            row = (
                db.query(PaymentSessionORM)
                .filter(PaymentSessionORM.stripe_session_id == out_trade_no)
                .first()
            )
            if row is None:
                logger.warning("WeChat fulfill: no row for out_trade_no=%s", out_trade_no)
                return False
            if row.status == "paid":
                return False

            row.status = "paid"
            row.completed_at = datetime.utcnow()
            db.commit()

            membership_service.upgrade_membership(row.user_id, row.membership_id)
            logger.info(
                "WeChat payment fulfilled: user_id=%d membership_id=%d out_trade_no=%s",
                row.user_id,
                row.membership_id,
                out_trade_no,
            )
            return True
        finally:
            db.close()


wechat_pay_service = WechatPayService()
