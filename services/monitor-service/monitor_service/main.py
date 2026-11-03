"""Embeddable GEO monitoring service.

Two audiences:

* Subscription-site users (JWT from the parent site): create monitoring jobs,
  follow progress, read reports. Data is strictly tenant-scoped.
* Operators (MONITOR_ADMIN_TOKEN): platform login states, judge-model health,
  and the cross-tenant job queue.

The monitoring core is the desktop pipeline (tools/geo_record + AI verdicts);
this module is only the HTTP shell around it.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, runner
from .auth import AuthError, verify_admin, verify_token
from .store import JobStore

# static/ lives next to the package dir in both layouts
# (repo: services/monitor-service/static, image: /srv/static).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="GEO Monitor Module", version="1.0.0")
store = JobStore(config.DB_PATH)
worker = runner.Worker(store)


@app.on_event("startup")
def _startup() -> None:
    problems = config.validate()
    if problems:
        raise RuntimeError("monitor-service configuration invalid: " + "; ".join(problems))
    runner.fail_interrupted(store)
    worker.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    worker.stop()


# --------------------------------------------------------------------------
# helpers


def _user_claims(request: Request) -> dict[str, str]:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.startswith("Bearer ") else ""
    if not token:
        token = request.query_params.get("token", "")
    try:
        return verify_token(token, config.MONITOR_JWT_SECRET)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _admin_ok(request: Request) -> None:
    try:
        verify_admin(request.headers.get("authorization", ""), config.MONITOR_ADMIN_TOKEN)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Job view safe for the owning tenant (no internal paths)."""
    has_report = bool(job.get("report_dir")) and (Path(job["report_dir"]) / "record.html").is_file()
    return {
        "id": job["id"],
        "brand": job["brand"],
        "status": job["status"],
        "total_questions": job["total_questions"],
        "completed_questions": job["completed_questions"],
        "error": job["error"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "report_ready": has_report,
    }


def _require_owned_job(job_id: str, tenant_id: str) -> dict[str, Any]:
    job = store.get(job_id, tenant_id=tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


# --------------------------------------------------------------------------
# user API (subscription-site identity bridge)


@app.get("/api/me")
def me(request: Request) -> dict[str, Any]:
    return _user_claims(request)


@app.post("/api/jobs", status_code=202)
def create_job(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    claims = _user_claims(request)
    try:
        validated = runner.geo_record.validate_config(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(validated["questions"]) > config.MONITOR_MAX_QUESTIONS:
        raise HTTPException(status_code=422,
                            detail=f"单次最多 {config.MONITOR_MAX_QUESTIONS} 个问题")
    try:
        runner.request_quota(claims["tenant_id"], len(validated["questions"]))
    except runner.QuotaDenied as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    job = store.create(tenant_id=claims["tenant_id"], user_id=claims["user_id"],
                       config=validated)
    return _public_job(job)


@app.post("/api/questions/generate")
def questions_generate(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    _user_claims(request)
    brand = str(payload.get("brand") or "").strip()
    article_urls = [str(u).strip() for u in payload.get("article_urls") or [] if str(u).strip()]
    keywords = [str(k).strip() for k in payload.get("keywords") or [] if str(k).strip()]
    if not brand:
        raise HTTPException(status_code=422, detail="brand 必填")
    try:
        questions = runner.generate_questions_for(brand, article_urls, keywords)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"questions": questions}


@app.get("/api/jobs")
def list_jobs(request: Request, limit: int = 20) -> dict[str, Any]:
    claims = _user_claims(request)
    jobs = store.list(claims["tenant_id"], limit=limit)
    return {"jobs": [_public_job(job) for job in jobs]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    claims = _user_claims(request)
    job = _require_owned_job(job_id, claims["tenant_id"])
    return _public_job(job)


@app.get("/api/jobs/{job_id}/report")
def job_report(job_id: str, request: Request):
    claims = _user_claims(request)
    job = _require_owned_job(job_id, claims["tenant_id"])
    path = Path(job["report_dir"]) / "record.html" if job.get("report_dir") else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="报告尚未生成")
    return FileResponse(path, media_type="text/html; charset=utf-8")


@app.get("/api/jobs/{job_id}/results")
def job_results(job_id: str, request: Request):
    claims = _user_claims(request)
    job = _require_owned_job(job_id, claims["tenant_id"])
    path = Path(job["report_dir"]) / "results.json" if job.get("report_dir") else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="结果尚未生成")
    return FileResponse(path, media_type="application/json; charset=utf-8")


@app.get("/api/platform-status")
def platform_status(request: Request) -> dict[str, Any]:
    """Customer-facing readiness: named platforms, no operator detail."""
    _user_claims(request)
    try:
        rows = _fetch_sessions()
    except RuntimeError as exc:
        return {"ready": False, "detail": str(exc), "platforms": []}
    from session_status import session_ready, session_label  # noqa: E402
    platforms = [{
        "engine": row.get("engine"),
        "ready": session_ready(row),
        "label": session_label(row),
    } for row in rows]
    return {"ready": all(p["ready"] for p in platforms), "platforms": platforms}


# --------------------------------------------------------------------------
# operator API


def _fetch_sessions() -> list[dict[str, Any]]:
    from geo_record import _check_sessions  # noqa: E402
    try:
        return _check_sessions(config.BROWSER_SERVICE_URL)
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc


@app.get("/api/admin/jobs")
def admin_jobs(request: Request, limit: int = 50) -> dict[str, Any]:
    _admin_ok(request)
    return {"jobs": [_public_job(job) | {"tenant_id": job["tenant_id"],
                                         "user_id": job["user_id"]}
                     for job in store.list_all(limit=limit)]}


@app.get("/api/admin/browser-sessions")
def admin_browser_sessions(request: Request) -> dict[str, Any]:
    _admin_ok(request)
    from session_status import complete_session_results, session_label  # noqa: E402
    from geo_record import ENGINES  # noqa: E402
    try:
        rows = _fetch_sessions()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    full = complete_session_results(rows, ENGINES)
    return {"sessions": [{"engine": engine, **info, "label": session_label(info)}
                         for engine, info in full.items()]}


@app.post("/api/admin/model/test")
def admin_model_test(request: Request) -> dict[str, Any]:
    _admin_ok(request)
    try:
        runner.preflight_model()
    except (ValueError, RuntimeError, OSError) as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "model": config.AI_MODEL, "wire_api": config.AI_WIRE_API}


@app.get("/api/admin/model")
def admin_model(request: Request) -> dict[str, Any]:
    _admin_ok(request)
    return {
        "base_url": config.AI_BASE_URL,
        "model": config.AI_MODEL,
        "wire_api": config.AI_WIRE_API,
        "api_key_set": bool(config.AI_API_KEY),
    }


# --------------------------------------------------------------------------
# embeddable UI


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    return HTMLResponse("<script>location.replace('/app/')</script>")


app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="app")


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, Any]:
    return {"ok": True}
