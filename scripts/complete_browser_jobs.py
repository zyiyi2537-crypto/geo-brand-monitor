#!/usr/bin/env python3
"""一次性 ops:把指定的 browser_jobs(queued)用 browser-service /search-hot 跑出
结果并回写(status/answer/citations_json/source_url/finished_at)。

deepseek 走 /search-hot 的纯 HTTP 分支 —— 直接 check-out 账号、**绕过 claim 的
全局日 cap**,所以即便 deepseek 当天已超 cap 也能完成这几条。

用法:
  DB_URL=postgresql+psycopg://user:pass@host:9000/appdb \
  python complete_browser_jobs.py --base http://127.0.0.1:8092 --jobs 57,58,59,60
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime

from sqlalchemy import create_engine, text


def search_hot(base: str, engine: str, query: str, timeout: int) -> dict:
    body = json.dumps({"engine": engine, "query": query}).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/search-hot", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8092")
    ap.add_argument("--jobs", required=True, help="逗号分隔的 browser_jobs id")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    db_url = os.environ["DB_URL"]
    ids = [int(x) for x in args.jobs.split(",") if x.strip()]
    eng = create_engine(db_url)

    with eng.begin() as c:
        rows = c.execute(
            text("SELECT id, engine, query FROM browser_jobs "
                 "WHERE id = ANY(:ids) AND status='queued' ORDER BY id"),
            {"ids": ids},
        ).fetchall()

    if not rows:
        print("没有匹配的 queued job:", ids)
        return

    for jid, engine, query in rows:
        print(f"\n[job {jid}] engine={engine} query={query!r} 跑中…")
        try:
            res = search_hot(args.base, engine, query, args.timeout)
        except Exception as e:  # noqa: BLE001
            print(f"[job {jid}] /search-hot 异常: {e!r}")
            continue
        answer = res.get("answer") or ""
        cites = res.get("citations") or []
        err = res.get("error")
        source_url = cites[0]["url"] if cites else None
        ok = bool(answer) and not err
        status = "done" if ok else "failed"
        with eng.begin() as c:
            c.execute(
                text("UPDATE browser_jobs SET status=:st, answer=:a, "
                     "citations_json=:cj, source_url=:su, error=:err, "
                     "finished_at=:fa WHERE id=:id"),
                {"st": status, "a": answer,
                 "cj": json.dumps(cites, ensure_ascii=False),
                 "su": source_url, "err": err,
                 "fa": datetime.utcnow(), "id": jid},
            )
        print(f"[job {jid}] -> {status}  ans_len={len(answer)} cites={len(cites)} err={err!r}")


if __name__ == "__main__":
    main()
