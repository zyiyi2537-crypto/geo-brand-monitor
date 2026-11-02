"""URL 级 ROI 命中工具(telemetry-service 端口)。

跟 backend/geo/services/citation_match.py 同源,规则严格一致 — 双方都改时
同步两边。后端版本有 docstring 详述策略。
"""
from __future__ import annotations

import json
import logging
from typing import Iterable
from urllib.parse import parse_qsl, urlparse, urlencode

log = logging.getLogger(__name__)

_TRACKING_KEYS = {
    "wid", "log_from", "c_source", "c_score", "backurl",
    "timestamp", "signature", "third", "wfr", "utm_source",
    "utm_medium", "utm_campaign", "from", "spm",
}


def canonicalize(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url.strip().lower())
    except Exception:  # noqa: BLE001
        return ""
    host = p.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "").rstrip("/")
    pairs = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
        if k not in _TRACKING_KEYS
    ]
    pairs.sort()
    q = urlencode(pairs)
    base = f"{host}{path}"
    return f"{base}?{q}" if q else base


def match_citations_to_docs(
    citations: list[dict] | None,
    doc_urls: dict[int, list[str]],
) -> dict[int, set[str]]:
    if not citations:
        return {}
    canon_to_doc: dict[str, list[int]] = {}
    for doc_id, urls in doc_urls.items():
        for u in urls:
            c = canonicalize(u)
            if c:
                canon_to_doc.setdefault(c, []).append(doc_id)
    if not canon_to_doc:
        return {}
    hits: dict[int, set[str]] = {}
    for cit in citations:
        if not isinstance(cit, dict):
            continue
        url = cit.get("url") or ""
        c = canonicalize(url)
        if not c:
            continue
        for doc_id in canon_to_doc.get(c, ()):
            hits.setdefault(doc_id, set()).add(url)
    return hits


def extract_publish_urls(publish_targets_json: str | None) -> list[str]:
    if not publish_targets_json:
        return []
    try:
        targets = json.loads(publish_targets_json)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(targets, list):
        return []
    out: list[str] = []
    for t in targets:
        if isinstance(t, dict):
            u = (t.get("url") or "").strip()
            if u:
                out.append(u)
    return out


def merge_cited_by(
    existing_json: str | None,
    engine: str,
    response_ids: Iterable[int],
) -> str:
    try:
        existing = json.loads(existing_json or "{}")
    except Exception:  # noqa: BLE001
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    bucket = set(existing.get(engine, []) or [])
    for rid in response_ids:
        try:
            bucket.add(int(rid))
        except (TypeError, ValueError):
            continue
    existing[engine] = sorted(bucket)
    return json.dumps(existing, ensure_ascii=False)
