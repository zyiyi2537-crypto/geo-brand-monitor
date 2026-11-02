"""URL 级 ROI 命中工具。

给定 AI 答复的 citations 列表 + 一组投放 doc 的 publish URL,判断哪个 doc 被
哪条 citation 引到了。被 backfill 脚本 / 跑批完成时的 cron / admin 手动触发
端点共用。

匹配策略:
  - host 去掉 `www.` / `m.` 前缀(移动版镜像与 PC 版视为同一信源,
    如豆包常引 `m.sohu.com/a/<id>`,投放登记的是 `www.sohu.com/a/<id>`)
  - path 去掉末尾 `/`
  - query 排序后保留,丢弃跟踪类参数(`wid`/`log_from`/`c_source`/`timestamp`...)
  - 两侧规范化后字符串相等 = 命中
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
    """规范化 URL,丢弃跟踪参数,去掉 fragment 和 www. 前缀。

    返回空字符串表示 URL 无效。
    """
    if not url:
        return ""
    try:
        p = urlparse(url.strip().lower())
    except Exception:  # noqa: BLE001
        return ""
    host = p.hostname or ""
    # 去掉 www. / m.(移动版镜像)前缀 —— 同一篇文章的 PC/移动 URL 归一为同一信源
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
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
    """把 citations 跟一组 doc 的投放 URL 做匹配。

    Args:
        citations: AI 答复里的 citations,形如 [{url, domain, title}, ...]
        doc_urls: {doc_id: [publish_url, ...]}

    Returns:
        {doc_id: {cited_url, ...}}  仅包含被命中的 doc。
    """
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
    """从 doc.publish_targets_json 里抽出所有非空 URL。"""
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
    """把新命中的 response_id 合并进 doc.cited_by_json,按引擎分桶,自动去重。"""
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
