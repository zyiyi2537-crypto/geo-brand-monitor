"""Zhipu ChatGLM API adapter — web_search tool support.

The Zhipu API supports a `web_search` tool that returns search results
with URLs, titles, and content snippets.

Env: ZHIPU_API_KEY
"""

from __future__ import annotations

import os
import json

import requests

from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


class ZhipuAPIAdapter(EngineAdapter):
    name = "智谱"

    API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("ZHIPU_API_KEY", "").strip()

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str) -> EngineResult:
        if not self._api_key:
            return EngineResult(engine=self.name, query=query, error="ZHIPU_API_KEY not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "glm-4-plus",
            "messages": [{"role": "user", "content": query}],
            "tools": [
                {
                    "type": "web_search",
                    "web_search": {"enable": True},
                }
            ],
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

                # Zhipu returns web_search results in tool_calls or web_search field
                tool_calls = msg.get("tool_calls", [])
                for tc in tool_calls:
                    if tc.get("type") == "web_search":
                        search_data = tc.get("web_search", {})
                        results = search_data.get("search_result", [])
                        for i, sr in enumerate(results):
                            url = sr.get("link", "") or sr.get("url", "")
                            title = sr.get("title", "")
                            snippet = sr.get("content", "")
                            if url:
                                citations.append(
                                    Citation.from_url(url, title=title, snippet=snippet, position=i + 1)
                                )

            # Also check top-level web_search field (some API versions)
            ws = data.get("web_search", [])
            if ws and not citations:
                for i, sr in enumerate(ws):
                    url = sr.get("link", "") or sr.get("url", "")
                    title = sr.get("title", "")
                    snippet = sr.get("content", "")
                    if url:
                        citations.append(
                            Citation.from_url(url, title=title, snippet=snippet, position=i + 1)
                        )

            # Fallback
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
