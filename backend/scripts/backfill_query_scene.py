"""CLI:把所有 topic 的 queries_json 里每条 query 用启发式打上 scene_type 标签.

2026-05-28 — 4 维场景扩展第一波 backfill 脚本.
不依赖 LLM,纯文本启发式(geo.services.query_expander.classify_query):

  优先级:
    1. 文本含 target / aliases 字面 → brand
    2. 含意图词(如何 / 怎么用 / 教程 / 攻略 / 步骤 / 入门 ...) → intent
    3. 含问答词(哪家 / 怎么样 / 对比 / 是什么 / 评价 / 吗 ...) → qa
    4. 其余 → search

幂等可重跑:覆盖式写 scene_type.

用法:
    ./venv/bin/python scripts/backfill_query_scene.py             # 全部 topic
    ./venv/bin/python scripts/backfill_query_scene.py --topic 12  # 只跑 topic 12
    ./venv/bin/python scripts/backfill_query_scene.py --dry-run   # 只算不写
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geo.database import SessionLocal
from geo.models.ai_telemetry import AiTelemetryTopicORM
from geo.services.query_expander import classify_query, ALL_SCENES

log = logging.getLogger(__name__)


def _process_one(topic: AiTelemetryTopicORM) -> tuple[int, int, Counter]:
    """处理单个 topic.返回 (total_queries, changed_count, scene_distribution)."""
    try:
        arr = json.loads(topic.queries_json or "[]")
    except Exception:  # noqa: BLE001
        arr = []
    if not isinstance(arr, list):
        arr = []

    target = (topic.target or "").strip()
    try:
        aliases = json.loads(topic.target_aliases_json or "[]")
        if not isinstance(aliases, list):
            aliases = []
        aliases = [str(a) for a in aliases if isinstance(a, str)]
    except Exception:  # noqa: BLE001
        aliases = []

    counts: Counter = Counter()
    changed = 0
    upgraded: list[dict] = []
    for q in arr:
        if isinstance(q, str):
            scene = classify_query(q, target=target, aliases=aliases)
            counts[scene] += 1
            upgraded.append({
                "text": q, "status": "approved",
                "selected": True, "scene_type": scene,
            })
            changed += 1
        elif isinstance(q, dict) and q.get("text"):
            new_q = dict(q)
            scene = classify_query(str(q.get("text") or ""),
                                    target=target, aliases=aliases)
            counts[scene] += 1
            if new_q.get("scene_type") != scene:
                new_q["scene_type"] = scene
                changed += 1
            upgraded.append(new_q)
    return len(upgraded), changed, counts, upgraded


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", type=int, default=None,
                    help="只跑这个 topic_id;默认扫所有")
    ap.add_argument("--dry-run", action="store_true",
                    help="只算分布不写库")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    db = SessionLocal()
    try:
        q = db.query(AiTelemetryTopicORM)
        if args.topic is not None:
            q = q.filter(AiTelemetryTopicORM.id == args.topic)
        topics = q.all()
        log.info("found %d topics to backfill", len(topics))

        all_counts: Counter = Counter()
        total_queries = 0
        total_changed = 0
        touched_topics = 0
        for t in topics:
            n_queries, n_changed, counts, upgraded = _process_one(t)
            total_queries += n_queries
            total_changed += n_changed
            all_counts.update(counts)
            if n_queries == 0:
                continue
            log.info(
                "topic %d (name=%r, target=%r): %d queries, %d changed, dist=%s",
                t.id, t.name, t.target or "", n_queries, n_changed,
                dict(counts),
            )
            if n_changed > 0 and not args.dry_run:
                t.queries_json = json.dumps(upgraded, ensure_ascii=False)
                touched_topics += 1
        if args.dry_run:
            log.info("DRY-RUN: would touch %d topics", touched_topics)
        else:
            db.commit()
            log.info("committed; touched %d topics", touched_topics)

        log.info("─" * 60)
        log.info("TOTAL across %d topics:", len(topics))
        log.info("  queries seen:    %d", total_queries)
        log.info("  scene_type changed: %d", total_changed)
        log.info("  scene distribution:")
        for s in ALL_SCENES:
            n = all_counts.get(s, 0)
            pct = 100 * n / total_queries if total_queries else 0
            log.info("    %-8s %5d (%.1f%%)", s, n, pct)
    finally:
        db.close()


if __name__ == "__main__":
    main()
