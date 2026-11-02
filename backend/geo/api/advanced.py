"""Advanced GEO check endpoints.

Wraps the 6 advanced modes from root geo_checker.py behind tier-gated HTTP
endpoints. Each endpoint:
  - Validates the URL / entity name.
  - Resolves the caller's membership (anonymous → free).
  - Rejects with 402 if the mode requires a higher tier than the caller has.
  - Calls the corresponding advanced_runners function in-process.
  - Maps RuntimeError (missing/invalid API key) → 503 so the frontend can tell
    the user it's a server-side configuration issue, not bad input.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from starlette.responses import FileResponse
from geo.models.advanced import (
    CompareRequest,
    CompareResponse,
    CrawlTestRequest,
    CrawlTestResponse,
    AuthorityAuditRequest,
    AuthorityAuditResponse,
    CitationCheckRequest,
    CitationCheckResponse,
    AiVisibilityRequest,
    AiVisibilityResponse,
    EntityAuditRequest,
    EntityAuditResponse,
    AeoVisibilityRequest,
    AeoVisibilityResponse,
    CompetitiveIntelRequest,
    CompetitiveIntelResponse,
    MODE_MIN_TIER,
    TIER_RANK,
)
from geo.services import advanced_runners
from geo.utils.validator import validate_url, sanitize_url
from geo.utils.error_handler import AppException
from geo.utils.request_log import request_log
from geo.api.geo import _resolve_membership_from_request


router = APIRouter()


def _ensure_tier(request: Request, mode_key: str) -> None:
    """Raise 402 if the caller's tier is below the mode's minimum."""
    min_tier = MODE_MIN_TIER.get(mode_key)
    if not min_tier:
        raise AppException(status_code=500, message=f"unknown mode {mode_key}")
    membership, _user_id = _resolve_membership_from_request(request)
    caller_rank = TIER_RANK.get(membership.slug, 0)
    needed_rank = TIER_RANK.get(min_tier, 99)
    if caller_rank < needed_rank:
        raise AppException(
            status_code=402,
            message=f"'{mode_key}' requires {min_tier} tier or higher",
            details={"current_tier": membership.slug, "required_tier": min_tier},
        )


def _check_url(url: str) -> str:
    if not validate_url(url):
        raise AppException(status_code=400, message="Invalid URL format")
    return sanitize_url(url)


async def _run_or_raise(fn, *args, **kwargs):
    # Runners make 10s–minutes of blocking HTTP calls. Offload to FastAPI's
    # threadpool so the event loop stays free for other requests.
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except RuntimeError as e:
        # API key missing / invalid. 503 = service unavailable on our side.
        raise AppException(status_code=503, message=str(e))
    except ValueError as e:
        raise AppException(status_code=400, message=str(e))
    except Exception as e:
        raise AppException(status_code=500, message=f"advanced check failed: {e}")


def _log_ctx(request: Request, mode: str, url: str):
    """Pull user_id + tier from the auth context and build the request_log CM."""
    membership, user_id = _resolve_membership_from_request(request)
    return request_log(
        f"check.advanced.{mode}",
        mode,
        url,
        user_id=user_id,
        tier=membership.slug if membership else "free",
    )


@router.post("/check/advanced/compare")
async def advanced_compare(body: CompareRequest, request: Request):
    _ensure_tier(request, "compare")
    clean_urls = [_check_url(u) for u in body.urls]
    with _log_ctx(request, "compare", "+".join(clean_urls)) as rec:
        rec["urls"] = clean_urls

        # Check Redis cache first — if hit, return the full result immediately
        # so existing clients (curl / old frontend) still work without polling.
        from geo.services import cache_service
        identity = {"url": "+".join(sorted(clean_urls)), "urls": sorted(clean_urls)}
        key = cache_service.make_cache_key("compare", identity.get("url", ""), extra=identity)
        cached = cache_service.get_cached_report(key)
        if cached is not None:
            return CompareResponse(**cached)

        # Cache miss — start background task, return task_id immediately.
        task_id = advanced_runners.start_compare_task(clean_urls)
        rec["task_id"] = task_id
        return {"task_id": task_id, "status": "running"}


@router.get("/check/advanced/compare/{task_id}")
async def advanced_compare_poll(task_id: str):
    """Poll for compare result by task_id."""
    task = advanced_runners.get_entity_task(task_id)
    status = task.get("status")
    if status == "not_found":
        raise AppException(status_code=404, message="Task not found")
    if status == "done":
        return CompareResponse(**task["result"])
    if status == "error":
        raise AppException(status_code=500, message=task["error"])
    return {"task_id": task_id, "status": "running"}


@router.post("/check/advanced/crawl-test", response_model=CrawlTestResponse)
async def advanced_crawl_test(body: CrawlTestRequest, request: Request):
    _ensure_tier(request, "crawlTest")
    clean_url = _check_url(body.url)
    with _log_ctx(request, "crawl-test", clean_url):
        data = await _run_or_raise(advanced_runners.run_crawl_test, clean_url)
        return CrawlTestResponse(**data)


@router.post("/check/advanced/authority", response_model=AuthorityAuditResponse)
async def advanced_authority(body: AuthorityAuditRequest, request: Request):
    _ensure_tier(request, "authority")
    clean_url = _check_url(body.url)
    with _log_ctx(request, "authority", clean_url):
        data = await _run_or_raise(advanced_runners.run_authority_audit, clean_url)
        return AuthorityAuditResponse(**data)


@router.post("/check/advanced/citation", response_model=CitationCheckResponse)
async def advanced_citation(body: CitationCheckRequest, request: Request):
    _ensure_tier(request, "citation")
    clean_url = _check_url(body.url)
    with _log_ctx(request, "citation", clean_url):
        data = await _run_or_raise(advanced_runners.run_citation_check, clean_url)
        return CitationCheckResponse(**data)


@router.post("/check/advanced/visibility", response_model=AiVisibilityResponse)
async def advanced_visibility(body: AiVisibilityRequest, request: Request):
    _ensure_tier(request, "visibility")
    clean_url = _check_url(body.url)
    with _log_ctx(request, "visibility", clean_url) as rec:
        data = await _run_or_raise(
            advanced_runners.run_ai_visibility,
            clean_url,
            body.custom_queries,
        )
        if body.custom_queries:
            rec["custom_queries"] = body.custom_queries
        return AiVisibilityResponse(**data)


@router.post("/check/advanced/entity")
async def advanced_entity(body: EntityAuditRequest, request: Request):
    _ensure_tier(request, "entity")
    entity_name = body.entity_name.strip()
    entity_type = body.entity_type.strip().lower()
    with _log_ctx(request, "entity", entity_name) as rec:
        rec["entity_type"] = entity_type

        # Check Redis cache first — if hit, return the full result immediately
        # so existing clients (curl / old frontend) still work without polling.
        identity = {"url": entity_name, "entity_type": entity_type}
        from geo.services import cache_service
        key = cache_service.make_cache_key("entity", entity_name, extra=identity)
        cached = cache_service.get_cached_report(key)
        if cached is not None:
            return EntityAuditResponse(**cached)

        # Cache miss — start background task, return task_id immediately.
        task_id = advanced_runners.start_entity_task(entity_name, entity_type)
        rec["task_id"] = task_id
        return {"task_id": task_id, "status": "running"}


@router.get("/check/advanced/entity/{task_id}")
async def advanced_entity_poll(task_id: str):
    """Poll for entity audit result by task_id."""
    task = advanced_runners.get_entity_task(task_id)
    status = task.get("status")
    if status == "not_found":
        from geo.utils.error_handler import AppException
        raise AppException(status_code=404, message="Task not found")
    if status == "done":
        return EntityAuditResponse(**task["result"])
    if status == "error":
        from geo.utils.error_handler import AppException
        raise AppException(status_code=500, message=task["error"])
    return {"task_id": task_id, "status": "running"}


@router.post("/check/advanced/aeo", response_model=AeoVisibilityResponse)
async def advanced_aeo(body: AeoVisibilityRequest, request: Request):
    _ensure_tier(request, "aeo")
    clean_url = _check_url(body.url)
    with _log_ctx(request, "aeo", clean_url):
        data = await _run_or_raise(advanced_runners.run_aeo_visibility, clean_url)
        return AeoVisibilityResponse(**data)


@router.get("/check/advanced/engines/status")
async def engines_status():
    """Return availability of each competitive-intel engine."""
    import os
    engines = {}
    # API engines
    engines["openai"] = {
        "available": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "type": "api",
    }
    engines["perplexity"] = {
        "available": bool(os.environ.get("PERPLEXITY_API_KEY", "").strip()),
        "type": "api",
    }
    engines["kimi"] = {
        "available": bool(os.environ.get("KIMI_API_KEY", "").strip()),
        "type": "api",
    }
    engines["qwen"] = {
        "available": bool(os.environ.get("QWEN_API_KEY", "").strip()),
        "type": "api",
    }
    engines["zhipu"] = {
        "available": bool(os.environ.get("ZHIPU_API_KEY", "").strip()),
        "type": "api",
    }
    # Browser engines — via microservice
    try:
        from browser_engine.client import get_sessions
        for info in get_sessions():
            engines[info["engine"]] = {
                "available": info["has_session"],
                "type": "playwright",
                "has_session": info["has_session"],
                "name": info.get("name", info["engine"]),
            }
    except Exception:
        pass
    return engines


@router.post("/check/advanced/competitive-intel", response_model=CompetitiveIntelResponse)
async def advanced_competitive_intel(body: CompetitiveIntelRequest, request: Request):
    _ensure_tier(request, "competitiveIntel")
    clean_url = _check_url(body.url)
    with _log_ctx(request, "competitive-intel", clean_url) as rec:
        if body.competitor_domains:
            rec["competitor_domains"] = body.competitor_domains
        data = await _run_or_raise(
            advanced_runners.run_competitive_intel,
            clean_url,
            body.competitor_domains,
        )
        return CompetitiveIntelResponse(**data)


# ---------------------------------------------------------------------------
# Video snapshot download
# ---------------------------------------------------------------------------


@router.get("/check/advanced/snapshot/{engine}/{filename:path}")
async def download_snapshot(engine: str, filename: str, request: Request):
    """Download a recorded video snapshot — proxied from browser service."""
    _ensure_tier(request, "competitiveIntel")

    if not all(c.isalnum() or c in "-_" for c in engine):
        raise AppException(status_code=400, message="Invalid engine name")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise AppException(status_code=400, message="Invalid filename")
    if not filename.endswith(".webm"):
        raise AppException(status_code=400, message="Only .webm files are served")

    from browser_engine.client import get_snapshot_url
    import httpx
    from starlette.responses import StreamingResponse

    url = get_snapshot_url(engine, filename)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                raise AppException(status_code=404, message="Snapshot not found")
            resp.raise_for_status()
            return StreamingResponse(
                iter([resp.content]),
                media_type="video/webm",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except AppException:
        raise
    except Exception as e:
        raise AppException(status_code=502, message=f"Browser service error: {e}")
