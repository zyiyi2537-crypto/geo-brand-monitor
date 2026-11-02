from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import StreamingResponse as FAPStreamingResponse
from pydantic import BaseModel
import asyncio
import io
import json
import uuid
import time
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from geo.services.geo_checker import run_geo_check
from geo.services.fix_package import FixPackageGenerator
from geo.services.membership_service import (
    membership_service,
    FREE_CHECK_CATEGORIES,
    ALL_CHECK_CATEGORIES,
)
from geo.services.quota_service import check_and_increment_quota
from geo.services.detection_service import save_detection
from geo.models.geo import GeoTestRequest, GeoTestResult
from geo.models.membership import Membership
from geo.utils.validator import validate_url, sanitize_url
from geo.utils.error_handler import AppException
from geo.utils.request_log import request_log
from geo.api.auth import SECRET_KEY, ALGORITHM
from geo.services.user_service import user_service
import jwt
from jwt import PyJWTError as JWTError
import asyncio
import json
import uuid
import time
from fastapi.responses import StreamingResponse
from typing import Dict, Any, Optional, List, Tuple

# Re-export from the membership service so we don't maintain duplicate lists.
ALL_CATEGORIES = ALL_CHECK_CATEGORIES


def _resolve_membership_from_request(request: Request) -> Tuple[Membership, Optional[int]]:
    """Pull the effective membership and (if any) user_id for the caller.

    If an Authorization: Bearer token is present and valid, returns the user's
    active paid tier and their user_id. Otherwise returns the free tier and
    None. The user_id is needed by callers that want to enforce monthly quota
    via quota_service — returning it here avoids decoding the JWT twice.
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if username:
                user = user_service.get_user_by_username(username)
                if user:
                    return membership_service.get_effective_membership(user.id), user.id
        except JWTError:
            pass
    free = membership_service.get_membership_by_slug("free")
    if free is None:
        raise AppException(status_code=500, message="Free membership tier not initialized")
    return free, None


def _locked_for(membership: Membership) -> List[str]:
    allowed = membership.allowed_check_categories
    if allowed is None:
        return []
    allowed_set = set(allowed)
    return [c for c in ALL_CATEGORIES if c not in allowed_set]


_BAD_URL_MESSAGE = "Unable to analyze this URL. Please check the address and try again."


async def _run_check_or_400(
    rec: Dict[str, Any],
    *args,
    **kwargs,
) -> GeoTestResult:
    """Run `run_geo_check` in a worker thread and translate any unhandled
    failure into a user-friendly 400.

    `validate_url` at the endpoint entry now rejects obviously-bad input
    (non-ASCII, bad scheme, hostless URLs) before we get here, but the checker
    can still blow up on a well-formed URL that doesn't actually resolve /
    returns garbage (DNS failure, timeout, empty body, malformed HTML). Leaking
    "list index out of range" to end users is never useful, so we preserve the
    original exception in the request log's `raw_error` field (request_log
    overwrites `error` with the re-raised AppException, so we need a distinct
    key) and surface a canonical English message that the i18n layer localizes
    for the caller.
    """
    try:
        return await asyncio.to_thread(run_geo_check, *args, **kwargs)
    except AppException:
        raise
    except Exception as exc:
        rec["raw_error"] = f"{type(exc).__name__}: {exc}"
        raise AppException(status_code=400, message=_BAD_URL_MESSAGE)


def _strip_locked_checks(result: GeoTestResult, locked: List[str]) -> GeoTestResult:
    """Return a copy of `result` with locked categories hidden from `checks`.

    The full 25 categories always run now — even for free / anonymous callers —
    so that `score` reflects the real state of the site instead of an
    artificially high 5-category average. To keep the UI behavior unchanged,
    we drop the locked categories' check details before handing the response
    to the client and recompute `summary` counts over the visible checks. The
    top-level `score` and `grade` are preserved because the whole point is
    that non-member users see a realistic (usually lower) number.

    Must always copy: `run_geo_check` may return a cached object shared across
    tiers, and mutating it would poison the cache for a later paid caller.
    """
    if not locked:
        return result
    locked_set = set(locked)
    stripped = result.model_copy(deep=True)
    stripped.checks = [c for c in stripped.checks if c.category not in locked_set]
    stripped.summary = {
        "pass_count": sum(1 for c in stripped.checks if c.status == "PASS"),
        "warn_count": sum(1 for c in stripped.checks if c.status == "WARN"),
        "fail_count": sum(1 for c in stripped.checks if c.status == "FAIL"),
        "info_count": sum(1 for c in stripped.checks if c.status == "INFO"),
        "total_checks": len(stripped.checks),
    }
    return stripped


# Fix recommendations are a paid perk: only starter / growth / scale tiers see
# them. Lower tiers (free, pro) get include_fix forced to False so the fix text
# never leaves the backend — frontend gating alone would be bypassable.
_FIX_ALLOWED_TIERS = frozenset({"starter", "growth", "scale"})


def _fix_allowed(membership: Membership) -> bool:
    return membership.slug in _FIX_ALLOWED_TIERS


ANON_COOKIE_NAME = "geo_anon_id"
# 1 year. Long enough that the monthly bucket is the limiting factor, not the
# cookie lifetime; short enough that it eventually rotates if a browser stays
# logged out forever.
ANON_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _ensure_anon_client_id(request: Request, response: Response) -> str:
    """Read or mint the `geo_anon_id` cookie used to bucket anonymous usage.

    If the request already carries the cookie we reuse it; otherwise we
    generate a fresh UUID4 and set it on the outgoing response so the next
    request lands in the same bucket. The cookie is HTTP-only — frontend JS
    has no need to read it, and httponly avoids accidental leakage via XSS.
    """
    existing = request.cookies.get(ANON_COOKIE_NAME)
    if existing:
        return existing
    new_id = uuid.uuid4().hex
    response.set_cookie(
        key=ANON_COOKIE_NAME,
        value=new_id,
        max_age=ANON_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return new_id


router = APIRouter()

# Store active tasks for SSE
tasks: Dict[str, Dict[str, Any]] = {}

async def geo_check_task(
    task_id: str,
    url: str,
    include_fix: bool,
    allowed_categories: Optional[List[str]] = None,
    tier: Optional[str] = None,
    locked_categories: Optional[List[str]] = None,
    user_id: Optional[int] = None,
    mode: str = "free",
):
    """Background task to run GEO check and store results"""
    print(f"Starting GEO check for {url}")
    try:
        # Check if task still exists
        if task_id not in tasks:
            print(f"Task {task_id} no longer exists")
            return
            
        # Update task status to running
        tasks[task_id]["status"] = "running"
        tasks[task_id]["progress"] = 0
        print(f"Task {task_id} status updated to running")
        
        # Define progress callback function
        def progress_callback(progress):
            print(f"Progress callback called with progress: {progress}%")
            if task_id in tasks:
                tasks[task_id]["progress"] = progress
                print(f"Task {task_id} progress updated to {progress}%")
        
        # Run GEO check with progress callback. The checker is synchronous and
        # does blocking IO (HTTP fetches), so offload to a worker thread so the
        # event loop keeps serving other requests.
        print(f"Calling run_geo_check for {url}")
        try:
            result = await asyncio.to_thread(
                run_geo_check,
                url,
                include_fix,
                progress_callback,
                allowed_categories,
                user_id,                                           # L2 DB cache key
                tier if tier is not None else "free",              # L1 cache key part
            )
            # Strip locked categories before we touch `result` again: the
            # underlying run_geo_check may have returned a cached object
            # shared across tiers, and _strip_locked_checks deep-copies so
            # we never mutate that cached instance.
            if locked_categories:
                result = _strip_locked_checks(result, locked_categories)
            if tier is not None:
                result.tier = tier
            if locked_categories is not None:
                result.locked_categories = locked_categories
            print(f"GEO check completed for {url}")
        except KeyboardInterrupt:
            print(f"GEO check interrupted for {url}")
            # Update task status to failed
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = "GEO check was interrupted"
            return
        except Exception as e:
            print(f"GEO check failed for {url}: {str(e)}")
            # Update task status to failed
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e)
            return
        
        # Check if task still exists
        if task_id not in tasks:
            print(f"Task {task_id} no longer exists")
            return
            
        # Update task status to completed
        tasks[task_id]["status"] = "completed"
        tasks[task_id]["progress"] = 100
        # Convert result to dictionary for proper JSON serialization
        tasks[task_id]["result"] = result.model_dump()
        print(f"Task {task_id} status updated to completed")
        print(f"Task {task_id} result: {result}")

        # Persist for logged-in users so the personal center history can
        # display and replay this run. Best-effort — never fail the task.
        if user_id is not None:
            try:
                save_detection(user_id=user_id, result=result, mode=mode)
            except Exception as persist_err:  # pragma: no cover
                print(f"[sse] save_detection failed: {persist_err}")
    except Exception as e:
        # Check if task still exists
        if task_id in tasks:
            # Update task status to failed
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e)
            print(f"Task {task_id} failed with error: {str(e)}")
        else:
            print(f"Task {task_id} no longer exists, error: {str(e)}")

@router.post("/check/anonymous", response_model=GeoTestResult)
async def check_anonymous(body: GeoTestRequest, request: Request, response: Response):
    """Anonymous check — runs the full 25 categories but only exposes the
    free-tier 5 in the response.

    The full run is used so that `score` reflects the site's real GEO state
    (typically lower than the 5-category-only average), which is the whole
    point of this endpoint as a conversion funnel. The 18 locked categories'
    check details are stripped server-side before we respond, so the UI only
    sees what it's allowed to render.

    No monthly quota — anonymous callers can run unlimited checks. Cookie is
    still minted for observability (`request_log` attaches `anon_id`).
    """
    if not validate_url(body.url):
        raise AppException(status_code=400, message="Invalid URL format")
    sanitized_url = sanitize_url(body.url)

    client_id = _ensure_anon_client_id(request, response)

    with request_log("check.anonymous", "default", sanitized_url,
                     anon_id=client_id, tier="free") as rec:
        result = await _run_check_or_400(
            rec,
            sanitized_url,
            False,   # anonymous callers are always free tier — no fix text
            None,    # no progress_callback
            None,    # run all 25 for a realistic score
            None,    # no user_id → L1 Redis only, no L2 DB fallback
            "free",  # tier key
            force_refresh=body.force_refresh,
        )
        locked = [c for c in ALL_CATEGORIES if c not in FREE_CHECK_CATEGORIES]
        result = _strip_locked_checks(result, locked)
        result.tier = "free"
        result.locked_categories = locked
        rec["score"] = result.score
        rec["grade"] = result.grade
        return result


@router.post("/check", response_model=GeoTestResult)
async def check_authenticated(body: GeoTestRequest, request: Request, response: Response):
    """Tiered check: uses the caller's membership to decide quota + display
    gating. Always runs the full 25 categories so the score is tier-independent.

    - Bearer token is optional. Without it, falls back to the free tier (same
      behavior as /check/anonymous but without writing any usage rows).
    - With a valid token, enforces monthly_check_quota.
    - The 23 checks always run regardless of tier; paid categories are
      stripped from the response for tiers that aren't allowed to see them,
      so free / pro callers get a realistic (lower) score but still only see
      the subset of check details their tier is entitled to.
    """
    if not validate_url(body.url):
        raise AppException(status_code=400, message="Invalid URL format")
    sanitized_url = sanitize_url(body.url)

    membership, user_id = _resolve_membership_from_request(request)

    # Logged-in users get the per-tier monthly quota. Anonymous callers (no
    # token or invalid token) are unlimited — still mint the cookie for
    # observability but skip quota enforcement.
    if user_id is not None:
        check_and_increment_quota(user_id, membership)
    else:
        _ensure_anon_client_id(request, response)

    effective_include_fix = body.include_fix and _fix_allowed(membership)
    with request_log("check.authenticated", "default", sanitized_url,
                     user_id=user_id, tier=membership.slug) as rec:
        result = await _run_check_or_400(
            rec,
            sanitized_url,
            effective_include_fix,
            None,             # no progress_callback
            None,             # run all 25 regardless of tier — strip locked details below
            user_id,          # L2 DB fallback
            membership.slug,  # tier key
            force_refresh=body.force_refresh,
        )
        locked = _locked_for(membership)
        result = _strip_locked_checks(result, locked)
        result.tier = membership.slug
        result.locked_categories = locked

        # Persist history for logged-in users only — anonymous runs have no
        # owner to file them under. Best-effort; failures do not affect the
        # response.
        if user_id is not None:
            mode = "advanced" if effective_include_fix else "free"
            save_detection(user_id=user_id, result=result, mode=mode)

        rec["score"] = result.score
        rec["grade"] = result.grade
        rec["fix"] = effective_include_fix
        return result


@router.post("/geo", response_model=GeoTestResult)
async def test_geo(body: GeoTestRequest, request: Request, response: Response):
    """Legacy alias — behaves like /check/anonymous.

    Runs the full 25 categories and strips the 18 locked ones before
    returning (same behavior as /check/anonymous). Kept so existing frontend
    calls to `geoApi.checkGeo` continue to work during the frontend
    migration. No monthly quota — unlimited anonymous checks.
    """
    if not validate_url(body.url):
        raise AppException(status_code=400, message="Invalid URL format")
    sanitized_url = sanitize_url(body.url)

    client_id = _ensure_anon_client_id(request, response)

    with request_log("geo.legacy", "default", sanitized_url,
                     anon_id=client_id, tier="free") as rec:
        result = await _run_check_or_400(
            rec,
            sanitized_url,
            False,   # legacy anonymous alias — free tier, no fix text
            None,    # no progress_callback
            None,    # run all 25 for a realistic score
            None,    # no user_id
            "free",  # tier key
            force_refresh=body.force_refresh,
        )
        locked = [c for c in ALL_CATEGORIES if c not in FREE_CHECK_CATEGORIES]
        result = _strip_locked_checks(result, locked)
        result.tier = "free"
        result.locked_categories = locked
        rec["score"] = result.score
        rec["grade"] = result.grade
        return result

@router.get("/geo/stream")
async def test_geo_stream(
    request: Request,
    url: str,
    include_fix: bool = True,
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Run GEO readiness test and stream results via SSE.

    Tier-aware: if a valid Bearer token is present in the Authorization
    header, runs with that user's allowed categories and enforces quota;
    otherwise runs the free-tier 5 categories.
    """
    print(f"Received SSE request for {url}")
    if not validate_url(url):
        raise AppException(status_code=400, message="Invalid URL format")

    sanitized_url = sanitize_url(url)
    print(f"Sanitized URL: {sanitized_url}")

    membership, user_id = _resolve_membership_from_request(request)

    # Enforce quota before spawning the background task so the 429 surfaces
    # synchronously on the SSE handshake instead of inside the event stream.
    # Only authenticated callers have a per-tier quota; anonymous SSE is
    # unlimited. We still mint `geo_anon_id` for observability and have to
    # remember it here so we can attach it to the StreamingResponse below
    # (set_cookie can't be called from inside the event generator since
    # headers are flushed before yields).
    set_anon_cookie_value: Optional[str] = None
    if user_id is not None:
        check_and_increment_quota(user_id, membership)
    else:
        client_id = request.cookies.get(ANON_COOKIE_NAME)
        if not client_id:
            client_id = uuid.uuid4().hex
            set_anon_cookie_value = client_id

    # All 25 categories run for every tier now; display gating happens via
    # `locked_categories`, which the task strips from `checks[]` before the
    # result is serialized out. This way free / pro callers get a realistic
    # score without ever seeing the paid categories' check details.
    locked = _locked_for(membership)
    # Fix text is a paid perk — force False for any tier below starter so
    # lower tiers never see fix data over the wire, regardless of what the
    # client passed.
    effective_include_fix = include_fix and _fix_allowed(membership)

    task_id = str(uuid.uuid4())
    print(f"Created task ID: {task_id}")

    tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "url": sanitized_url,
        "include_fix": effective_include_fix,
        "tier": membership.slug,
    }
    print(f"Initialized task: {tasks[task_id]}")

    import asyncio
    print(f"Starting background task for {sanitized_url}")
    asyncio.create_task(
        geo_check_task(
            task_id,
            sanitized_url,
            effective_include_fix,
            allowed_categories=None,
            tier=membership.slug,
            locked_categories=locked,
            user_id=user_id,
            mode="advanced" if effective_include_fix else "free",
        )
    )
    print(f"Background task started for {sanitized_url}")
    
    async def event_generator():
        print(f"Starting event generator for task {task_id}")
        try:
            # Send initial status
            print(f"Sending initial status for task {task_id}")
            yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
            
            # Update status to running
            tasks[task_id]["status"] = "running"
            print(f"Updated task status to running: {tasks[task_id]}")
            yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
            # Keep sending status updates every 2 seconds until task is completed or failed
            timeout = 1800  # 1800 seconds (30 minutes) timeout
            start_time = time.time()
            progress = 0
            
            while task_id in tasks:
                # Check if task is completed or failed
                if tasks[task_id]["status"] in ["completed", "failed"]:
                    print(f"Task {task_id} is {tasks[task_id]['status']}, sending final status")
                    yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
                    break
                
                # Check for timeout
                if time.time() - start_time > timeout:
                    print(f"Task {task_id} timed out after {timeout} seconds")
                    if task_id in tasks:
                        tasks[task_id]["status"] = "failed"
                        tasks[task_id]["error"] = f"GEO check timed out after {timeout} seconds"
                        yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
                    break
                
                # Check if progress is 100% but status is still running
                if task_id in tasks and tasks[task_id]["progress"] == 100 and tasks[task_id]["status"] == "running":
                    print(f"Updating task {task_id} status to completed")
                    tasks[task_id]["status"] = "completed"
                    print(f"Sending final status for task {task_id}: completed")
                    yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
                    break
                
                # Check if task has result but status is still running
                if task_id in tasks and "result" in tasks[task_id] and tasks[task_id]["status"] == "running":
                    print(f"Task {task_id} has result, updating status to completed")
                    tasks[task_id]["status"] = "completed"
                    tasks[task_id]["progress"] = 100
                    print(f"Sending final status for task {task_id}: completed")
                    yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
                    break
                
                # Update progress manually to show activity
                progress = min(progress + 5, 90)
                if task_id in tasks:
                    tasks[task_id]["progress"] = progress
                    print(f"Sending progress update for task {task_id}: {progress}%")
                    yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
                
                await asyncio.sleep(2)
            
            # Send final status if task still exists
            if task_id in tasks:
                print(f"Sending final status for task {task_id}: {tasks[task_id]['status']}")
                yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
                # Clean up task after sending final status
                print(f"Cleaning up task {task_id}")
                del tasks[task_id]
            else:
                print(f"Task {task_id} no longer exists")
                # Send completed status if task was removed
                yield f"event: status\ndata: {{\"status\": \"completed\", \"progress\": 100, \"url\": \"{sanitized_url}\", \"include_fix\": {effective_include_fix}}}\n\n"
        except asyncio.CancelledError:
            print(f"Event generator for task {task_id} was cancelled")
            # Clean up task if it still exists
            if task_id in tasks:
                print(f"Cleaning up cancelled task {task_id}")
                del tasks[task_id]
        except Exception as e:
            print(f"Error in event generator for task {task_id}: {str(e)}")
            # Send error status if task still exists
            if task_id in tasks:
                tasks[task_id]["status"] = "failed"
                tasks[task_id]["error"] = f"SSE error: {str(e)}"
                print(f"Sending error status for task {task_id}: {tasks[task_id]['status']}")
                yield f"event: status\ndata: {json.dumps(tasks[task_id], default=str)}\n\n"
                # Clean up task after sending error status
                print(f"Cleaning up task {task_id}")
                del tasks[task_id]
            else:
                # Send error status if task was removed
                yield f"event: status\ndata: {{\"status\": \"failed\", \"error\": \"{str(e)}\", \"url\": \"{sanitized_url}\", \"include_fix\": {effective_include_fix}}}\n\n"
        finally:
            print(f"Event generator for task {task_id} completed")

    
    sse_response = FAPStreamingResponse(event_generator(), media_type="text/event-stream")
    if set_anon_cookie_value is not None:
        sse_response.set_cookie(
            key=ANON_COOKIE_NAME,
            value=set_anon_cookie_value,
            max_age=ANON_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return sse_response


class FixPackageRequest(BaseModel):
    url: str


@router.post("/check/fix-package")
async def download_fix_package(body: FixPackageRequest, request: Request):
    """Generate and stream a ZIP fix package for the given URL.

    Requires starter+ membership. Runs the full 25-category check with fixes
    enabled, then assembles a ZIP containing:
      - fix-manifest.json     (all fix items with metadata)
      - robots.txt           (if robots issues found)
      - llms.txt / llms-full.txt
      - patches/meta-tags-patch.html
      - patches/json-ld-patch.html
      - patches/security-headers-nginx.conf / .htaccess
      - humans.txt
      - sitemap.xml.example
      - content/gseo-suggestions.md
      - README.md
    """
    if not validate_url(body.url):
        raise AppException(status_code=400, message="Invalid URL format")
    sanitized_url = sanitize_url(body.url)

    membership, user_id = _resolve_membership_from_request(request)

    if not _fix_allowed(membership):
        raise AppException(
            status_code=403,
            message="This feature requires a starter or higher membership.",
        )

    with request_log(
        "fix_package.download",
        "default",
        sanitized_url,
        user_id=user_id,
        tier=membership.slug,
    ) as rec:
        # Build cache key to check if we already have results
        from geo.services.geo_checker import _build_cache_key
        cache_key = _build_cache_key(
            sanitized_url,
            True,  # include_fix
            None,  # all categories
            membership.slug
        )
        
        # Check cache first
        from geo.services.cache_service import get_cached_report
        cached_result = get_cached_report(cache_key)
        
        if cached_result:
            # Use cached result
            from geo.models.geo import GeoTestResult, CheckResult
            # Convert dict to GeoTestResult, handling nested CheckResult objects
            cached_result['checks'] = [CheckResult(**check) for check in cached_result.get('checks', [])]
            result = GeoTestResult(**cached_result)
            rec["score"] = result.score
            rec["cache_hit"] = True
        else:
            # No cache, run the check
            result = await _run_check_or_400(
                rec,
                sanitized_url,
                True,    # always include fixes
                None,    # no progress_callback
                None,    # run all 25 categories
                user_id,
                membership.slug,
            )
            rec["score"] = result.score
            rec["cache_hit"] = False

    locale = request.headers.get("X-Locale", "en")
    generator = FixPackageGenerator(result, locale=locale)
    zip_bytes = generator.build_zip()

    from urllib.parse import urlparse
    parsed = urlparse(sanitized_url)
    domain = (parsed.netloc or sanitized_url).replace(":", "_").replace("/", "_")
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M")
    filename = f"geo-fix-{domain}-{timestamp}.zip"

    return FAPStreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
