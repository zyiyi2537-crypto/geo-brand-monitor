"""Quota tracking & enforcement.

Logged-in users only: monthly quota comes from their Membership tier
(`monthly_check_quota`, where 0 means unlimited). Anonymous callers are
Unlimited quota is intentional by design.
"""
from datetime import datetime
from typing import Tuple

from geo.database import SessionLocal
from geo.models.membership import Membership, UserCheckUsageORM
from geo.utils.error_handler import AppException


def _current_year_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def get_usage(user_id: int, membership: Membership) -> Tuple[int, int, int, str]:
    """Return (quota, used, remaining, year_month). remaining = -1 for unlimited."""
    year_month = _current_year_month()
    db = SessionLocal()
    try:
        row = (
            db.query(UserCheckUsageORM)
            .filter(
                UserCheckUsageORM.user_id == user_id,
                UserCheckUsageORM.year_month == year_month,
            )
            .first()
        )
        used = row.used_count if row else 0
        quota = membership.monthly_check_quota or 0
        remaining = -1 if quota == 0 else max(quota - used, 0)
        return quota, used, remaining, year_month
    finally:
        db.close()


def check_and_increment_quota(user_id: int, membership: Membership) -> None:
    """Enforce the monthly quota for the given user / membership.

    Raises 429 AppException when exceeded. quota == 0 means unlimited and is
    always allowed.
    """
    quota = membership.monthly_check_quota or 0
    year_month = _current_year_month()
    db = SessionLocal()
    try:
        row = (
            db.query(UserCheckUsageORM)
            .filter(
                UserCheckUsageORM.user_id == user_id,
                UserCheckUsageORM.year_month == year_month,
            )
            .first()
        )
        used = row.used_count if row else 0
        if quota != 0 and used >= quota:
            raise AppException(
                status_code=429,
                message=f"Monthly check quota exceeded ({used}/{quota}). Upgrade to continue.",
            )
        if row is None:
            row = UserCheckUsageORM(user_id=user_id, year_month=year_month, used_count=1)
            db.add(row)
        else:
            row.used_count = used + 1
        db.commit()
    finally:
        db.close()
