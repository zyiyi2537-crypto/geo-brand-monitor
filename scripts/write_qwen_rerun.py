"""把 /tmp/qwen_rerun.json 的 qwen 重跑结果写回 browser_jobs(backend venv + DB_URL)。"""
import json
import os
from datetime import datetime

from sqlalchemy import create_engine, text

data = json.load(open("/tmp/qwen_rerun.json", encoding="utf-8"))
eng = create_engine(os.environ["DB_URL"])
for jid, r in data.items():
    ans = r.get("answer") or ""
    cites = r.get("citations") or []
    status = "done" if ans else "failed"
    with eng.begin() as c:
        c.execute(
            text("UPDATE browser_jobs SET status=:st, answer=:a, citations_json=:c, "
                 "source_url=:s, error=:e, finished_at=:f WHERE id=:id"),
            {"st": status, "a": ans, "c": json.dumps(cites, ensure_ascii=False),
             "s": (cites[0]["url"] if cites else None),
             "e": (None if ans else r.get("error")), "f": datetime.utcnow(), "id": int(jid)},
        )
    print(f"job {jid} -> {status} ans={len(ans)} cites={len(cites)}")
