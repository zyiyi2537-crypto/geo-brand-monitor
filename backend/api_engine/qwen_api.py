"""Qwen (通义千问 / DashScope) API adapter — enable_search=true.

The DashScope API supports `enable_search` which triggers Qwen to search the
web and return structured `search_results` in the response.

Env: QWEN_API_KEY
"""

from __future__ import annotations

import os

import requests

from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


class QwenAPIAdapter(EngineAdapter):
    name = "通义千问"

    API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("QWEN_API_KEY", "").strip()

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str) -> EngineResult:
        if not self._api_key:
            return EngineResult(engine=self.name, query=query, error="QWEN_API_KEY not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "qwen-plus",
            "messages": [{"role": "user", "content": query}],
            "enable_search": True,
        }

        try:
            r = requests.post(self.API_URL, json=payload, headers=headers, timeout=60)
            if r.status_code == 401:
                return EngineResult(engine=self.name, query=query, error="invalid_key")
            if r.status_code != 200:
                return EngineResult(engine=self.name, query=query, error=f"http_{r.status_code}")

            data = r.json()
            answer = ""
            citations = []

            choices = data.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                answer = msg.get("content", "") or ""

            # DashScope returns search_results in the response
            search_results = data.get("search_results", [])
            if not search_results:
                # Some versions nest it under choices[0].message
                if choices:
                    search_results = choices[0].get("message", {}).get("search_results", [])

            for i, sr in enumerate(search_results):
                url = sr.get("url", "") or sr.get("link", "")
                title = sr.get("title", "")
                snippet = sr.get("snippet", "") or sr.get("text", "")
                if url:
                    citations.append(Citation.from_url(url, title=title, snippet=snippet, position=i + 1))

            # Fallback to URL extraction
            if not citations:
                urls = extract_urls_from_text(answer)
                citations = [
                    Citation.from_url(url, position=i + 1)
                    for i, url in enumerate(urls)
                ]

            return EngineResult(
                engine=self.name,
                query=query,
                answer=answer,
                citations=citations,
            )
        except requests.RequestException as e:
            return EngineResult(engine=self.name, query=query, error=str(e))
