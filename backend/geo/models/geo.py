from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class GeoTestRequest(BaseModel):
    """Request model for GEO test"""
    url: str = Field(..., description="Website URL to test")
    include_fix: bool = Field(default=True, description="Include fix recommendations")
    force_refresh: bool = Field(
        default=False,
        description=(
            "Skip L1 Redis + L2 DB cache and run fresh. Used by the 'verify "
            "after fix' flow on the result page so users see updated scores "
            "immediately instead of the 24h-stale cached report."
        ),
    )

class CheckResult(BaseModel):
    """Result of a single check"""
    category: str
    status: str  # PASS, WARN, FAIL, INFO
    message: str
    fix: Optional[str] = None
    # i18n key + params emitted by geo_checker.emit_check(). When present,
    # the frontend renders t(message_key, message_params); when absent
    # (legacy un-migrated checks), the frontend falls back to `message`.
    message_key: Optional[str] = None
    message_params: Optional[Dict[str, Any]] = None
    # i18n key + params for the fix recommendation, emitted by emit_fix().
    # Same fallback: when absent the frontend renders plain `fix` text.
    fix_key: Optional[str] = None
    fix_params: Optional[Dict[str, Any]] = None

class GeoTestResult(BaseModel):
    """Response model for GEO test result"""
    url: str
    score: int
    grade: str
    checks: List[CheckResult]
    summary: Dict[str, Any]
    tier: Optional[str] = None  # 'free' | 'pro' | 'starter' | 'growth' | 'scale'
    locked_categories: Optional[List[str]] = None  # categories hidden from this tier
