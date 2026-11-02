"""Hybrid backfill for a topic — doubao via ARK Bot + deepseek via vm03 browser.

Models / paths (web-UI parity):
  • Doubao   → ARK Bot endpoint /api/v3/bots/chat/completions
               bot=DOUBAO_BOT_ID  (绑定 Doubao-1.5-pro-32k + 联网搜索插件)
               答案 + references 都是字节自家搜索回来的
  • DeepSeek → vm03 browser-service /search (Playwright cold-start)
               用真 chat.deepseek.com 网页登录态走真浏览器,真原生 web search

Creates a NEW run_id; does not touch failed runs.

Usage (on vm02):
    cd /opt/geo/services/telemetry-service
    DATABASE_URL=sqlite:////opt/geo/backend/data/geo_checker.db \\
      ARK_API_KEY=ark-xxx DOUBAO_BOT_ID=bot-xxxx \\
      BROWSER_SERVICE_CN=http://localhost:8092 \\
      /opt/geo/backend/venv/bin/python -u -m scripts.backfill_topic_api \\
      --topic-id 2 --engines doubao,deepseek --concurrent 2
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

SVC_DIR = Path(__file__).resolve().parent.parent
if str(SVC_DIR) not in sys.path:
    sys.path.insert(0, str(SVC_DIR))

from app.storage import (  # noqa: E402
    TopicORM, db_session, start_run, finish_run, save_response,
    parse_topic, parse_target,
)
from app.tracking import (  # noqa: E402
    detect_hit, initialize_pending_cells, mark_cells_running,
    update_query_hit_after_response,
)


ARK_BOT_URL = "https://ark.cn-beijing.volces.com/api/v3/bots/chat/completions"


async def call_doubao_bot(client: httpx.AsyncClient, query: str, prompt_ext: str) -> dict:
    """ARK Bot endpoint — 联网搜索插件已挂在 bot 上,无需我们手搓 RAG。"""
    key = os.environ.get("ARK_API_KEY", "").strip()
    bot_id = os.environ.get("DOUBAO_BOT_ID", "").strip()
    if not key or not bot_id:
        return {"answer": "", "citations": [], "error": "ARK_API_KEY / DOUBAO_BOT_ID not set"}
    content = f"{query}\n\n{prompt_ext}" if prompt_ext else query
    payload = {
        "model": bot_id,
        "messages": [{"role": "user", "content": content}],
    }
    try:
        r = await client.post(
            ARK_BOT_URL, json=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=120,
        )
        if r.status_code != 200:
            return {"answer": "", "citations": [], "error": f"http_{r.status_code}: {r.text[:200]}"}
        data = r.json()
        if "error" in data:
            return {"answer": "", "citations": [], "error": f"ark_error: {data['error']}"}
        msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
        answer = msg.get("content", "") or ""
        refs = data.get("references") or msg.get("references") or []
        citations: list[dict] = []
        for i, r in enumerate(refs):
            if not isinstance(r, dict):
                continue
            url = r.get("url") or ""
            if not url:
                continue
            citations.append({
                "url": url,
                "title": (r.get("title") or "").strip(),
                "snippet": (r.get("summary") or r.get("snippet") or "").strip()[:500],
                "position": i + 1,
            })
        return {"answer": answer, "citations": citations, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"answer": "", "citations": [], "error": f"exception: {e}"}


async def call_deepseek_browser(client: httpx.AsyncClient, query: str, prompt_ext: str) -> dict:
    """vm03 browser-service /search — Playwright 真浏览器跑 chat.deepseek.com."""
    base = os.environ.get("BROWSER_SERVICE_CN", "http://localhost:8092").rstrip("/")
    content = f"{query}\n\n{prompt_ext}" if prompt_ext else query
    payload = {"engine": "deepseek", "query": content}
    try:
        r = await client.post(
            f"{base}/search", json=payload,
            headers={"Content-Type": "application/json"},
            timeout=240,
        )
        if r.status_code != 200:
            return {"answer": "", "citations": [], "error": f"http_{r.status_code}: {r.text[:200]}"}
        data = r.json()
        err = data.get("error")
        answer = data.get("answer") or ""
        # browser-service citations: [{url, domain, title, snippet, position}]
        citations = []
        for i, c in enumerate(data.get("citations") or []):
            if not isinstance(c, dict):
                continue
            url = c.get("url") or ""
            if not url:
                continue
            citations.append({
                "url": url,
                "title": (c.get("title") or "").strip(),
                "snippet": (c.get("snippet") or "").strip()[:500],
                "position": c.get("position") or (i + 1),
            })
        return {"answer": answer, "citations": citations, "error": err}
    except Exception as e:  # noqa: BLE001
        return {"answer": "", "citations": [], "error": f"exception: {e}"}


ENGINE_CALLERS = {
    "doubao":   call_doubao_bot,
    "deepseek": call_deepseek_browser,
}


async def run_backfill(topic_id: int, engines: list[str], concurrent: int) -> None:
    with db_session() as s:
        topic = s.get(TopicORM, topic_id)
        if topic is None:
            print(f"[backfill] topic {topic_id} not found", file=sys.stderr)
            sys.exit(1)
        queries, _ = parse_topic(topic)
        target, aliases = parse_target(topic)
        prompt_ext = (topic.prompt_extension or "").strip()
        run = start_run(s, topic_id)
        run_id = run.id
        initialize_pending_cells(s, topic)
        mark_cells_running(s, topic)
        topic_name = topic.name

    total = len(queries) * len(engines)
    print(
        f"[backfill] topic_id={topic_id} name={topic_name!r} target={target!r} aliases={aliases}\n"
        f"[backfill] engines={engines} queries={len(queries)} total_cells={total} concurrent={concurrent}\n"
        f"[backfill] run_id={run_id} prompt_ext_len={len(prompt_ext)}\n"
        f"[backfill] doubao_bot={os.environ.get('DOUBAO_BOT_ID')} "
        f"vm03_browser={os.environ.get('BROWSER_SERVICE_CN', 'http://localhost:8092')}",
        flush=True,
    )

    sem = asyncio.Semaphore(concurrent)
    done = 0
    fails = 0
    t0 = time.monotonic()

    async with httpx.AsyncClient() as client:
        async def _one(engine: str, query: str) -> None:
            nonlocal done, fails
            caller = ENGINE_CALLERS[engine]
            async with sem:
                result = await caller(client, query, prompt_ext)

            answer = result.get("answer", "") or ""
            citations = result.get("citations") or []
            error = result.get("error")
            hit, excerpt = (False, None)
            if not error:
                hit, excerpt = detect_hit(answer, target, aliases)

            with db_session() as s:
                r = save_response(
                    s, run_id=run_id, topic_id=topic_id, engine=engine, query=query,
                    answer=answer, citations=citations,
                    video_url=None, source_url=None,
                    error=error, hit=hit, hit_excerpt=excerpt,
                )
                if not error:
                    t_managed = s.get(TopicORM, topic_id)
                    if t_managed is not None:
                        update_query_hit_after_response(s, response=r, topic=t_managed)

            done += 1
            if error:
                fails += 1
            elapsed = time.monotonic() - t0
            tag = "✓" if (not error and hit) else ("·" if not error else "✗")
            print(
                f"  [{done:>3}/{total}] {tag} {engine:<9} ans={len(answer):>5} "
                f"cites={len(citations)} hit={int(hit)} err={(error or '')[:50]:<50} "
                f"({query[:30]!r:<32}) {elapsed:.1f}s",
                flush=True,
            )

        tasks = [_one(e, q) for e in engines for q in queries]
        await asyncio.gather(*tasks)

    status = "success" if fails < total else "failed"
    with db_session() as s:
        finish_run(s, run_id, status, error=None if fails == 0 else f"{fails}/{total} failed")

    print(
        f"\n[backfill] DONE run_id={run_id} status={status} "
        f"total={total} failed={fails} elapsed={time.monotonic()-t0:.1f}s"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--topic-id", type=int, required=True)
    p.add_argument("--engines", default="doubao,deepseek",
                   help="comma-separated, supported: doubao,deepseek (default: both)")
    p.add_argument("--concurrent", type=int, default=2)
    args = p.parse_args()
    engines = [e.strip() for e in args.engines.split(",") if e.strip() in ENGINE_CALLERS]
    if not engines:
        print(f"[backfill] no valid engines (supported: {list(ENGINE_CALLERS)})", file=sys.stderr)
        sys.exit(1)
    asyncio.run(run_backfill(args.topic_id, engines, args.concurrent))


if __name__ == "__main__":
    main()
