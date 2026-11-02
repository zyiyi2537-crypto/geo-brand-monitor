"""DDG search proxy — 给 vm02(机房 IP 在国内,DDG 直连不可用)远程调用。

vm02 → 本机 nginx :80 /ddg/ → proxy_pass http://127.0.0.1:8095/
                                        → 这个 FastAPI 服务调本机出口的 ddgs

返回格式与 sentinel-service/search/ddg.py:ddg_search() 完全一致,
让上游可以零差异替换本地 ddgs 库。

env:
  DDG_PROXY_PORT  默认 8095
  DDG_PROXY_TOKEN 可选 — 若设了,client 必须带 X-DDG-Token 头,否则 401。
                          防止公网被滥用。
"""
from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from ddgs import DDGS  # type: ignore


_TOKEN = os.environ.get("DDG_PROXY_TOKEN", "").strip()


app = FastAPI(title="ddg-proxy", description="DDG search proxy for cross-region access")


def _check_auth(x_ddg_token: Optional[str]) -> None:
    if _TOKEN and x_ddg_token != _TOKEN:
        raise HTTPException(401, "invalid or missing X-DDG-Token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "auth": "required" if _TOKEN else "open"}


@app.get("/search")
def search(
    query: str = Query(..., min_length=1),
    max_results: int = Query(10, ge=1, le=50),
    region: str = Query("wt-wt"),
    timelimit: Optional[str] = Query(None, pattern=r"^(d|w|m|y)$"),
    x_ddg_token: Optional[str] = Header(None, alias="X-DDG-Token"),
) -> dict:
    """DDG text search — 返回 [{title, href, body}] list。

    超时 / 错误统一包成 200 + 空 results,与 sentinel-service ddg.py 兼容。
    """
    _check_auth(x_ddg_token)
    t0 = time.time()
    try:
        with DDGS() as ddgs:
            it = ddgs.text(
                query,
                region=region,
                timelimit=timelimit,
                max_results=max_results,
            )
            results = list(it or [])
    except Exception as e:  # noqa: BLE001
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "query": query,
            "elapsed": round(time.time() - t0, 3),
            "results": [],
        }
    return {
        "status": "ok",
        "query": query,
        "elapsed": round(time.time() - t0, 3),
        "results": results,
    }
