"""Update topic target + aliases, then recompute hit/hit_excerpt + query_hits matrix.

跑这个之前:
  - topic 2 target='竞天程晓峰' aliases=[] → detect_hit 永远 false (5 字连串不会出现)

跑这个之后:
  - topic 2 target='程晓峰' aliases=['竞天','竞天公诚','Jingtian','Jingtian & Gongcheng']
  - 所有历史 response 重算 hit 列(基于新 target+aliases 跑 detect_hit)
  - query_hits 矩阵 cells 重建(total_hits / first_hit_response_id)

Usage:
    cd /opt/geo/services/telemetry-service
    DATABASE_URL=sqlite:////opt/geo/backend/data/geo_checker.db \\
      /opt/geo/backend/venv/bin/python -u -m scripts.relabel_topic_target \\
      --topic-id 2 --target '程晓峰' --aliases '["竞天","竞天公诚","Jingtian","Jingtian & Gongcheng"]'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SVC_DIR = Path(__file__).resolve().parent.parent
if str(SVC_DIR) not in sys.path:
    sys.path.insert(0, str(SVC_DIR))

from app.storage import TopicORM, ResponseORM, db_session, parse_target  # noqa: E402
from app.tracking import backfill_query_hits  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--topic-id", type=int, required=True)
    p.add_argument("--target", type=str, required=True)
    p.add_argument("--aliases", type=str, default="[]", help="JSON-encoded list of aliases")
    args = p.parse_args()

    aliases = json.loads(args.aliases)
    if not isinstance(aliases, list):
        print("--aliases must be a JSON list", file=sys.stderr)
        sys.exit(1)

    with db_session() as s:
        topic = s.get(TopicORM, args.topic_id)
        if topic is None:
            print(f"topic {args.topic_id} not found", file=sys.stderr)
            sys.exit(1)

        old_target, old_aliases = parse_target(topic)
        old_n_responses_hit = (
            s.query(ResponseORM)
             .filter(ResponseORM.topic_id == args.topic_id, ResponseORM.hit == True)  # noqa: E712
             .count()
        )
        old_n_responses_total = (
            s.query(ResponseORM)
             .filter(ResponseORM.topic_id == args.topic_id)
             .count()
        )
        print(f"[before] target={old_target!r} aliases={old_aliases} hits={old_n_responses_hit}/{old_n_responses_total}")

        topic.target = args.target
        topic.target_aliases_json = json.dumps(aliases, ensure_ascii=False)
        s.flush()

        # backfill_query_hits 内部:
        #   1. 把所有 response 用新 target+aliases 跑 detect_hit, 更新 hit + hit_excerpt
        #   2. 重置 query_hits 矩阵 cells, 用新 hits 重新填
        # 注意:它只对 r.hit=None 或 False 的 response 重算;已经 True 的不动.
        # 所以先把 topic 2 所有 response 的 hit 重置为 False, 强制全部重算.
        s.query(ResponseORM).filter(ResponseORM.topic_id == args.topic_id).update(
            {ResponseORM.hit: False, ResponseORM.hit_excerpt: None, ResponseORM.mention_position: None},
            synchronize_session=False,
        )
        s.flush()

        n = backfill_query_hits(s, topic)
        s.commit()

        new_n_responses_hit = (
            s.query(ResponseORM)
             .filter(ResponseORM.topic_id == args.topic_id, ResponseORM.hit == True)  # noqa: E712
             .count()
        )
        print(f"[after]  target={args.target!r} aliases={aliases} hits={new_n_responses_hit}/{old_n_responses_total} (rebuilt {n} responses)")


if __name__ == "__main__":
    main()
