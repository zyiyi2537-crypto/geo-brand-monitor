"""Backfill: queries_json 各 query 的 seed 字段。

新增 QueryItem.seed 字段后,新建/新加的 query 在 /selected-queries 时
自带 seed。但已有 topic 的 queries 是空的;本脚本一次性回填。

策略(从准到糙):
  1) expansion_log_json[].raw_excerpt 命中:把命中那条 log 的 seed 写入
  2) 子串匹配:找最长的 seed,使其文本是 query 文本的子串(大小写不敏感)
  3) 该 topic 只有 1 个 seed_prompt:全部 query 归属那个种子(fallback)
  4) 否则空字符串保留(UI 显示 "—")

幂等:已有非空 seed 的 query 不动;可重复跑。

Usage:
    cd backend && python migrations/legacy/010_backfill_query_seed.py
"""
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> None:
    from sqlalchemy.orm import sessionmaker
    from geo.database import engine
    from geo.models.ai_telemetry import AiTelemetryTopicORM

    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()

    topics = s.query(AiTelemetryTopicORM).all()
    touched_topics = 0
    touched_queries = 0
    for t in topics:
        try:
            queries = json.loads(t.queries_json or "[]")
            seeds_raw = json.loads(t.seed_prompts_json or "[]")
            expansion = json.loads(t.expansion_log_json or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(queries, list):
            continue
        seed_texts = [
            sp.get("text") for sp in seeds_raw
            if isinstance(sp, dict) and sp.get("text")
        ]
        # 1) 用 expansion_log 的 raw_excerpt 反查
        guess: dict[str, str] = {}
        for log in expansion:
            if not isinstance(log, dict):
                continue
            seed = (log.get("seed") or "").strip()
            excerpt = log.get("raw_excerpt") or ""
            if not seed or not excerpt:
                continue
            for q in queries:
                if not isinstance(q, dict):
                    continue
                qt = q.get("text") or ""
                if qt and qt in excerpt and qt not in guess:
                    guess[qt] = seed
        # 2) 子串匹配 — 找最长的 seed,其文本是 query 子串(大小写不敏感)
        sorted_seeds = sorted(
            [(sp or "") for sp in seed_texts if sp],
            key=len, reverse=True,
        )

        def substr_match(qt: str) -> str:
            qt_low = qt.lower()
            for sp in sorted_seeds:
                if sp and sp.lower() in qt_low:
                    return sp
            return ""

        # 3) 兜底:只有 1 个种子时全部 query 归属它
        fallback = seed_texts[0] if len(seed_texts) == 1 else ""
        changed = False
        for q in queries:
            if not isinstance(q, dict):
                continue
            if q.get("seed"):
                continue
            qt = q.get("text") or ""
            new_seed = guess.get(qt) or substr_match(qt) or fallback
            if new_seed:
                q["seed"] = new_seed
                changed = True
                touched_queries += 1
        if changed:
            t.queries_json = json.dumps(queries, ensure_ascii=False)
            touched_topics += 1
            with_seed = sum(1 for q in queries if isinstance(q, dict) and q.get("seed"))
            print(
                f"  topic#{t.id} ({t.name!r}): "
                f"{with_seed}/{len(queries)} queries have seed now"
            )

    s.commit()
    s.close()
    print(f"done: {touched_topics} topics touched, {touched_queries} queries got a seed")


if __name__ == "__main__":
    main()
