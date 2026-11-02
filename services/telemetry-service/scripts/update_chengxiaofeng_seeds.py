"""一次性脚本:把「程晓峰」topic 里 5 条短关键词种子改成完整 query 形式。

旧种子 → 新种子(按 text 精确匹配,匹中才换):
  跨境并购     → 企业跨境/TMT投资、海外并购的北京律师
  私募股权     → 私募股权的北京律师
  资本市场     → 资本市场(港股、美股及A股)的北京律师
  反垄断申报   → 反垄断申报与合规的北京律师
  外商直接投资 → 适合外商直接投资(FDI)的北京律师

默认 dry-run — 打印将要做的改动但不写库;加 --commit 才真的 UPDATE。
匹配方式:topic.name ILIKE '%程晓峰%'。多条匹配会一并处理,逐个确认。

用法:
    # dry-run(默认)
    DATABASE_URL=mysql+pymysql://USER:PASS@HOST:PORT/DB \\
        /home/DEV/GEO/backend/venv/bin/python \\
        /home/DEV/GEO/services/telemetry-service/scripts/update_chengxiaofeng_seeds.py

    # 真的写库
    DATABASE_URL=mysql+pymysql://USER:PASS@HOST:PORT/DB \\
        /home/DEV/GEO/backend/venv/bin/python \\
        /home/DEV/GEO/services/telemetry-service/scripts/update_chengxiaofeng_seeds.py --commit

可选参数:
    --topic-id N      只改指定 id 的 topic(不再按 name 模糊匹配)
    --no-changelog    不追加 topic_changelog_json(默认会加一条 update 记录)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


# 旧文本 → 新文本(精确匹配 + strip 后比对)
RENAMES: dict[str, str] = {
    "跨境并购":     "企业跨境/TMT投资、海外并购的北京律师",
    "私募股权":     "私募股权的北京律师",
    "资本市场":     "资本市场(港股、美股及A股)的北京律师",
    "反垄断申报":   "反垄断申报与合规的北京律师",
    "外商直接投资": "适合外商直接投资(FDI)的北京律师",
}


def _load_backend_path() -> None:
    """让 import geo.* 能找到 backend 包。"""
    backend = Path(__file__).resolve().parents[3] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--commit", action="store_true",
                   help="真的写库(默认 dry-run 只打印)")
    p.add_argument("--topic-id", type=int, default=None,
                   help="只处理指定 topic id(默认按 name LIKE '%程晓峰%' 匹配)")
    p.add_argument("--no-changelog", action="store_true",
                   help="不追加 topic_changelog_json(默认会追加一条)")
    args = p.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL 必须设(指向程晓峰所在的 DB)。", file=sys.stderr)
        sys.exit(2)

    _load_backend_path()
    from geo.database import SessionLocal
    from geo.models.ai_telemetry import AiTelemetryTopicORM

    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"━━━ 模式:{mode} ━━━")
    print(f"DB:{os.environ['DATABASE_URL'].split('@')[-1]}")
    print()

    s = SessionLocal()
    try:
        q = s.query(AiTelemetryTopicORM)
        if args.topic_id is not None:
            q = q.filter(AiTelemetryTopicORM.id == args.topic_id)
        else:
            q = q.filter(AiTelemetryTopicORM.name.ilike("%程晓峰%"))
        topics = q.all()

        if not topics:
            print("没找到匹配的 topic。检查 --topic-id 或 name 是否含「程晓峰」。",
                  file=sys.stderr)
            sys.exit(1)

        print(f"匹配到 {len(topics)} 条 topic:")
        for t in topics:
            print(f"  • topic_id={t.id}  name={t.name!r}  target={t.target!r}  "
                  f"user_id={t.user_id}  status={t.submission_status}")
        print()

        total_changes = 0
        for t in topics:
            try:
                seeds = json.loads(t.seed_prompts_json or "[]")
            except (TypeError, ValueError) as e:
                print(f"  ✗ topic {t.id}: seed_prompts_json 解析失败 ({e}),跳过")
                continue
            if not isinstance(seeds, list):
                print(f"  ✗ topic {t.id}: seed_prompts_json 不是 list,跳过")
                continue

            changes: list[tuple[str, str]] = []  # (old, new)
            for item in seeds:
                if not isinstance(item, dict):
                    continue
                old_text = (item.get("text") or "").strip()
                if old_text in RENAMES:
                    new_text = RENAMES[old_text]
                    if old_text != new_text:
                        item["text"] = new_text
                        changes.append((old_text, new_text))

            if not changes:
                print(f"━━━ topic {t.id} ({t.name!r}) ━━━")
                print("  无可改种子(5 条短关键词均不在 seed_prompts_json 里)")
                continue

            print(f"━━━ topic {t.id} ({t.name!r}) — {len(changes)} 条改动 ━━━")
            for old, new in changes:
                print(f"  - {old!r}")
                print(f"  + {new!r}")
            total_changes += len(changes)

            if args.commit:
                t.seed_prompts_json = json.dumps(seeds, ensure_ascii=False)
                # 追加 changelog(跟 backend 既有 _append_changelog 同 schema)
                if not args.no_changelog:
                    try:
                        cl = json.loads(t.topic_changelog_json or "[]")
                    except (TypeError, ValueError):
                        cl = []
                    cl.append({
                        "at": datetime.utcnow().isoformat() + "Z",
                        "actor_id": None,
                        "actor_role": "script:update_chengxiaofeng_seeds",
                        "field": "seed_prompts",
                        "before": [old for old, _ in changes],
                        "after": [new for _, new in changes],
                    })
                    t.topic_changelog_json = json.dumps(cl, ensure_ascii=False)
                t.version = (t.version or 1) + 1

        print()
        print(f"━━━ 汇总:{total_changes} 条种子要改 ━━━")
        if args.commit:
            s.commit()
            print(f"✓ 已 COMMIT。topic.version +1,topic_changelog 追加 update 记录。")
        else:
            print(f"(dry-run,未写库。加 --commit 真的写。)")
    finally:
        s.close()


if __name__ == "__main__":
    main()
