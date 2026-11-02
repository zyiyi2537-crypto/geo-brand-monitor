"""把豆包(或任意引擎)实际引用过的 URL,标注为"自有已发布文章",回填到
topic_generated_docs(status='published', publish_targets_json[].url)。

回填后,该 topic 的信源占比(owned 口径)就能把这些 URL 计入分子。

== 两种模式 ==

A. dump 模式 — 看豆包都引了什么,选哪些是自己的:
    DATABASE_URL=sqlite:////path/to/test.db \\
      /opt/geo/backend/venv/bin/python -u -m scripts.backfill_owned_urls \\
      --topic-id 7 --engine 豆包 --list

    输出:每个被引用过的 URL 一行,带 hit_count / domain / title / snippet,
    按 hit 命中次数倒序。

B. add 模式 — 把挑好的 URL 入库为 published doc(一个 URL 写一行 doc):
    /opt/geo/backend/venv/bin/python -u -m scripts.backfill_owned_urls \\
      --topic-id 7 --add \\
      --url "https://mp.weixin.qq.com/s/xxx" \\
      --url "https://zhuanlan.zhihu.com/p/yyy"

  或从 stdin 读(每行一个 URL,空行跳过):
    cat my_owned.txt | /opt/geo/backend/venv/bin/python -u \\
      -m scripts.backfill_owned_urls --topic-id 7 --add --from-stdin

  默认 source='user' / status='published' / title 留空。
  --title 'xxx' 给所有 URL 同一个标题,或留空让前端按 URL 显示。

== 选项 ==
  --topic-id N    必填
  --engine NAME   list 模式过滤引擎(默认 list 所有引擎;add 模式不用)
  --list          dump 模式
  --add           add 模式
  --url URL       add 模式,可重复
  --from-stdin    add 模式,从 stdin 读 URL 列表
  --title TEXT    add 模式,给所有 URL 一个标题
  --source S      add 模式,source 字段(默认 user;可填 ai)
  --dry-run       add 模式,不真插,只打要插什么
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

DEFAULT_DB_URL = "sqlite:///./data/geo_checker.db"


def _norm_url(u: str) -> str:
    if not u:
        return ""
    u = u.strip()
    try:
        p = urlparse(u)
        host = p.netloc.lower()
        path = p.path.rstrip("/") or "/"
        q = ("?" + p.query) if p.query else ""
        return f"{p.scheme.lower()}://{host}{path}{q}"
    except Exception:  # noqa: BLE001
        return u


# ─────────────────── list 模式 ───────────────────


def list_cited_urls(conn, topic_id: int, engine: str | None) -> None:
    """打印该 topic(可选引擎)所有 citation URL,按 hit 命中次数倒序。"""
    sql = (
        "SELECT engine, hit, citations_json "
        "FROM ai_telemetry_responses "
        "WHERE topic_id = :tid"
    )
    params: dict = {"tid": topic_id}
    if engine:
        sql += " AND engine = :eng"
        params["eng"] = engine
    rows = conn.execute(text(sql), params).fetchall()

    # url_norm → {hit_count, total_count, sample_title, sample_snippet,
    #             engines: Counter, raw_url}
    url_stats: dict[str, dict] = {}
    for eng, hit, cit_json in rows:
        try:
            cits = json.loads(cit_json or "[]")
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(cits, list):
            continue
        for c in cits:
            if not isinstance(c, dict):
                continue
            u = c.get("url") or ""
            if not u:
                continue
            nu = _norm_url(u)
            s = url_stats.setdefault(nu, {
                "raw_url": u,
                "hit_count": 0,
                "total_count": 0,
                "sample_title": "",
                "sample_snippet": "",
                "engines": Counter(),
            })
            s["total_count"] += 1
            s["engines"][eng] += 1
            if hit:
                s["hit_count"] += 1
            if not s["sample_title"]:
                s["sample_title"] = (c.get("title") or "")[:80]
            if not s["sample_snippet"]:
                s["sample_snippet"] = (c.get("snippet") or "")[:120]

    # 已存在 owned 标一下
    owned_rows = conn.execute(text(
        "SELECT publish_targets_json FROM topic_generated_docs "
        "WHERE topic_id = :tid AND status = 'published'"
    ), {"tid": topic_id}).fetchall()
    owned_set: set[str] = set()
    for (tj,) in owned_rows:
        try:
            tgts = json.loads(tj or "[]")
        except Exception:  # noqa: BLE001
            continue
        if isinstance(tgts, list):
            for t in tgts:
                if isinstance(t, dict):
                    u = t.get("url") or ""
                    if u:
                        owned_set.add(_norm_url(u))

    items = sorted(url_stats.items(),
                   key=lambda kv: (-kv[1]["hit_count"], -kv[1]["total_count"]))
    if not items:
        print(f"(no citations for topic_id={topic_id}"
              + (f" engine={engine}" if engine else "") + ")")
        return

    print(f"# topic_id={topic_id}"
          f"{f' engine={engine}' if engine else ''} "
          f"— {len(items)} unique URLs, "
          f"{sum(1 for _, s in items if s['hit_count'] > 0)} ever hit")
    print(f"# owned_already = {len(owned_set)} URL(s) marked 'published'")
    print()
    print(f"{'own':<4} {'hit':>4} {'tot':>4} {'engines':<22}  URL  /  title  /  snippet")
    print("-" * 100)
    for nu, s in items:
        own_mark = "✓" if nu in owned_set else "·"
        eng_str = ",".join(f"{e}:{n}" for e, n in s["engines"].most_common(4))
        print(f"{own_mark:<4} {s['hit_count']:>4} {s['total_count']:>4} "
              f"{eng_str[:22]:<22}  {s['raw_url']}")
        if s["sample_title"]:
            print(f"{'':<4} {'':>4} {'':>4} {'':<22}    title:   {s['sample_title']}")
        if s["sample_snippet"]:
            print(f"{'':<4} {'':>4} {'':>4} {'':<22}    snippet: {s['sample_snippet']}")


# ─────────────────── add 模式 ───────────────────


def _topic_exists(conn, topic_id: int) -> bool:
    r = conn.execute(text(
        "SELECT 1 FROM ai_telemetry_topics WHERE id = :tid"
    ), {"tid": topic_id}).fetchone()
    return r is not None


def _existing_owned(conn, topic_id: int) -> set[str]:
    """该 topic 已有的 published owned URL 集(去重判定用)。"""
    rows = conn.execute(text(
        "SELECT publish_targets_json FROM topic_generated_docs "
        "WHERE topic_id = :tid AND status = 'published'"
    ), {"tid": topic_id}).fetchall()
    out: set[str] = set()
    for (tj,) in rows:
        try:
            tgts = json.loads(tj or "[]")
        except Exception:  # noqa: BLE001
            continue
        if isinstance(tgts, list):
            for t in tgts:
                if isinstance(t, dict):
                    u = t.get("url") or ""
                    if u:
                        out.add(_norm_url(u))
    return out


def add_owned_urls(
    conn, topic_id: int, urls: list[str],
    title: str, source: str, dry_run: bool,
) -> int:
    if not _topic_exists(conn, topic_id):
        print(f"ERROR: topic_id={topic_id} not found", file=sys.stderr)
        return 1

    existing = _existing_owned(conn, topic_id)
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat()
    plan: list[tuple[str, str]] = []   # (raw_url, norm_url)
    seen: set[str] = set()
    for u in urls:
        u = (u or "").strip()
        if not u:
            continue
        nu = _norm_url(u)
        if not nu:
            continue
        if nu in existing:
            print(f"  skip (already published): {u}", file=sys.stderr)
            continue
        if nu in seen:
            continue
        seen.add(nu)
        plan.append((u, nu))

    if not plan:
        print("nothing to insert", file=sys.stderr)
        return 0

    print(f"{'[dry-run] ' if dry_run else ''}"
          f"will insert {len(plan)} owned URL(s) into topic_id={topic_id} "
          f"as source='{source}' status='published':")
    for u, nu in plan:
        print(f"  {u}")

    if dry_run:
        return 0

    # 实际插:每条 URL 一个 doc
    inserted = 0
    for raw_url, _nu in plan:
        publish_targets = json.dumps([{
            "platform": "web",
            "media": "",
            "url": raw_url,
            "marked_at": now,
            "marked_by": "backfill",
        }], ensure_ascii=False)
        conn.execute(text("""
            INSERT INTO topic_generated_docs (
                topic_id, execution_plan_id,
                created_at, source_query_text,
                title, body_markdown, summary,
                llm_model, generation_error,
                status, selected_for_review,
                review_decision_at, reviewer_id, reject_reason,
                publish_targets_json, source, cited_by_json
            ) VALUES (
                :tid, NULL,
                :now, '',
                :title, '', '',
                '', NULL,
                'published', 0,
                :now, NULL, NULL,
                :ptj, :src, '{}'
            )
        """), {
            "tid": topic_id,
            "now": now,
            "title": title or "",
            "ptj": publish_targets,
            "src": source,
        })
        inserted += 1
    conn.commit()
    print(f"inserted {inserted} doc(s)", file=sys.stderr)
    return 0


# ─────────────────── 主流程 ───────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="owned_urls 回填工具")
    ap.add_argument("--topic-id", type=int, required=True)
    ap.add_argument("--engine", type=str, default=None,
                    help="list 模式过滤引擎,如 --engine 豆包")
    ap.add_argument("--list", dest="do_list", action="store_true")
    ap.add_argument("--add", dest="do_add", action="store_true")
    ap.add_argument("--url", action="append", default=[],
                    help="add 模式,要标为自有的 URL(可重复)")
    ap.add_argument("--from-stdin", action="store_true",
                    help="add 模式,从 stdin 读 URL(每行一个)")
    ap.add_argument("--title", type=str, default="")
    ap.add_argument("--source", type=str, default="user", choices=["user", "ai"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not (args.do_list or args.do_add):
        ap.error("must pass --list or --add")
    if args.do_list and args.do_add:
        ap.error("--list and --add are mutually exclusive")

    db_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    print(f"DB: {db_url}", file=sys.stderr)
    eng = create_engine(db_url)

    if args.do_list:
        with eng.connect() as conn:
            list_cited_urls(conn, args.topic_id, args.engine)
        return 0

    # add 模式
    urls: list[str] = list(args.url)
    if args.from_stdin:
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls:
        print("ERROR: add mode needs --url URL or --from-stdin", file=sys.stderr)
        return 2

    with eng.begin() as conn:
        return add_owned_urls(
            conn, args.topic_id, urls, args.title, args.source, args.dry_run,
        )


if __name__ == "__main__":
    sys.exit(main())
