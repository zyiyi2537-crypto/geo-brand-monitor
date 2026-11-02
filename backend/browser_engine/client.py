"""Unified HTTP client for browser engine microservice.

Routes engine queries to the configured regional browser-service instance.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

# ── Service URLs ───────────────────────────────────────────────

BROWSER_CN_URL = os.environ.get("BROWSER_CN_URL", "http://localhost:8092")
BROWSER_GLOBAL_URL = os.environ.get("BROWSER_GLOBAL_URL", "http://localhost:8091")

ENGINE_ROUTING = {
    # CN — domestic engines
    "deepseek": "cn",
    "doubao":   "cn",
    "qwen":     "cn",
    "wenxin":   "cn",
    "yuanbao":  "cn",
    # Global — international engines
    "chatgpt":  "global",
    "claude":   "global",
    "gemini":   "global",
    "grok":     "global",
    "copilot":  "global",
}

_TIMEOUT = 180.0
_SHORT_TIMEOUT = 10.0


def _base_url(engine: str) -> str:
    """Return the full base URL including the nginx route prefix.

    Production deploys the cn / global browser-service instances behind nginx,
    which proxies `/api/browser-cn/*` → cn instance and `/api/browser-global/*`
    → global instance. So callers must hit `{host}/api/browser-{region}/...`,
    not `{host}/...` (the bare path falls through to the SPA fallback and
    returns the index.html, not JSON).
    """
    region = ENGINE_ROUTING.get(engine, "cn")
    host = BROWSER_GLOBAL_URL if region == "global" else BROWSER_CN_URL
    return f"{host.rstrip('/')}/api/browser-{region}"


# ── Search ─────────────────────────────────────────────────────

def search(engine: str, query: str) -> dict:
    """Sync search — call from thread pool."""
    base = _base_url(engine)
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{base}/search", json={"engine": engine, "query": query})
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": "browser service unavailable"}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"engine": engine, "query": query, "answer": "", "citations": [], "error": "browser service busy (429)"}
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": f"browser service error: {e}"}
    except Exception as e:
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": str(e)}


async def search_async(engine: str, query: str) -> dict:
    """Async search — call from async context."""
    base = _base_url(engine)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{base}/search", json={"engine": engine, "query": query})
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": "browser service unavailable"}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"engine": engine, "query": query, "answer": "", "citations": [], "error": "browser service busy (429)"}
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": f"browser service error: {e}"}
    except Exception as e:
        return {"engine": engine, "query": query, "answer": "", "citations": [], "error": str(e)}


# ── Fetch page title ───────────────────────────────────────────

def fetch_title(url: str, region: str = "cn", timeout_ms: int = 15000) -> str:
    """用 browser-service 的真实浏览器抓任意 URL 的页面标题.

    知乎等站点对裸 HTTP 请求 403,只有真实浏览器能拿到 <title>,所以走 browser-service.
    best-effort — 服务不可用 / 抓不到都返回空字符串,调用方自行回退.
    region: "cn"(默认,国内信源如知乎)或 "global".
    """
    host = BROWSER_GLOBAL_URL if region == "global" else BROWSER_CN_URL
    if not host:
        return ""
    base = f"{host.rstrip('/')}/api/browser-{region}"
    try:
        with httpx.Client(timeout=(timeout_ms / 1000.0) + 10.0) as client:
            resp = client.post(f"{base}/fetch-title",
                               json={"url": url, "timeout_ms": timeout_ms})
            resp.raise_for_status()
            return (resp.json().get("title") or "").strip()
    except Exception:
        return ""


# ── Session status ─────────────────────────────────────────────

def has_session(engine: str) -> bool:
    """Check if a single engine has a valid session."""
    base = _base_url(engine)
    try:
        with httpx.Client(timeout=_SHORT_TIMEOUT) as client:
            resp = client.get(f"{base}/sessions/{engine}")
            if resp.status_code == 200:
                return resp.json().get("has_session", False)
    except Exception:
        pass
    return False


async def has_session_async(engine: str) -> bool:
    base = _base_url(engine)
    try:
        async with httpx.AsyncClient(timeout=_SHORT_TIMEOUT) as client:
            resp = await client.get(f"{base}/sessions/{engine}")
            if resp.status_code == 200:
                return resp.json().get("has_session", False)
    except Exception:
        pass
    return False


def get_sessions() -> list[dict]:
    """Get all sessions from both service instances."""
    result = []
    for host, region in [(BROWSER_CN_URL, "cn"), (BROWSER_GLOBAL_URL, "global")]:
        if not host:
            continue
        try:
            with httpx.Client(timeout=_SHORT_TIMEOUT) as client:
                resp = client.get(f"{host.rstrip('/')}/api/browser-{region}/sessions")
                if resp.status_code == 200:
                    result.extend(resp.json())
        except Exception:
            pass
    return result


async def get_sessions_async() -> list[dict]:
    """Async version — fetches from both instances concurrently."""
    result = []
    async with httpx.AsyncClient(timeout=_SHORT_TIMEOUT) as client:
        for host, region in [(BROWSER_CN_URL, "cn"), (BROWSER_GLOBAL_URL, "global")]:
            if not host:
                continue
            try:
                resp = await client.get(f"{host.rstrip('/')}/api/browser-{region}/sessions")
                if resp.status_code == 200:
                    result.extend(resp.json())
            except Exception:
                pass
    return result


# ── Snapshot proxy helper ──────────────────────────────────────

def get_snapshot_url(engine: str, filename: str) -> str:
    """Return the full URL for a snapshot file on the browser service."""
    base = _base_url(engine)
    return f"{base}/snapshot/{engine}/{filename}"
