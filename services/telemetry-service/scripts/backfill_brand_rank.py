"""一次性脚本 — 对历史 hit=True 但 brand_rank IS NULL 的 responses 补抽 brand_rank.

跑批流程的 _extract_one 见到 competitors_json 非空会跳过(避免重跑),所以新加
brand_rank 字段后对老数据无效。这里旁路那个 check,只补 brand_rank 一个字段,
不动 competitors_json / mention_position / 其它已抽字段。

Usage:
    cd services/telemetry-service
    python -m scripts.backfill_brand_rank                # 全量补
    python -m scripts.backfill_brand_rank --topic 5      # 单 topic
    python -m scripts.backfill_brand_rank --limit 200    # 限条数(LLM 配额)
    python -m scripts.backfill_brand_rank --dry-run

幂等可重跑。LLM 失败的 response 保持 brand_rank NULL,下次再补。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.storage import db_session, ResponseORM, TopicORM, parse_target
from app.llm import extract_response_insights

log = logging.getLogger(__name__)


def backfill(*, topic_id: int | None, limit: int | None, dry_run: bool) -> None:
    with db_session() as s:
        q = s.query(ResponseORM).filter(
            ResponseORM.hit == True,  # noqa: E712
            ResponseORM.brand_rank.is_(None),
            ResponseORM.error.is_(None),
        )
        if topic_id is not None:
            q = q.filter(ResponseORM.topic_id == topic_id)
        q = q.order_by(ResponseORM.id.desc())
        if limit:
            q = q.limit(limit)
        rows = q.all()
        log.info("found %d responses to backfill brand_rank", len(rows))
        if dry_run:
            for r in rows[:10]:
                log.info("  would backfill response id=%d topic=%d engine=%s query=%r",
                         r.id, r.topic_id, r.engine, r.query[:50])
            return

        topic_cache: dict[int, tuple[str, list[str]]] = {}
        ok, skipped, failed = 0, 0, 0
        for r in rows:
            if r.topic_id not in topic_cache:
                t = s.get(TopicORM, r.topic_id)
                topic_cache[r.topic_id] = parse_target(t) if t else ("", [])
            target, _ = topic_cache[r.topic_id]
            if not target:
                skipped += 1
                continue
            try:
                citations = json.loads(r.citations_json or "[]")
            except Exception:  # noqa: BLE001
                citations = []
            try:
                result = extract_response_insights(
                    target=target, query=r.query, engine=r.engine,
                    answer=r.answer or "", citations=citations,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("extract failed for response %d: %s", r.id, e)
                failed += 1
                continue
            rank = result.get("brand_rank") if result else None
            if isinstance(rank, int) and rank >= 1:
                r.brand_rank = rank
                ok += 1
                s.commit()
            else:
                failed += 1
        log.info("backfill done: ok=%d skipped=%d failed=%d", ok, skipped, failed)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", type=int, default=None, help="single topic id")
    ap.add_argument("--limit", type=int, default=None, help="cap N responses")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    backfill(topic_id=args.topic, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
