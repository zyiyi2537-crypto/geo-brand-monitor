"""Unified EngineAdapter interface and shared data structures.

Every AI engine adapter — whether API-based or Playwright-based — implements
the EngineAdapter ABC so the analysis layer never cares about the underlying
transport.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse


# ── Data structures ──────────────────────────────────────────

@dataclass
class Citation:
    """A single citation extracted from an AI engine's answer."""
    url: str
    domain: str
    title: str = ""
    snippet: str = ""          # context around the citation
    position: int = 0          # ordinal position in the answer (1-based)

    @staticmethod
    def from_url(url: str, title: str = "", snippet: str = "", position: int = 0) -> "Citation":
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = url
        return Citation(url=url, domain=domain, title=title, snippet=snippet, position=position)


@dataclass
class EngineResult:
    """Unified result from any AI engine query."""
    engine: str                 # "kimi" / "qwen" / "perplexity" / "deepseek" / …
    query: str
    answer: str = ""
    citations: List[Citation] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    error: Optional[str] = None
    video_path: Optional[str] = None  # MP4 snapshot path when GEO_RECORD_VIDEO=1


# ── Abstract base class ──────────────────────────────────────

class EngineAdapter(ABC):
    """Unified interface for all AI engine adapters."""

    name: str = "unknown"

    @abstractmethod
    async def search(self, query: str) -> EngineResult:
        """Run a query and return the answer with structured citations."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check whether the engine is usable (valid API key / live session)."""
        ...

    async def close(self) -> None:
        """Clean up resources (browser pages, HTTP sessions, etc.)."""
        pass


# ── Helpers shared across adapters ───────────────────────────

_URL_RE = re.compile(r'https?://[\w\-\.]+\.[a-z]{2,}/\S*')


def extract_urls_from_text(text: str) -> List[str]:
    """Fallback: regex-extract URLs from answer text when the API doesn't
    provide structured citations."""
    return list(dict.fromkeys(_URL_RE.findall(text)))


def extract_citations_from_json(data, block_hosts: tuple = ()) -> List[Citation]:
    """Extract structured citations from a parsed JSON API response.

    Walks the JSON tree looking for common citation patterns:
      - {"url": "...", "title": "...", "snippet": "..."}
      - {"link": "...", "title": "...", "text": "..."}
      - {"href": "...", "name": "...", "description": "..."}
      - Lists of the above

    Args:
        data: Parsed JSON (dict or list) from an API response.
        block_hosts: Domain substrings to exclude.
    """
    citations: List[Citation] = []
    seen: set[str] = set()
    pos = 0

    def _add(url: str, title: str = "", snippet: str = "") -> None:
        nonlocal pos
        url = url.strip().rstrip("\\").rstrip(")")
        if not url.startswith("http"):
            return
        domain = urlparse(url).netloc.replace("www.", "")
        if not domain or any(bh in domain for bh in block_hosts):
            return
        if url in seen:
            return
        seen.add(url)
        pos += 1
        citations.append(Citation.from_url(url, title=title, snippet=snippet, position=pos))

    def _walk(obj) -> None:
        if isinstance(obj, dict):
            url = obj.get("url") or obj.get("link") or obj.get("href") or obj.get("source") or ""
            title = obj.get("title") or obj.get("name") or obj.get("text") or ""
            snippet = obj.get("snippet") or obj.get("description") or obj.get("excerpt") or obj.get("summary") or ""
            if isinstance(url, str) and url.startswith("http"):
                _add(url, str(title), str(snippet))
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    try:
        _walk(data)
    except Exception:
        pass
    return citations
