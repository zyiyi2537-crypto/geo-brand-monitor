"""把 ai_telemetry_responses.citations_json 跟 topic_generated_docs.publish_targets_json
取交集,回填 doc.cited_by_json。

被以下入口调用:
  - CLI:scripts/backfill_doc_cited_by.py
  - HTTP:POST /api/admin/content-review/rebuild-cited-by
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from geo.database import SessionLocal
from geo.models.ai_telemetry import (
    AiTelemetryResponseORM, TopicGeneratedDocORM,
)
from geo.services.citation_match import (
    extract_publish_urls, match_citations_to_docs,
)

log = logging.getLogger(__name__)


def run(topic_id: int | None = None, *, dry_run: bool = False, replace: bool = False) -> dict:
    """主入口。

    Args:
        topic_id: 限定 topic;None = 全部有 publish_targets 的 doc。
        dry_run: 只算不写。
        replace: True = 完全重算,丢弃旧 cited_by;False = 合并,保留旧记录。

    Returns:
        统计字典 {topics, docs, matched_docs, responses_scanned, hits, dry_run, replace}
    """
    s = SessionLocal()
    try:
        doc_q = s.query(TopicGeneratedDocORM).filter(
            TopicGeneratedDocORM.publish_targets_json.isnot(None),
            TopicGeneratedDocORM.publish_targets_json != "",
            TopicGeneratedDocORM.publish_targets_json != "[]",
        )
        if topic_id is not None:
            doc_q = doc_q.filter(TopicGeneratedDocORM.topic_id == topic_id)
        docs_by_topic: dict[int, list[TopicGeneratedDocORM]] = defaultdict(list)
        for d in doc_q.all():
            docs_by_topic[d.topic_id].append(d)

        if not docs_by_topic:
            return {"topics": 0, "docs": 0, "matched_docs": 0,
                    "responses_scanned": 0, "hits": 0,
                    "dry_run": dry_run, "replace": replace}

        total_docs = 0
        matched_docs = 0
        total_responses_scanned = 0
        total_hits = 0

        for tid, docs in docs_by_topic.items():
            doc_urls: dict[int, list[str]] = {
                d.id: extract_publish_urls(d.publish_targets_json) for d in docs
            }
            doc_urls = {k: v for k, v in doc_urls.items() if v}
            if not doc_urls:
                continue
            total_docs += len(doc_urls)

            buckets: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
            if not replace:
                for d in docs:
                    if d.id not in doc_urls:
                        continue
                    try:
                        existing = json.loads(d.cited_by_json or "{}")
                    except Exception:  # noqa: BLE001
                        existing = {}
                    if not isinstance(existing, dict):
                        continue
                    for eng, rids in existing.items():
                        if not isinstance(rids, list):
                            continue
                        for r in rids:
                            try:
                                buckets[d.id][eng].add(int(r))
                            except (TypeError, ValueError):
                                pass

            q = s.query(AiTelemetryResponseORM).filter(
                AiTelemetryResponseORM.topic_id == tid
            )
            for r in q.yield_per(500):
                total_responses_scanned += 1
                try:
                    cits = json.loads(r.citations_json or "[]")
                except Exception:  # noqa: BLE001
                    continue
                hits = match_citations_to_docs(cits, doc_urls)
                if not hits:
                    continue
                for doc_id in hits.keys():
                    buckets[doc_id][r.engine].add(r.id)
                    total_hits += 1

            for d in docs:
                if d.id not in doc_urls:
                    continue
                new_payload = {
                    eng: sorted(rids) for eng, rids in buckets.get(d.id, {}).items() if rids
                }
                new_json = json.dumps(new_payload, ensure_ascii=False) if new_payload else "{}"
                if new_payload:
                    matched_docs += 1
                if (d.cited_by_json or "{}") != new_json:
                    if not dry_run:
                        d.cited_by_json = new_json

        if not dry_run:
            s.commit()

        stats = {
            "topics": len(docs_by_topic),
            "docs": total_docs,
            "matched_docs": matched_docs,
            "responses_scanned": total_responses_scanned,
            "hits": total_hits,
            "dry_run": dry_run,
            "replace": replace,
        }
        log.info("backfill cited_by done %s", stats)
        return stats
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
