"""Runtime configuration for the embeddable GEO monitor service.

Everything is environment-driven so one image serves every deployment:
the subscription site signs user tokens with MONITOR_JWT_SECRET, operators
manage platform logins with MONITOR_ADMIN_TOKEN, and the judge model is a
service-wide asset configured once through GEO_AI_* variables.
"""
from __future__ import annotations

import os
from pathlib import Path

def _find_root() -> Path:
    """Locate the directory that contains tools/geo_record.py.

    Walks up from this file so both layouts work: the repo checkout
    (new geo/services/monitor-service/monitor_service/) and the flattened
    Docker image (/srv/monitor_service/).
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "tools" / "geo_record.py").is_file():
            return parent
    raise RuntimeError("cannot locate pipeline root (tools/geo_record.py)")


ROOT = _find_root()

MONITOR_JWT_SECRET = os.environ.get("MONITOR_JWT_SECRET", "")
MONITOR_ADMIN_TOKEN = os.environ.get("MONITOR_ADMIN_TOKEN", "")

BROWSER_SERVICE_URL = os.environ.get("MONITOR_BROWSER_URL", "http://127.0.0.1:8091")
REPORTS_DIR = Path(os.environ.get("MONITOR_REPORTS_DIR") or ROOT / "reports" / "monitor")
DATA_DIR = Path(os.environ.get("MONITOR_DATA_DIR") or ROOT / "services" / "monitor-service" / "data")
DB_PATH = Path(os.environ.get("MONITOR_DB") or DATA_DIR / "monitor.db")

MONITOR_WORKERS = int(os.environ.get("MONITOR_WORKERS", "1"))
MONITOR_JOB_TIMEOUT = float(os.environ.get("MONITOR_JOB_TIMEOUT", "330"))
MONITOR_MAX_QUESTIONS = int(os.environ.get("MONITOR_MAX_QUESTIONS", "50"))

# Optional quota bridge to the subscription site. When set, the service POSTs
# {tenant_id, questions} and expects {"allowed": true} before a job starts.
MONITOR_QUOTA_URL = os.environ.get("MONITOR_QUOTA_URL", "")
MONITOR_QUOTA_TOKEN = os.environ.get("MONITOR_QUOTA_TOKEN", "")
MONITOR_QUOTA_FAIL_MODE = os.environ.get("MONITOR_QUOTA_FAIL_MODE", "deny")  # deny | allow

# Judge model (operator asset). Same variable names as the tools/geo_record CLI.
AI_BASE_URL = os.environ.get("GEO_AI_BASE_URL", "")
AI_MODEL = os.environ.get("GEO_AI_MODEL", "")
AI_API_KEY = os.environ.get("GEO_AI_API_KEY", "")
AI_WIRE_API = os.environ.get("GEO_AI_WIRE_API", "chat")


def ai_settings() -> dict[str, str]:
    return {
        "base_url": AI_BASE_URL,
        "model": AI_MODEL,
        "api_key": AI_API_KEY,
        "wire_api": AI_WIRE_API,
    }


def validate() -> list[str]:
    """Return configuration problems that must be fixed before serving."""
    problems: list[str] = []
    if not MONITOR_JWT_SECRET:
        problems.append("MONITOR_JWT_SECRET is required (shared with the subscription site)")
    if len(MONITOR_JWT_SECRET) < 16:
        problems.append("MONITOR_JWT_SECRET must be at least 16 characters")
    if not MONITOR_ADMIN_TOKEN:
        problems.append("MONITOR_ADMIN_TOKEN is required for operator endpoints")
    if MONITOR_MAX_QUESTIONS < 1:
        problems.append("MONITOR_MAX_QUESTIONS must be positive")
    if MONITOR_QUOTA_FAIL_MODE not in {"deny", "allow"}:
        problems.append("MONITOR_QUOTA_FAIL_MODE must be deny or allow")
    return problems
