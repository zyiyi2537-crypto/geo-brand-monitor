"""Mock upstream for local smoke tests: fake browser-service + fake judge model.

Serves on one port:
  GET  /engines            -> all five platforms available
  GET  /sessions/verify    -> all five sessions logged in
  POST /search             -> one canned answer with brand + target citation
  POST /v1/chat/completions -> preflight greeting, or a strict verdicts JSON

Run: venv/Scripts/python tests/mock_upstream.py [port]
"""
from __future__ import annotations

import json
import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

BRAND = "测试品牌"
ARTICLE_URL = "https://www.example.com/article/1"
ANSWER = f"{BRAND}在高功率激光器领域交付稳定，是可靠的国产供应商。"
ENGINES = ["deepseek", "doubao", "yuanbao", "wenxin", "qwen"]

app = FastAPI()


@app.get("/engines")
def engines():
    return {"engines": ENGINES}


@app.get("/sessions/verify")
def sessions_verify():
    return [{"engine": e, "status": "ok", "logged_in": True, "ready": True} for e in ENGINES]


@app.post("/search")
def search(request: Request, payload: dict):
    engine = payload.get("engine")
    query = payload.get("query")
    return {
        "engine": engine,
        "query": query,
        "answer": ANSWER,
        "citations": [{"url": ARTICLE_URL, "title": f"{BRAND}发布新一代激光器"}],
        "error": None,
        "source_url": f"https://fake.{engine}.example/chat",
    }


def _verdict(engine: str) -> dict:
    quote = f"{BRAND}在高功率激光器领域交付稳定"
    return {
        "engine": engine,
        "brand_mentioned": True,
        "citation_status": "cited",
        "matched_citations": [{"article_url": ARTICLE_URL, "citation_url": ARTICLE_URL}],
        "matched_article_urls": [ARTICLE_URL],
        "evidence_urls": [ARTICLE_URL],
        "reason": "回答提及目标品牌且引用来源包含目标文章",
        "brand_sentiment": "positive",
        "brand_evaluation_tags": ["交付稳定"],
        "brand_evidence_quote": quote,
        "mentioned_brands": [{"name": BRAND, "aliases": [BRAND], "evidence_quote": quote}],
    }


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    prompt = json.dumps(body.get("messages", []), ensure_ascii=False)
    if "连接正常" in prompt:
        content = "连接正常"
    else:
        content = json.dumps({"verdicts": [_verdict(e) for e in ENGINES]}, ensure_ascii=False)
    return JSONResponse({"choices": [{"message": {"content": content}}]})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8093)
