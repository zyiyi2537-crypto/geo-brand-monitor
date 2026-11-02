"""一次性脚本 — 用 extract_v3 prompt 对历史 responses 重抽 competitors。

extract_v2 → v3 加了主体类型判断(人物 / 公司 / 产品),v2 把人物主体的
答复里把所在机构抽成竞品的 bug 修了。这里旁路 _extract_one 的
"if r.competitors_json: return" 短路,**强制重抽**已抽过的 responses。

只覆盖 competitors_json,其它字段(citation_domains_json / answer_format /
mention_position / brand_rank)沿用原值不动。

Usage:
    cd services/telemetry-service
    python -m scripts.backfill_competitors_v3                 # 全部 hit=True 的
    python -m scripts.backfill_competitors_v3 --topic 1       # 单 topic
    python -m scripts.backfill_competitors_v3 --limit 50      # 限 N 条(LLM 配额)
    python -m scripts.backfill_competitors_v3 --dry-run       # 只列数,不调 LLM

幂等可重跑。LLM 失败的保留旧值(不擦)。
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
            ResponseORM.error.is_(None),
        )
        if topic_id is not None:
            q = q.filter(ResponseORM.topic_id == topic_id)
        q = q.order_by(ResponseORM.id.desc())
        if limit:
            q = q.limit(limit)
        rows = q.all()
        log.info("found %d responses to re-extract competitors", len(rows))
        if dry_run:
            for r in rows[:10]:
                try:
                    old = json.loads(r.competitors_json or "[]")
                except Exception:  # noqa: BLE001
                    old = []
                log.info("  id=%d topic=%d engine=%s old=%d competitors",
                         r.id, r.topic_id, r.engine, len(old))
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
            if not result:
                failed += 1
                continue
            comps = result.get("competitors") or []
            r.competitors_json = json.dumps(comps, ensure_ascii=False)
            ok += 1
            s.commit()
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
