"""OpenRouter HTTPS 透传代理 — 给 vm02(国内 IP 被 OpenRouter chat completions 风控)用.

架构(与 ddg-proxy 同构):
    vm02 → EC2 nginx :80 /openrouter/ → 127.0.0.1:8096
                                          ↓
                  这个 FastAPI 服务用 EC2 出口(美国 IP)调 openrouter.ai
                                          ↓
                                       原样返回

特点:
- **Authorization 头透传** — vm02 仍管 OPENROUTER_API_KEY,只是绕开 IP 风控
- **X-Proxy-Token 额外鉴权** — 防公网被滥用(nginx IP 白名单 + token 双重)
- **透传 status / body / 关键 header** — JSON 错误响应一字不改

env:
    OPENROUTER_PROXY_PORT     默认 8096
    OPENROUTER_PROXY_TOKEN    必填(否则启动后所有请求 401)
    OPENROUTER_PROXY_TIMEOUT  默认 120 秒
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s | %(message)s")
log = logging.getLogger("openrouter-proxy")

UPSTREAM = "https://openrouter.ai/api"
_TOKEN = os.environ.get("OPENROUTER_PROXY_TOKEN", "").strip()
TIMEOUT = int(os.environ.get("OPENROUTER_PROXY_TIMEOUT", "120"))

app = FastAPI(title="openrouter-proxy", version="0.1.0")


def _check_auth(x_proxy_token: Optional[str]) -> None:
    if not _TOKEN:
        # 启动时未设 token → 拒绝所有请求(防止裸跑公网)
        raise HTTPException(503, "proxy not configured (OPENROUTER_PROXY_TOKEN missing)")
    if x_proxy_token != _TOKEN:
        raise HTTPException(401, "invalid or missing X-Proxy-Token")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "upstream": UPSTREAM,
        "auth_required": bool(_TOKEN),
        "timeout": TIMEOUT,
    }


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(
    path: str,
    request: Request,
    x_proxy_token: Optional[str] = Header(None, alias="X-Proxy-Token"),
) -> Response:
    """透传 /v1/* 到 OpenRouter,Authorization 等头原样送上,body 原样送上."""
    _check_auth(x_proxy_token)

    # 透传给 OpenRouter 的关键 header(不带不必要的 Host / Connection 等)
    out_headers: dict[str, str] = {}
    for h in ("authorization", "content-type", "http-referer", "x-title", "accept"):
        v = request.headers.get(h)
        if v:
            out_headers[h] = v

    body = await request.body()
    url = f"{UPSTREAM}/v1/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.request(
                request.method, url, headers=out_headers, content=body,
            )
    except httpx.HTTPError as e:
        log.warning("upstream error: method=%s path=%s err=%s", request.method, path, e)
        raise HTTPException(502, f"upstream: {e}")

    log.info(
        "proxy ok: method=%s path=%s upstream=%d size=%d",
        request.method, path, r.status_code, len(r.content),
    )

    # 透传 content-type;其它头不带(避免 transfer-encoding 等冲突)
    resp_headers: dict[str, str] = {}
    ct = r.headers.get("content-type")
    if ct:
        resp_headers["content-type"] = ct

    return Response(content=r.content, status_code=r.status_code, headers=resp_headers)
