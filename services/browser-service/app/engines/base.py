"""Self-contained base types for browser engine adapters.

No dependency on the main service's api_engine module.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse


@dataclass
class Citation:
    url: str
    domain: str
    title: str = ""
    snippet: str = ""
    position: int = 0

    @staticmethod
    def from_url(url: str, title: str = "", snippet: str = "", position: int = 0) -> "Citation":
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = url
        return Citation(url=url, domain=domain, title=title, snippet=snippet, position=position)


@dataclass
class EngineResult:
    engine: str
    query: str
    answer: str = ""
    citations: List[Citation] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    error: Optional[str] = None
    video_path: Optional[str] = None
    citation_collection: dict = field(default_factory=dict)
    source_url: Optional[str] = None


class EngineAdapter(ABC):
    name: str = "unknown"

    @abstractmethod
    async def search(self, query: str) -> EngineResult:
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        ...

    async def close(self) -> None:
        pass


_URL_RE = re.compile(r'https?://[\w\-\.]+\.[a-z]{2,}/\S*')


def extract_urls_from_text(text: str) -> List[str]:
    return list(dict.fromkeys(_URL_RE.findall(text)))


def extract_citations_from_json(data, block_hosts: tuple = ()) -> List[Citation]:
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
