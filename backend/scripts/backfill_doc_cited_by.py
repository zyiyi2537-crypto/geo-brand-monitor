"""CLI:回填 topic_generated_docs.cited_by_json。

逻辑实现在 geo.services.backfill_cited_by;这里只是 CLI 包装。

用法:
    ./venv/bin/python scripts/backfill_doc_cited_by.py            # 全部 topic
    ./venv/bin/python scripts/backfill_doc_cited_by.py --topic 2  # 只跑 topic 2
    ./venv/bin/python scripts/backfill_doc_cited_by.py --dry-run  # 只算不写
    ./venv/bin/python scripts/backfill_doc_cited_by.py --replace  # 不合并,直接重算
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geo.services.backfill_cited_by import run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", type=int, default=None, help="只跑这个 topic_id")
    ap.add_argument("--dry-run", action="store_true", help="只算不写库")
    ap.add_argument("--replace", action="store_true", help="不合并旧 cited_by,完全重算")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stats = run(topic_id=args.topic, dry_run=args.dry_run, replace=args.replace)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
