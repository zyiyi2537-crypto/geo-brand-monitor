"""LLM analysis pipeline (OpenAI).

Takes posts that don't yet have an analysis row, asks the model to produce a
structured JSON analysis (sentiment / topics / risk / citations / reasoning),
and persists the result to SQLite.

OpenAI auto-caches stable prompt prefixes (>1024 tokens) since Oct 2024 — no
explicit cache_control needed; just keep the system prompt frozen. Uses JSON
mode so the response is guaranteed-valid JSON.
"""
from __future__ import annotations

import json
import os
import sys
import time

import openai

from storage import (
    connect, init_schema, posts_missing_analysis, upsert_analysis,
)
from llm_client import chat_create, has_openai, has_qwen
from .prompts import ANALYZER_SYSTEM

ANALYZE_MODEL = os.environ.get("YUQING_ANALYZE_MODEL", "gpt-4o-mini")
MAX_TOKENS = 1500


_ALLOWED = {
    "is_relevant", "filter_reason", "summary",
    "sentiment_label", "sentiment_score", "emotions",
    "topics", "entities", "stance", "intent", "factuality",
    "risk_level", "risk_signals", "influence_potential",
    "hidden_meaning", "citations", "reasoning",
}


def _post_block(post) -> str:
    return json.dumps({
        "symbol": post["symbol"],
        "source": post["source"],
        "post_id": post["post_id"],
        "author": post["author"],
        "title": post["title"],
        "content": post["content"],
        "publish_time": post["publish_time"],
        "view_count": post["view_count"],
        "reply_count": post["reply_count"],
    }, ensure_ascii=False)


def _ensure_key() -> None:
    if not (has_openai() or has_qwen()):
        sys.exit(
            "no LLM key available. Set OPENAI_API_KEY (sk-...) or QWEN_API_KEY "
            "before running an LLM command."
        )


def _analyze_one(post):
    resp = chat_create(
        ANALYZE_MODEL,
        max_completion_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": ANALYZER_SYSTEM},
            {"role": "user", "content":
                f"分析以下帖子并按系统说明输出 JSON：\n\n{_post_block(post)}"},
        ],
    )
    text = resp.choices[0].message.content or ""
    obj = json.loads(text)
    analysis = {k: v for k, v in obj.items() if k in _ALLOWED}
    return analysis, resp.usage


def analyze_symbol(symbol: str, limit: int | None = None,
                   db_path=None, sleep_s: float | None = None) -> dict:
    # 默认节流:免费档(GLM glm-4.5-flash 等)RPM 通常 60,留 buffer 设 1.2s/req.
    # 允许调用方覆盖;cron 跑可以更慢,首跑默认即可.
    if sleep_s is None:
        sleep_s = float(os.environ.get("LLM_THROTTLE_S", "1.2"))
    conn = connect(db_path) if db_path else connect()
    init_schema(conn)

    posts = posts_missing_analysis(conn, symbol, limit=limit)
    if not posts:
        return {"analyzed": 0, "skipped": 0, "cached": 0,
                "input": 0, "output": 0}

    _ensure_key()

    # 并发数: 付费 LLM RPM 高可并发更多, 免费档保守一些
    concurrency = int(os.environ.get("LLM_ANALYZE_CONCURRENCY", "5"))

    if concurrency <= 1:
        return _analyze_serial(conn, posts, symbol, sleep_s)
    return _analyze_concurrent(conn, posts, symbol, concurrency)


def _analyze_serial(conn, posts, symbol, sleep_s):
    """原始串行分析 — 兼容低 RPM 的免费 LLM."""
    analyzed = skipped = 0
    cached = inp = outp = 0

    for i, post in enumerate(posts, 1):
        try:
            analysis, usage = _analyze_one(post)
        except json.JSONDecodeError as e:
            print(f"  [{i}/{len(posts)}] {post['post_id']} parse error: {e}",
                  file=sys.stderr)
            skipped += 1
            continue
        except openai.APIStatusError as e:
            print(f"  [{i}/{len(posts)}] {post['post_id']} API error "
                  f"{e.status_code}: {e.message}", file=sys.stderr)
            skipped += 1
            continue

        upsert_analysis(conn, post["source"], post["post_id"],
                        post["symbol"], analysis, ANALYZE_MODEL)
        conn.commit()
        analyzed += 1
        details = getattr(usage, "prompt_tokens_details", None)
        cached += getattr(details, "cached_tokens", 0) or 0
        inp += usage.prompt_tokens
        outp += usage.completion_tokens

        if i % 5 == 0 or i == len(posts):
            print(f"  [{i}/{len(posts)}] analyzed; "
                  f"in={inp} out={outp} cached={cached}")

        if sleep_s:
            time.sleep(sleep_s)

    return {
        "analyzed": analyzed, "skipped": skipped,
        "cached": cached, "input": inp, "output": outp,
    }


def _analyze_concurrent(conn, posts, symbol, concurrency):
    """并发批量分析 — 显著加速, 适合付费 LLM 或高 RPM."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    analyzed = skipped = 0
    cached = inp = outp = 0

    def _safe_analyze(post):
        try:
            analysis, usage = _analyze_one(post)
            return post, analysis, usage, None
        except (json.JSONDecodeError, openai.APIStatusError) as e:
            return post, None, None, e

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_safe_analyze, p): p for p in posts}
        done = 0
        for fut in as_completed(futures):
            post, analysis, usage, err = fut.result()
            done += 1
            if err:
                print(f"  [{done}/{len(posts)}] {post['post_id']} error: {err}",
                      file=sys.stderr)
                skipped += 1
                continue

            upsert_analysis(conn, post["source"], post["post_id"],
                            post["symbol"], analysis, ANALYZE_MODEL)
            analyzed += 1
            details = getattr(usage, "prompt_tokens_details", None)
            cached += getattr(details, "cached_tokens", 0) or 0
            inp += usage.prompt_tokens
            outp += usage.completion_tokens

            if done % 10 == 0 or done == len(posts):
                print(f"  [{done}/{len(posts)}] analyzed; "
                      f"in={inp} out={outp} cached={cached}")

    conn.commit()

    return {
        "analyzed": analyzed, "skipped": skipped,
        "cached": cached, "input": inp, "output": outp,
    }
