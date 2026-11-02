"""OpenRouter API 客户端 — 用于海外 5 引擎 (chatgpt/claude/gemini/grok/copilot).

为什么不走 browser:海外 5 个引擎我们没有可用的 browser-service 实例(IP 风控 + 登录态)。
OpenRouter 已经把这些模型 host 了,通过 `:online` 后缀启用 web search,
返回内容里带原生 citations(部分模型,如 perplexity)或正文里夹 URL(GPT/Claude).

返回 shape 与 services/browser-service `/search` **完全一致**,这样 runner 切换零成本:
    {engine, query, answer, citations[{url, domain, title}], video_url, source_url, error}

引擎到 OpenRouter model 的映射(`:online` 启用 web search 插件):
    chatgpt → openai/gpt-4o-mini:online
    claude  → anthropic/claude-3.5-sonnet:online
    gemini  → google/gemini-2.0-flash-exp:online
    grok    → x-ai/grok-2-1212:online
    copilot → openai/gpt-4o:online   (Microsoft Copilot 没公开 API,GPT-4 是近似底层模型)

ENV:
    OPENROUTER_API_KEY  必填
    OPENROUTER_MODEL_<engine>  可覆盖默认 model id(运维想换模型时用)
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODEL_MAP: dict[str, str] = {
    # 2026-05 实测可用,优先用「search-preview」(自带 web search)或「router alias」.
    # 老的 `:online` 后缀在 2026 已废弃,会返回 500.
    "chatgpt": "openai/gpt-4o-mini-search-preview",
    "claude":  "~anthropic/claude-sonnet-latest",
    "gemini":  "~google/gemini-flash-latest",
    "grok":    "x-ai/grok-4-fast",
    "copilot": "openai/gpt-4o-search-preview",
}

# `_URL_RE` 在 answer 文本里抓 URL 兜底(GPT/Claude/Grok 没有结构化 citations 字段)
_URL_RE = re.compile(r"https?://[\w\-\.]+\.[a-z]{2,}/?\S*")


def _model_for(engine: str) -> str | None:
    override = os.environ.get(f"OPENROUTER_MODEL_{engine.upper()}")
    if override:
        return override
    return DEFAULT_MODEL_MAP.get(engine)


def is_openrouter_engine(engine: str) -> bool:
    """这个引擎是否走 OpenRouter API(否则走 browser-service)."""
    return _model_for(engine) is not None


def _err(engine: str, query: str, msg: str) -> dict[str, Any]:
    return {
        "engine": engine, "query": query, "answer": "", "citations": [],
        "video_url": None, "source_url": None, "error": msg,
    }


async def call_openrouter(
    client: httpx.AsyncClient, engine: str, query: str, timeout: int = 60,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return _err(engine, query, "OPENROUTER_API_KEY 未配置")

    model = _model_for(engine)
    if not model:
        return _err(engine, query, f"未映射的引擎: {engine}")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": query}],
        "max_tokens": 1500,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter 建议设这俩做应用 ranking(可选,不影响调用)
        "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "https://vigilath.ai"),
        "X-Title": os.environ.get("OPENROUTER_TITLE", "Vigilath AI Telemetry"),
    }

    try:
        r = await client.post(OPENROUTER_URL, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as e:
        return _err(engine, query, f"network: {e}")

    if r.status_code != 200:
        body = r.text[:200] if r.text else ""
        return _err(engine, query, f"http_{r.status_code}: {body}")

    try:
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return _err(engine, query, f"bad_json: {e}")

    # ── 抽答案 ───────────────────────────────
    answer = ""
    choices = data.get("choices") or []
    if choices:
        msg_obj = choices[0].get("message") or {}
        answer = (msg_obj.get("content") or "").strip()

    # ── 抽 citations:三个来源合并去重,保持顺序 ──
    urls: list[str] = []
    seen: set[str] = set()
    titles: dict[str, str] = {}

    # 1. data.citations(perplexity / sonar 类返回这里)
    for c in (data.get("citations") or []):
        if isinstance(c, str) and c.startswith("http"):
            if c not in seen:
                seen.add(c); urls.append(c)
        elif isinstance(c, dict):
            u = c.get("url") or c.get("link")
            if isinstance(u, str) and u.startswith("http") and u not in seen:
                seen.add(u); urls.append(u)
                t = c.get("title") or ""
                if t:
                    titles[u] = t

    # 2. message.annotations(OpenAI/Anthropic 新版结构化引用)
    for ch in choices:
        msg_obj = ch.get("message") or {}
        for ann in (msg_obj.get("annotations") or []):
            uc = (ann.get("url_citation") or {}) if isinstance(ann, dict) else {}
            u = uc.get("url")
            if isinstance(u, str) and u.startswith("http") and u not in seen:
                seen.add(u); urls.append(u)
                t = uc.get("title") or ""
                if t:
                    titles[u] = t

    # 3. answer 正文 URL 兜底(grok/gemini/copilot 主要靠这条)
    for u in _URL_RE.findall(answer):
        u = u.rstrip(".,);]'\"")
        if u not in seen:
            seen.add(u); urls.append(u)

    citations: list[dict[str, str]] = []
    for u in urls:
        try:
            domain = (urlparse(u).hostname or "").lower().replace("www.", "")
        except Exception:  # noqa: BLE001
            domain = ""
        citations.append({"url": u, "domain": domain, "title": titles.get(u, "")})

    log.info(
        "openrouter ok: engine=%s model=%s ans_len=%d cites=%d",
        engine, model, len(answer), len(citations),
    )
    return {
        "engine": engine, "query": query, "answer": answer, "citations": citations,
        "video_url": None, "source_url": None, "error": None,
    }
