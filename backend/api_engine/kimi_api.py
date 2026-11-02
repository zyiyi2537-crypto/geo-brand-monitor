"""Kimi (Moonshot) API adapter — native web_search tool support.

Kimi's API allows invoking a `web_search` built-in tool which returns
structured search results including URLs, titles, and snippets.

Env: KIMI_API_KEY
"""

from __future__ import annotations

import os
import json

import requests

from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


class KimiAPIAdapter(EngineAdapter):
    name = "Kimi"

    API_URL = "https://api.moonshot.cn/v1/chat/completions"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("KIMI_API_KEY", "").strip()

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str) -> EngineResult:
        if not self._api_key:
            return EngineResult(engine=self.name, query=query, error="KIMI_API_KEY not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "moonshot-v1-auto",
            "messages": [{"role": "user", "content": query}],
            "tools": [
                {
                    "type": "builtin_function",
                    "function": {"name": "web_search"},
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
            search_queries = []

            choices = data.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                answer = msg.get("content", "") or ""

                # Extract citations from tool call results if present
                tool_calls = msg.get("tool_calls", [])
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    if fn.get("name") == "web_search":
                        try:
                            args = json.loads(fn.get("arguments", "{}"))
                            sq = args.get("query", "")
                            if sq:
                                search_queries.append(sq)
                        except (json.JSONDecodeError, TypeError):
                            pass

            # Kimi embeds citations as [^n] references with URLs in the text
            # Fall back to URL extraction from answer
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
                search_queries=search_queries,
            )
        except requests.RequestException as e:
            return EngineResult(engine=self.name, query=query, error=str(e))
