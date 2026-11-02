import io
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Enable i18n-ready structured emit in geo_checker BEFORE importing it.
# geo_checker.output reads this env var at module-load time to toggle the
# \x01GK\x01...\x01GE\x01 marker in each emit_check line.
os.environ["GEO_EMIT_STRUCTURED"] = "1"

# Post-refactor (2026-04-17): geo_checker is a package, not a single file.
# We reach into its submodules directly:
#   - state:       for SHOW_FIX toggling
#   - orchestrate: for generate_score
#   - checks:      for per-function timing instrumentation
from geo_checker import state as _gc_state
from geo_checker import orchestrate as _gc_orchestrate
from geo_checker import checks as _gc_checks
from geo.models.geo import GeoTestResult, CheckResult
from geo.utils.timing import instrument_checks, instrument_funcs, time_block
from geo.services import cache_service

_log = logging.getLogger(__name__)

# Monkey-patch every check_* + the top-level generate_score with timing logs.
# Applied once at import; subsequent imports are no-ops (idempotent via
# _geo_timed marker inside timing._wrap).
#
# IMPORTANT: we must instrument BOTH _gc_checks (the source module) AND
# _gc_orchestrate (which has local bindings via `from .checks import ...`).
# CHECK_REGISTRY lambdas resolve `check_https(url)` against orchestrate's own
# globals — instrumenting only _gc_checks wraps the wrong copy and per-check
# timing disappears. Keep both or you lose visibility.
instrument_checks(_gc_checks)
instrument_checks(_gc_orchestrate)
instrument_funcs(_gc_orchestrate, ["generate_score"])

# Cache TTL for report layer. Redis is the primary cache; detection_records
# (SQLite) is a secondary per-user永久 cache — together they form a two-level
# cache: first L1 (Redis, cross-user, 24h), then L2 (DB, per-user, 24h window
# inside permanent retention).
_REPORT_TTL_S = 24 * 60 * 60

# geo_checker.__main__ uses module-level globals (_scores, _page_cache, SHOW_FIX),
# so concurrent in-process calls would race. Serialize with a lock; concurrency
# across requests is still achieved by offloading via asyncio.to_thread in the
# API layer — the event loop stays unblocked, even while checks queue here.
_geo_checker_lock = threading.Lock()

class GeoChecker:
    def run_geo_check(
        self,
        url: str,
        include_fix: bool,
        allowed_categories: Optional[List[str]] = None,
    ) -> GeoTestResult:
        return run_geo_check(url, include_fix, allowed_categories=allowed_categories)

geo_checker = GeoChecker()


def _build_cache_key(url: str, include_fix: bool, allowed_categories: Optional[List[str]], tier: str) -> str:
    categories_key = ",".join(sorted(allowed_categories)) if allowed_categories else "all"
    return cache_service.make_cache_key(
        "default",
        url,
        tier=tier,
        include_fix=include_fix,
        extra={"categories": categories_key},
    )


def _lookup_db_fallback(user_id: int, url: str, tier: str) -> Optional[GeoTestResult]:
    """Registered user L2 cache: scan detection_records within the last 24h
    for a matching (user_id, url, tier, mode=free) record. Returns the stored
    GeoTestResult or None.

    detection_records is never evicted (永久 retention), but we still apply
    the 24h window here so the user gets a fresh run daily even if their
    Redis entry was pushed out. Older records remain for history/display
    via /api/account/detections but are not reused as cache.
    """
    try:
        from geo.database import SessionLocal
        from geo.models.detection import DetectionRecordORM
    except Exception as e:
        _log.warning("DB fallback unavailable: %s", e)
        return None

    cutoff = datetime.utcnow() - timedelta(seconds=_REPORT_TTL_S)
    db = SessionLocal()
    try:
        # Normalize URL for a looser match (DB stores trailing slash sometimes).
        url_variants = {url, url.rstrip("/"), url + "/"}
        rec = (
            db.query(DetectionRecordORM)
            .filter(
                DetectionRecordORM.user_id == user_id,
                DetectionRecordORM.url.in_(list(url_variants)),
                DetectionRecordORM.tier == tier,
                DetectionRecordORM.mode == "free",
                DetectionRecordORM.deleted_at.is_(None),
                DetectionRecordORM.created_at >= cutoff,
            )
            .order_by(DetectionRecordORM.created_at.desc())
            .first()
        )
        if rec is None:
            return None
        data = json.loads(rec.result_snapshot)
        return GeoTestResult(**data)
    except Exception as e:
        _log.warning("DB fallback query failed for user=%s url=%s: %s", user_id, url, e)
        return None
    finally:
        db.close()


def run_geo_check(
    url: str,
    include_fix: bool,
    progress_callback=None,
    allowed_categories: Optional[List[str]] = None,
    user_id: Optional[int] = None,
    tier: str = "free",
    force_refresh: bool = False,
) -> GeoTestResult:
    """Run GEO readiness check in-process and return structured result.

    Two-level cache (issue #8, 2026-04-17):
      L1 — Redis db=7, 24h TTL, key = sha1(url|tier|include_fix|categories).
           Cross-user shared (any user reading the same URL+tier benefits).
      L2 — DB detection_records, per-user, 24h window. Only queried for
           logged-in users on L1 miss. Acts as a second-chance cache when
           Redis is cold / flushed / lost a key to LRU.

    allowed_categories: optional whitelist of category labels (e.g. the 5
    free-tier checks). When None, all 25 categories are run.
    user_id: if provided, enables L2 DB fallback. Anonymous requests get L1 only.
    tier: user's effective tier, part of the cache key (free/starter/pro/...)
    force_refresh: when True, skip both L1 (Redis) and L2 (DB) reads and run
        fresh. The freshly computed result is still written back to L1 so it
        overwrites any stale entry, and (for logged-in callers) save_detection
        in the API layer appends a new L2 row that will win subsequent
        order_by(created_at desc) lookups. Used by the "verify after fix" UX
        on the result page.
    """
    print(f"Starting run_geo_check for {url}{' [force_refresh]' if force_refresh else ''}")

    cache_key = _build_cache_key(url, include_fix, allowed_categories, tier)

    if not force_refresh:
        # L1: Redis cache
        cached = cache_service.get_cached_report(cache_key)
        if cached:
            print(f"L1 cache HIT for {url}")
            if progress_callback:
                progress_callback(100)
            return GeoTestResult(**cached)

        # L2: DB fallback for logged-in users
        if user_id is not None:
            db_result = _lookup_db_fallback(user_id, url, tier)
            if db_result is not None:
                print(f"L2 DB cache HIT for user={user_id} url={url}")
                # Warm Redis so the next request (including other users on same tier)
                # can hit L1 directly.
                cache_service.set_cached_report(cache_key, db_result.model_dump(), ttl_s=_REPORT_TTL_S)
                if progress_callback:
                    progress_callback(100)
                return db_result

    # Background ticker thread: emits a time-based progress estimate while the
    # checker is running (same semantics as the old subprocess-based reader).
    stop_event = threading.Event()
    progress_thread: Optional[threading.Thread] = None
    if progress_callback:
        start_time = time.time()

        def _tick_progress():
            while not stop_event.wait(2):
                elapsed = time.time() - start_time
                progress_callback(min(int((elapsed / 300) * 90), 90))

        progress_thread = threading.Thread(target=_tick_progress, daemon=True)
        progress_thread.start()

    try:
        buf = io.StringIO()
        # _geo_checker_lock still protects SHOW_FIX toggling across requests.
        # Inside a single request, the 25 check_* run concurrently (#14) but
        # their shared state (_scores, _page_cache) is lock-protected inside
        # the geo_checker package itself.
        #
        # stdout: we use the same _ThreadLocalStdout proxy as advanced_runners
        # (installed there at module load) so two concurrent threadpool threads
        # running check_* can each write to their own buffer without
        # clobbering sys.stdout. redirect_stdout is NOT safe here because it
        # mutates the process-wide sys.stdout.
        from geo.services.advanced_runners import _stdout_proxy
        with _geo_checker_lock:
            old_show_fix = _gc_state.SHOW_FIX
            _gc_state.SHOW_FIX = include_fix
            _stdout_proxy._state.buf = buf
            try:
                with time_block(f"default_check url={url}"):
                    _gc_orchestrate.generate_score(
                        url, allowed_categories=allowed_categories
                    )
            finally:
                _stdout_proxy._state.buf = None
                _gc_state.SHOW_FIX = old_show_fix

        output = buf.getvalue()
        print(f"Parsing GEO output...")
        geo_result = parse_geo_output(url, output, include_fix)
        print(f"GEO check completed successfully")

        # Write L1 (Redis). L2 (detection_records) is written by the API
        # layer's save_detection() only for logged-in users after the
        # response serialization, so we don't double-persist here.
        cache_service.set_cached_report(cache_key, geo_result.model_dump(), ttl_s=_REPORT_TTL_S)
        return geo_result
    except Exception as e:
        print(f"Error in run_geo_check: {str(e)}")
        raise Exception(f"Failed to run GEO check: {str(e)}")
    finally:
        stop_event.set()
        if progress_thread is not None:
            progress_thread.join(timeout=1)
        if progress_callback:
            progress_callback(100)

# Legacy get_cached_result / cache_result have been replaced by
# cache_service (Redis) + _lookup_db_fallback. If any caller imported them
# from this module, they now get an AttributeError — intentional, so we
# catch stragglers at import-time rather than silently miss the cache.

_KEY_MARKER_RE = re.compile(r"\x01GK\x01(.*?)\x01GE\x01", re.DOTALL)


def _extract_key_marker(message: str):
    """Strip the structured-i18n marker from a check message if present.

    Returns (clean_message, message_key_or_none, message_params_or_none).
    """
    m = _KEY_MARKER_RE.search(message)
    if not m:
        return message, None, None
    try:
        meta = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return message, None, None
    clean = (message[: m.start()] + message[m.end() :]).rstrip()
    return clean, meta.get("k"), meta.get("p")


def parse_geo_output(url: str, output: str, include_fix: bool) -> GeoTestResult:
    """Parse the output from geo_checker script into structured format"""
    checks = []
    current_category = None

    # Remove ANSI color codes from output. IMPORTANT: run this BEFORE the
    # status_pattern match. The marker chars (\x01) are NOT ANSI and survive.
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    output = ansi_escape.sub('', output)

    # Regex patterns to extract information
    category_pattern = re.compile(r"^--- (.*) ---")
    status_pattern = re.compile(r"^\s*\[(PASS|WARN|FAIL|INFO| FIX)\] (.*)")
    score_pattern = re.compile(r"^AI VISIBILITY SCORE:\s*(\d+)/100\s*\(Grade: ([A-F+]+)\)")

    score = 0
    grade = "F"

    lines = output.split('\n')
    for line in lines:
        line = line.strip()

        # Check for category
        category_match = category_pattern.match(line)
        if category_match:
            current_category = category_match.group(1)
            continue

        # Check for status line
        status_match = status_pattern.match(line)
        if status_match and current_category:
            status = status_match.group(1)
            raw_message = status_match.group(2)
            # Extract optional i18n key marker embedded by emit_check.
            message, message_key, message_params = _extract_key_marker(raw_message)

            # For FIX lines, we need to handle differently
            if status == " FIX":
                # This is a fix recommendation for the previous check.
                # emit_fix() joins multi-line text with \x02 so the parser
                # sees a single line — restore real newlines here.
                restored = message.replace("\x02", "\n")
                if checks:
                    # Multiple legacy fix() calls per check all collapse onto
                    # the last fix line, matching pre-migration behavior.
                    checks[-1].fix = restored
                    if message_key is not None:
                        checks[-1].fix_key = message_key
                        checks[-1].fix_params = message_params
            else:
                # This is a new check result
                check = CheckResult(
                    category=current_category,
                    status=status,
                    message=message,
                    fix=None,
                    message_key=message_key,
                    message_params=message_params,
                )
                checks.append(check)

        # Check for score
        score_match = score_pattern.match(line)
        if score_match:
            score = int(score_match.group(1))
            grade = score_match.group(2)
    
    # Calculate summary
    summary = {
        "pass_count": sum(1 for c in checks if c.status == "PASS"),
        "warn_count": sum(1 for c in checks if c.status == "WARN"),
        "fail_count": sum(1 for c in checks if c.status == "FAIL"),
        "info_count": sum(1 for c in checks if c.status == "INFO"),
        "total_checks": len(checks)
    }
    
    return GeoTestResult(
        url=url,
        score=score,
        grade=grade,
        checks=checks,
        summary=summary
    )
