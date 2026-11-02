"""Centralized QA/test-account price overrides.

One whitelist of test emails, shared by every payment gateway (Stripe,
WeChat, future). Lets us run real end-to-end checkout flows without burning
real money, and keeps the backdoor visible in one place.

Fixed amounts, not a lookup table — simplest thing that works:
- USD → 60 cents ($0.60, above Stripe's $0.50 minimum)
- CNY → 100 fen (¥1.00)

Other currencies are not overridden; callers see None and fall back to the
membership's configured price.
"""
from typing import Optional


# Test accounts that get the minimum-viable price on any payment method.
# Lowercased; caller's email is lowercased before lookup.
_TEST_EMAILS = {
    "guotielong@hotmail.com",
}


def get_test_price_override(email: Optional[str], currency: str) -> Optional[int]:
    """Return override amount in the smallest unit of `currency` (cents for
    USD, fen for CNY), or None if this caller/currency shouldn't be overridden.
    """
    if not email or email.lower() not in _TEST_EMAILS:
        return None
    c = (currency or "").lower()
    if c == "usd":
        return 60
    if c == "cny":
        return 100
    return None
