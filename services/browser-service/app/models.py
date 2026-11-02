"""Pydantic v2 models for browser service API."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    engine: str
    query: str


class CitationOut(BaseModel):
    url: str
    domain: str
    title: str = ""
    snippet: str = ""
    position: int = 0


class SearchResponse(BaseModel):
    engine: str
    query: str
    answer: str = ""
    citations: List[CitationOut] = []
    error: Optional[str] = None
    video_url: Optional[str] = None
    citation_collection: dict = Field(default_factory=dict)
    source_url: Optional[str] = None


class FetchTitleRequest(BaseModel):
    url: str
    timeout_ms: int = 15000


class FetchTitleResponse(BaseModel):
    url: str
    title: str = ""
    error: Optional[str] = None


class SessionInfo(BaseModel):
    engine: str
    has_session: bool
    name: str = ""


class EnginesResponse(BaseModel):
    region: str
    engines: List[str]


class HealthResponse(BaseModel):
    status: str
    browser_connected: bool
    region: str
    engine_count: int
    background_mode: bool = False
    desktop_isolated: bool = False
