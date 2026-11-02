"""一次性脚本 — 把现有 Topic 升级到 v1+:

1. 对每个 Topic,若 target='' 且该 user 有 active 舆情账户,从 sentiment account
   的 target + aliases 回填 Topic.target / target_aliases_json.
2. 对每条历史 Response,若 hit IS NULL,跑 detect_hit() 重算 hit + hit_excerpt.
3. 对每个 Topic,清空 QueryHit 行后从 Response 历史聚合重建.

Usage:
    cd services/telemetry-service
    python -m scripts.backfill_query_hits          # 跑所有 enabled topics
    python -m scripts.backfill_query_hits --topic 5

通过 backend 库连接(同 DATABASE_URL).幂等可重跑.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# 允许从 services/telemetry-service 目录直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.storage import db_session, TopicORM
from app.tracking import backfill_query_hits

log = logging.getLogger(__name__)


def _read_sentiment_target(s, user_id: int) -> tuple[str, list[str]]:
    """从舆情 account 取 target + aliases.

    SentimentAccountORM 在另一个 package(geo.models),这里用裸 SQL,避免硬依赖.
    """
    row = s.execute(
        text(
            "SELECT target, aliases_json FROM sentiment_accounts "
            "WHERE user_id = :uid AND active = 1 "
            "ORDER BY created_at ASC LIMIT 1"
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return "", []
    target = row[0] or ""
    aliases: list[str] = []
    try:
        aliases = json.loads(row[1] or "[]")
    except Exception:  # noqa: BLE001
        aliases = []
    return target, aliases


def backfill_topic_target(s, topic: TopicORM) -> bool:
    """若 Topic.target 为空,从舆情账户回填. Returns True 表示有改动."""
    if topic.target:
        return False
    target, aliases = _read_sentiment_target(s, topic.user_id)
    if not target:
        return False
    topic.target = target
    topic.target_aliases_json = json.dumps(aliases, ensure_ascii=False)
    log.info("topic %d: target backfilled from sentiment = %r (+ %d aliases)",
             topic.id, target, len(aliases))
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", type=int, default=None, help="只跑指定 topic_id")
    parser.add_argument("--all", action="store_true", help="包括 disabled topics")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")

    # 先在 session 内取出 id 列表(避免 session 关闭后 detached instance)
    with db_session() as s:
        q = s.query(TopicORM.id)
        if args.topic is not None:
            q = q.filter(TopicORM.id == args.topic)
        elif not args.all:
            q = q.filter(TopicORM.enabled == True)  # noqa: E712
        topic_ids = [r[0] for r in q.all()]
        log.info("backfilling %d topics", len(topic_ids))

    for tid in topic_ids:
        try:
            with db_session() as s:
                t = s.get(TopicORM, tid)
                if t is None:
                    continue
                backfill_topic_target(s, t)
                n = backfill_query_hits(s, t)
                log.info("topic %d: rebuilt cells from %d responses", tid, n)
        except Exception as e:  # noqa: BLE001
            log.exception("topic %d backfill failed: %s", tid, e)

    log.info("done.")


if __name__ == "__main__":
    main()
