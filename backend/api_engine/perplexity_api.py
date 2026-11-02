"""Perplexity Sonar API adapter — uses the official Perplexity API (not OpenRouter).

The official API returns a `citations` field with source URLs, which is more
reliable than the OpenRouter passthrough.

Env: PERPLEXITY_API_KEY
"""

from __future__ import annotations

import os
from typing import List

import requests

from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


class PerplexityAPIAdapter(EngineAdapter):
    name = "Perplexity"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "").strip()

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str) -> EngineResult:
        if not self._api_key:
            return EngineResult(engine=self.name, query=query, error="PERPLEXITY_API_KEY not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "sonar",
            "messages": [{"role": "user", "content": query}],
        }

        try:
            r = requests.post(
                "https://api.perplexity.ai/chat/completions",
                json=payload, headers=headers, timeout=45,
            )
            if r.status_code == 401:
                return EngineResult(engine=self.name, query=query, error="invalid_key")
            if r.status_code != 200:
                return EngineResult(engine=self.name, query=query, error=f"http_{r.status_code}")

            data = r.json()
            answer = ""
            choices = data.get("choices", [])
            if choices:
                answer = choices[0].get("message", {}).get("content", "")

            # Official API returns structured citations
            raw_citations: List[str] = data.get("citations", [])
            if not raw_citations:
                raw_citations = extract_urls_from_text(answer)

            citations = [
                Citation.from_url(url, position=i + 1)
                for i, url in enumerate(raw_citations)
            ]

            return EngineResult(
                engine=self.name,
                query=query,
                answer=answer,
                citations=citations,
            )
        except requests.RequestException as e:
            return EngineResult(engine=self.name, query=query, error=str(e))
