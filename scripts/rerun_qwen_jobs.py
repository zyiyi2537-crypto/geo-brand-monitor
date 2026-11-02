"""重跑指定 qwen browser_jobs(用修好的 qwen_query 流程,带换号重试),结果写 /tmp/qwen_rerun.json。
在 browser-service venv 跑(import app.qwen_query)。去重查询,每个唯一查询最多重试 3 次。
用法: ENGINE_SESSION_POOL_URL=... ENGINE_SESSION_SERVICE_TOKEN=... python rerun_qwen_jobs.py
"""
import asyncio
import json
import sys

sys.path.insert(0, "/opt/browser-service")
from app.qwen_query import run  # noqa: E402

JOBS = {
    61: "喉咙痛喷雾剂哪种好",
    63: "润喉喷雾哪个好",
    64: "好分贝润喉喷雾有人用过吗",
    65: "声音嘶哑喷雾剂",
    66: "喉咙痛喷雾剂哪种好",
    67: "声音嘶哑喷雾剂",
    68: "声音嘶哑喷雾剂",
}


async def main():
    uniq = {}
    for jid, q in JOBS.items():
        uniq.setdefault(q, []).append(jid)
    by_query = {}
    for q in uniq:
        d = {"answer": "", "citations": [], "error": "no attempt"}
        for attempt in range(3):
            d = await run(q)
            if d.get("answer"):
                break
            print(f"[{q}] attempt {attempt+1} empty/err={d.get('error')}, retry…", flush=True)
        by_query[q] = {"answer": d.get("answer", ""), "citations": d.get("citations", []),
                       "error": d.get("error")}
        print(f"[{q}] FINAL ans_len={len(by_query[q]['answer'])} "
              f"cites={len(by_query[q]['citations'])} err={by_query[q]['error']}", flush=True)
    out = {str(jid): by_query[q] for jid, q in JOBS.items()}
    with open("/tmp/qwen_rerun.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("WROTE /tmp/qwen_rerun.json", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
