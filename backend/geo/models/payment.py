from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from geo.database import Base


class PaymentSessionORM(Base):
    """Tracks a payment session (Stripe or MoltsPay) from creation through fulfillment."""

    __tablename__ = "payment_sessions"

    id = Column(Integer, primary_key=True, index=True)
    stripe_session_id = Column(String, unique=True, nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    membership_id = Column(Integer, ForeignKey("memberships.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="usd")
    status = Column(String, nullable=False, default="pending", index=True)
    stripe_payment_intent_id = Column(String, nullable=True)
    checkout_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    # MoltsPay fields
    provider = Column(String, nullable=False, default="stripe")  # stripe | moltspay
    chain = Column(String, nullable=True)                        # base
    tx_hash = Column(String, nullable=True)
    wallet_address = Column(String, nullable=True)
