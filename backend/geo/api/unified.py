"""Unified GEO monitor API.

API adapters are preferred, while browser workers are an explicit fallback
for providers without an API. The job contract is transport agnostic so the
web UI can show progress, evidence and partial failures in one view.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field, field_validator
from geo.api.auth import require_admin
from geo.database import settings

log = logging.getLogger("geo.unified")
router = APIRouter(prefix="/unified", dependencies=[Depends(require_admin)])

API_ADAPTERS: dict[str, tuple[str, str, str]] = {
    "deepseek": ("DeepSeek", "", ""),
    "doubao": ("豆包", "", ""),
    "yuanbao": ("元宝", "", ""),
    "wenxin": ("文心一言", "", ""),
    "qwen": ("通义千问", "", ""),
}

BROWSER_ENGINES: dict[str, tuple[str, str]] = {
    "deepseek": ("DeepSeek", "CN browser"),
    "doubao": ("Doubao", "CN browser"),
    "qwen": ("Qwen", "CN browser"),
    "wenxin": ("Wenxin", "CN browser"),
    "yuanbao": ("Yuanbao", "CN browser"),
}

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = asyncio.Lock()
_job_semaphore = asyncio.Semaphore(int(os.environ.get("UNIFIED_MAX_CONCURRENT", "4")))
_REPORT_DIR = Path(os.environ.get("UNIFIED_REPORT_DIR", str(Path(__file__).resolve().parents[3] / "reports" / "unified")))
_CONFIG_PATH = Path(os.environ.get("UNIFIED_CONFIG_PATH", str(Path(__file__).resolve().parents[2] / "data" / "unified-providers.enc")))
_config_lock = asyncio.Lock()


class ProviderConfig(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=4096)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment or parts.query:
            raise ValueError("请输入完整的 HTTPS 请求地址")
        return value


def _cipher() -> Fernet:
    secret = os.environ.get("UNIFIED_CREDENTIAL_KEY") or settings.SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def _load_configs() -> dict[str, dict[str, str]]:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_cipher().decrypt(_CONFIG_PATH.read_bytes()))
    except (OSError, InvalidToken, ValueError) as exc:
        log.error("Unable to read unified provider configuration: %s", type(exc).__name__)
        raise HTTPException(500, "无法读取模型配置，请检查服务器加密密钥") from exc


def _save_configs(configs: dict[str, dict[str, str]]) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = _CONFIG_PATH.with_name(_CONFIG_PATH.name + ".tmp")
    temp.write_bytes(_cipher().encrypt(json.dumps(configs, ensure_ascii=False).encode()))
    os.replace(temp, _CONFIG_PATH)


class UnifiedJobRequest(BaseModel):
    brand: str = Field(..., min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    article_urls: list[str] = Field(default_factory=list, max_length=50)
    queries: list[str] = Field(..., min_length=1, max_length=100)
    engines: list[str] = Field(default_factory=list, max_length=20)
    mode: Literal["auto", "api", "browser"] = "auto"
    competitor_brands: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("brand")
    @classmethod
    def clean_brand(cls, value: str) -> str:
        return value.strip()

    @field_validator("queries", "aliases", "article_urls", "competitor_brands")
    @classmethod
    def clean_list(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            item = item.strip()
            if item and item.lower() not in seen:
                cleaned.append(item)
                seen.add(item.lower())
        return cleaned


class ProviderOut(BaseModel):
    id: str
    name: str
    transport: Literal["api", "browser"]
    status: Literal["ready", "fallback", "needs_key", "needs_login", "disabled"]
    configured: bool
    reason: str


def _api_ready(provider_id: str) -> bool:
    cfg = _load_configs().get(provider_id, {})
    return bool(cfg.get("endpoint") and cfg.get("model") and cfg.get("api_key"))


def _browser_available() -> bool:
    return bool(os.getenv("BROWSER_SERVICE_URL", "").strip() or os.getenv("BROWSER_SERVICE_CN", "").strip())


def _provider_catalog() -> list[ProviderOut]:
    out: list[ProviderOut] = []
    for provider_id, (name, env_key, _class_path) in API_ADAPTERS.items():
        ready = _api_ready(provider_id)
        out.append(ProviderOut(id=provider_id, name=name, transport="api",
                               status="ready" if ready else "needs_key",
                               configured=ready,
                               reason="已保存配置" if ready else "尚未配置 API"))
    return out


@router.get("/providers")
async def providers() -> dict[str, Any]:
    catalog = _provider_catalog()
    return {
        "providers": [p.model_dump() for p in catalog],
        "api_ready": sum(p.status == "ready" for p in catalog),
        "browser_fallback": sum(p.status == "fallback" for p in catalog),
        "login_required": sum(p.status == "needs_login" for p in catalog),
        "policy": "api_first",
    }


@router.get("/providers/{provider_id}/config")
async def get_provider_config(provider_id: str) -> dict[str, Any]:
    if provider_id not in API_ADAPTERS:
        raise HTTPException(404, "未知平台")
    cfg = _load_configs().get(provider_id, {})
    return {"endpoint": cfg.get("endpoint", ""), "model": cfg.get("model", ""), "has_key": bool(cfg.get("api_key"))}


@router.put("/providers/{provider_id}/config")
async def save_provider_config(provider_id: str, payload: ProviderConfig) -> dict[str, bool]:
    if provider_id not in API_ADAPTERS:
        raise HTTPException(404, "未知平台")
    async with _config_lock:
        configs = _load_configs()
        key = payload.api_key.strip() or configs.get(provider_id, {}).get("api_key", "")
        if not key or not payload.model.strip():
            raise HTTPException(400, "请填写模型名称和 API Key")
        configs[provider_id] = {"endpoint": payload.endpoint, "model": payload.model.strip(), "api_key": key}
        _save_configs(configs)
    return {"ok": True}


@router.delete("/providers/{provider_id}/config")
async def delete_provider_config(provider_id: str) -> dict[str, bool]:
    if provider_id not in API_ADAPTERS:
        raise HTTPException(404, "未知平台")
    async with _config_lock:
        configs = _load_configs()
        configs.pop(provider_id, None)
        _save_configs(configs)
    return {"ok": True}


@router.get("/browser-sessions")
async def browser_sessions() -> dict[str, Any]:
    base = os.getenv("BROWSER_SERVICE_URL", "").strip() or os.getenv("BROWSER_SERVICE_CN", "").strip()
    if not base:
        return {"available": False, "sessions": []}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(base.rstrip("/") + "/sessions")
            response.raise_for_status()
            sessions = response.json()
        return {"available": True, "sessions": [s for s in sessions if s.get("engine") in BROWSER_ENGINES]}
    except (httpx.HTTPError, ValueError, TypeError):
        return {"available": False, "sessions": []}


def _default_engines() -> list[str]:
    providers = _provider_catalog()
    ready_api = [p.id for p in providers if p.status == "ready"]
    if ready_api:
        return ready_api
    return [p.id for p in providers if p.transport == "browser" and p.status == "fallback"]


def _normalise_engine(engine: str) -> str:
    aliases = {"Qwen": "qwen", "qwen": "qwen", "Doubao": "doubao", "Wenxin": "wenxin", "Yuanbao": "yuanbao"}
    return aliases.get(engine.strip(), engine.strip().lower())


def _find_api_adapter(engine: str):
    spec = API_ADAPTERS.get(engine)
    if not spec or not spec[2]:
        return None
    import importlib
    module_path, class_name = spec[2].rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


async def _run_api_legacy(engine: str, query: str) -> dict[str, Any]:
    if engine == "doubao_api":
        key = os.getenv("ARK_API_KEY", "").strip()
        bot_id = os.getenv("DOUBAO_BOT_ID", "").strip()
        if not key or not bot_id:
            return {"engine": engine, "query": query, "answer": "", "citations": [], "error": "api_key_missing"}
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    "https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": bot_id, "messages": [{"role": "user", "content": query}]},
                )
            if response.status_code != 200:
                return {"engine": engine, "query": query, "answer": "", "citations": [], "error": f"http_{response.status_code}"}
            data = response.json()
            message = (data.get("choices") or [{}])[0].get("message", {}) or {}
            refs = data.get("references") or message.get("references") or []
            citations = [{"url": ref.get("url", ""), "title": ref.get("title", ""), "position": i + 1} for i, ref in enumerate(refs) if isinstance(ref, dict) and ref.get("url")]
            return {"engine": engine, "query": query, "answer": message.get("content", "") or "", "citations": citations, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"engine": engine, "query": query, "answer": "", "citations": [], "error": str(exc)}

    adapter = _find_api_adapter(engine)
    if adapter is None:
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": "api_not_available"}
    try:
        result = await asyncio.to_thread(lambda: asyncio.run(adapter.search(query)))
        return {"engine": engine, "query": query, "answer": result.answer or "",
                "citations": [c.__dict__ for c in (result.citations or [])], "error": result.error}
    except Exception as exc:  # noqa: BLE001
        log.exception("API engine %s failed", engine)
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": str(exc)}


async def _run_api(engine: str, query: str) -> dict[str, Any]:
    cfg = _load_configs().get(engine, {})
    result = {"engine": engine, "query": query, "answer": "", "citations": []}
    if not all(cfg.get(k) for k in ("endpoint", "model", "api_key")):
        return {**result, "error": "api_key_missing"}
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            response = await client.post(cfg["endpoint"], headers={"Authorization": "Bearer " + cfg["api_key"]},
                                         json={"model": cfg["model"], "messages": [{"role": "user", "content": query}]})
        if response.status_code != 200:
            return {**result, "error": f"API 请求失败 (HTTP {response.status_code})"}
        data = response.json()
        message = (data.get("choices") or [{}])[0].get("message", {}) or {}
        refs = data.get("references") or message.get("references") or []
        citations = [{"url": ref.get("url", ""), "title": ref.get("title", "")} for ref in refs if isinstance(ref, dict) and ref.get("url")]
        return {**result, "answer": message.get("content") or "", "citations": citations, "error": None}
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        return {**result, "error": f"请求或解析失败: {type(exc).__name__}"}


async def _run_browser(engine: str, query: str) -> dict[str, Any]:
    base_url = os.getenv("BROWSER_SERVICE_URL", "").strip()
    if not base_url:
        domestic = {"deepseek", "doubao", "qwen", "wenxin", "yuanbao"}
        base_url = os.getenv("BROWSER_SERVICE_CN" if engine in domestic else "BROWSER_SERVICE_GLOBAL", "").strip()
    if not base_url:
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": "browser_service_not_configured"}
    browser_engine = "qwen" if engine == "qwen_browser" else engine
    try:
        async with httpx.AsyncClient(timeout=330) as client:
            response = await client.post(f"{base_url.rstrip('/')}/search", json={"engine": browser_engine, "query": query})
        if response.status_code >= 400:
            return {"engine": engine, "query": query, "answer": "", "citations": [], "error": f"browser_http_{response.status_code}"}
        data = response.json()
        return {"engine": engine, "query": query, "answer": data.get("answer", "") or "",
                "citations": data.get("citations", []) or [], "source_url": data.get("source_url"),
                "error": data.get("error")}
    except Exception as exc:  # noqa: BLE001
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": str(exc)}


def _rank_answer(answer: str, brand: str, aliases: list[str], competitors: list[str]) -> tuple[bool, int | None, list[str]]:
    text = answer or ""
    target_names = {brand.lower(), *(a.lower() for a in aliases)}
    hits: list[tuple[int, str]] = []
    for name in [brand, *aliases, *competitors]:
        if not name:
            continue
        match = re.search(re.escape(name), text, flags=re.IGNORECASE)
        if match:
            hits.append((match.start(), name))
    hits.sort(key=lambda item: item[0])
    mention = any(name.lower() in target_names for _, name in hits)
    rank = next((i + 1 for i, (_, name) in enumerate(hits) if name.lower() in target_names), None)
    return mention, rank, [name for _, name in hits]


def _canonical_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
            return ""
        host = parts.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), host, path, "", ""))
    except ValueError:
        return ""


def _persist_report(job: dict[str, Any]) -> str:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORT_DIR / f"{job['id']}.json"
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _summarise(job: dict[str, Any]) -> dict[str, Any]:
    rows = job.get("results", [])
    successful = [row for row in rows if not row.get("error") and row.get("answer")]
    mentioned = [row for row in successful if row.get("target_mentioned")]
    domains = Counter()
    brands = Counter()
    engine_mentions = Counter()
    engine_results = Counter()
    cited_articles = Counter()
    for row in successful:
        engine_name = row.get("provider_name") or row.get("engine") or "unknown"
        engine_results[engine_name] += 1
        if row.get("target_mentioned"):
            engine_mentions[engine_name] += 1
        for citation in row.get("citations", []):
            url = citation.get("url", "")
            domain = citation.get("domain") or (url.split("/")[2] if url.startswith("http") else "")
            if domain:
                domains[domain.replace("www.", "")] += 1
        for brand in row.get("mentioned_names", []):
            brands[brand] += 1
        for article_url in {item.get("article_url", "") for item in row.get("cited_articles", [])}:
            if article_url:
                cited_articles[article_url] += 1
    rank_values = [row["target_rank"] for row in mentioned if row.get("target_rank")]
    article_cited_rows = sum(bool(row.get("cited_articles")) for row in successful)
    return {"total": len(rows), "successful": len(successful), "failed": len(rows) - len(successful),
            "mention_rate": round((len(mentioned) / len(successful)) * 100, 1) if successful else 0,
            "article_citation_rate": round((article_cited_rows / len(successful)) * 100, 1) if successful else 0,
            "average_target_rank": round(sum(rank_values) / len(rank_values), 1) if rank_values else None,
            "top_cited_articles": [{"name": name, "count": count} for name, count in cited_articles.most_common(10)],
            "top_citation_domains": [{"name": name, "count": count} for name, count in domains.most_common(10)],
            "brand_ranking": [{"name": name, "mentions": count, "rank": i + 1} for i, (name, count) in enumerate(brands.most_common(10))],
            "engine_mentions": [{"name": name, "count": count} for name, count in engine_mentions.most_common(10)],
            "engine_results": [{"name": name, "count": count} for name, count in engine_results.most_common(10)],
            "mention_breakdown": [{"name": "已提及", "count": len(mentioned)}, {"name": "未提及", "count": max(0, len(successful) - len(mentioned))}]}


async def _run_job(job_id: str, request: UnifiedJobRequest) -> None:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["started_at"] = datetime.now(timezone.utc).isoformat()

    catalog = {p.id: p for p in _provider_catalog()}
    engines = [_normalise_engine(e) for e in (request.engines or _default_engines())]
    results: list[dict[str, Any]] = []

    async def one(engine: str, query: str) -> None:
        async with _job_semaphore:
            provider = catalog.get(engine)
            api_candidate = engine in API_ADAPTERS and _api_ready(engine)
            use_api = request.mode == "api" or (request.mode == "auto" and api_candidate)
            if request.mode == "browser":
                use_api = False
            if request.mode == "api" and not api_candidate:
                result = {"engine": engine, "query": query, "answer": "", "citations": [], "error": "api_key_missing"}
            elif use_api:
                result = await _run_api(engine, query)
                # In auto mode an API outage should not make the whole check
                # empty when a saved browser session is available.
                if request.mode == "auto" and result.get("error") and _browser_available():
                    api_error = result.get("error")
                    browser_result = await _run_browser(engine, query)
                    if not browser_result.get("error"):
                        result = browser_result
                        result["fallback_from"] = "api"
                        result["api_error"] = api_error
            else:
                result = await _run_browser(engine, query)
            mention, rank, names = _rank_answer(result.get("answer", ""), request.brand, request.aliases, request.competitor_brands)
            result["provider_name"] = provider.name if provider else engine
            result["transport"] = "browser" if result.get("fallback_from") else ("api" if use_api else "browser")
            result["target_mentioned"] = mention
            result["target_rank"] = rank
            result["mentioned_names"] = names
            article_lookup = {_canonical_url(url): url for url in request.article_urls if _canonical_url(url)}
            result["cited_articles"] = [
                {"article_url": article_lookup[_canonical_url(citation.get("url", ""))], "citation": citation}
                for citation in result.get("citations", [])
                if isinstance(citation, dict) and _canonical_url(citation.get("url", "")) in article_lookup
            ]
            async with _jobs_lock:
                results.append(result)
                job = _jobs.get(job_id)
                if job:
                    job["results"] = results.copy()
                    job["progress"] = round((len(results) / max(1, len(engines) * len(request.queries))) * 100)

    await asyncio.gather(*(one(engine, query) for query in request.queries for engine in engines))
    async with _jobs_lock:
        job = _jobs.get(job_id)
        snapshot = None
        if job:
            job["summary"] = _summarise(job)
            job["status"] = "completed" if not any(r.get("error") for r in results) else "partial"
            job["progress"] = 100
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
            snapshot = dict(job)
    if snapshot:
        try:
            report_file = await asyncio.to_thread(_persist_report, snapshot)
            async with _jobs_lock:
                if _jobs.get(job_id):
                    _jobs[job_id]["report_url"] = f"/api/unified/reports/{job_id}"
                    _jobs[job_id]["report_file"] = report_file
        except Exception:  # noqa: BLE001
            log.exception("failed to persist unified report %s", job_id)


@router.post("/jobs", status_code=202)
async def create_job(request: UnifiedJobRequest) -> dict[str, Any]:
    engines = [_normalise_engine(e) for e in (request.engines or _default_engines())]
    if not engines:
        raise HTTPException(400, "no_engine_available")
    known = {p.id for p in _provider_catalog()}
    unknown = [e for e in engines if e not in known]
    if unknown:
        raise HTTPException(400, f"unknown engines: {unknown}")
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "queued", "progress": 0, "brand": request.brand,
           "aliases": request.aliases, "article_urls": request.article_urls,
           "queries": request.queries, "engines": engines,
           "mode": request.mode, "competitor_brands": request.competitor_brands,
           "results": [], "summary": {}, "created_at": datetime.now(timezone.utc).isoformat()}
    async with _jobs_lock:
        _jobs[job_id] = job
    asyncio.create_task(_run_job(job_id, request))
    return {"job_id": job_id, "status": "queued", "selected_engines": engines}


@router.get("/jobs")
async def list_jobs(limit: int = 20) -> dict[str, Any]:
    async with _jobs_lock:
        items_by_id = {item["id"]: dict(item) for item in _jobs.values()}
    if _REPORT_DIR.exists():
        for report_path in sorted(_REPORT_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True):
            try:
                saved = json.loads(report_path.read_text(encoding="utf-8"))
                if isinstance(saved, dict) and saved.get("id"):
                    items_by_id.setdefault(saved["id"], saved)
            except (OSError, json.JSONDecodeError):
                log.warning("skipping unreadable unified report %s", report_path.name)
    items = sorted(items_by_id.values(), key=lambda item: item.get("created_at", ""), reverse=True)[: max(1, min(limit, 100))]
    return {"jobs": items}


@router.get("/reports/{job_id}")
async def download_report(job_id: str) -> FileResponse:
    path = _REPORT_DIR / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "report_not_ready")
    return FileResponse(path, media_type="application/json", filename=f"geo-report-{job_id}.json")


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            return job
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id):
        raise HTTPException(404, "job_not_found")
    path = _REPORT_DIR / f"{job_id}.json"
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and saved.get("id") == job_id:
                return saved
        except (OSError, json.JSONDecodeError):
            log.exception("failed to load unified report %s", job_id)
    raise HTTPException(404, "job_not_found")


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str) -> dict[str, Any]:
    if provider_id not in API_ADAPTERS:
        raise HTTPException(400, "only_api_providers_can_be_tested")
    if not _api_ready(provider_id):
        raise HTTPException(409, "api_key_missing")
    result = await _run_api(provider_id, "请只回复：连接成功")
    if result.get("error"):
        return {"ok": False, "provider": API_ADAPTERS[provider_id][0], "message": str(result["error"])}
    answer = str(result.get("answer", "")).strip()
    if not answer:
        return {"ok": False, "provider": API_ADAPTERS[provider_id][0], "message": "服务返回成功，但没有收到文本回答"}
    return {"ok": True, "provider": API_ADAPTERS[provider_id][0], "message": "连接成功", "answer_preview": answer[:240]}


@router.get("/overview")
async def overview() -> dict[str, Any]:
    async with _jobs_lock:
        jobs = list(_jobs.values())
    completed = [job for job in jobs if job.get("status") in {"completed", "partial"}]
    summaries = [job.get("summary", {}) for job in completed if job.get("summary")]
    mention_rate = round(sum(s.get("mention_rate", 0) for s in summaries) / len(summaries), 1) if summaries else 0
    return {"jobs_total": len(jobs), "jobs_running": sum(job.get("status") in {"queued", "running"} for job in jobs),
            "mention_rate": mention_rate, "providers": (await providers()),
            "latest_job": completed[0] if completed else None}






