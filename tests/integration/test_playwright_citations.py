#!/usr/bin/env python3
"""Test Playwright citation extraction for multiple AI engines.

Usage:
    python test_playwright_citations.py                          # test default engines
    python test_playwright_citations.py --engines copilot        # test Copilot (no login needed)
    python test_playwright_citations.py --engines deepseek qwen  # test specific engines
    python test_playwright_citations.py --engines all            # test all available engines
    python test_playwright_citations.py --query "Tesla Model S"  # custom query
    python test_playwright_citations.py --engines all --query "小米汽车"  # all + Chinese query
"""

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from browser_engine.session_store import load_storage_state
from browser_engine.browser import close_browser


# All available engines — (engine_key, module_path, class_name, needs_login)
ALL_ENGINES = {
    # ── 国内引擎 ──
    "deepseek":  ("backend.browser_engine.engines.deepseek_browser",  "DeepSeekBrowserAdapter",  False),
    "doubao":    ("backend.browser_engine.engines.doubao_browser",    "DoubaoBrowserAdapter",    False),
    "qwen":      ("backend.browser_engine.engines.qwen_browser",     "QwenBrowserAdapter",      True),
    "wenxin":    ("backend.browser_engine.engines.wenxin_browser",   "WenxinBrowserAdapter",    True),
    "yuanbao":   ("backend.browser_engine.engines.yuanbao_browser",  "YuanbaoBrowserAdapter",   False),
    # ── 海外引擎 ──
    "chatgpt":   ("backend.browser_engine.engines.chatgpt_browser",  "ChatGPTBrowserAdapter",   False),
    "gemini":    ("backend.browser_engine.engines.gemini_browser",   "GeminiBrowserAdapter",    False),
    "grok":      ("backend.browser_engine.engines.grok_browser",     "GrokBrowserAdapter",      False),
    "claude":    ("backend.browser_engine.engines.claude_browser",   "ClaudeBrowserAdapter",    False),
    "copilot":   ("backend.browser_engine.engines.copilot_browser",  "CopilotBrowserAdapter",   True),  # anonymous OK
}

ENGINE_NAMES = sorted(ALL_ENGINES.keys())


def _check_session(engine: str) -> bool:
    state = load_storage_state(engine)
    if state:
        n_cookies = len(state.get("cookies", []))
        return n_cookies > 0
    return False


def _print_result(engine: str, result, elapsed: float):
    print(f"\n{'='*60}")
    print(f"  {engine}  ({elapsed:.1f}s)")
    print(f"{'='*60}")

    if result.error:
        print(f"  ERROR: {result.error}")
        return

    answer = result.answer or ""
    print(f"  Answer: {answer[:300]}{'...' if len(answer) > 300 else ''}")
    print(f"  Answer length: {len(answer)} chars")

    citations = result.citations or []
    print(f"  Citations: {len(citations)}")

    if citations:
        print(f"\n  {'#':<4} {'Domain':<30} {'Title':<40} {'URL'}")
        print(f"  {'-'*4} {'-'*30} {'-'*40} {'-'*40}")
        for c in citations:
            title = (c.title or "")[:38]
            domain = c.domain or ""
            url = (c.url or "")[:80]
            print(f"  {c.position:<4} {domain:<30} {title:<40} {url}")


async def test_engine(engine_name: str, query: str) -> tuple:
    if engine_name not in ALL_ENGINES:
        print(f"  Unknown engine: {engine_name}")
        return engine_name, None, 0

    module_path, class_name, optional_session = ALL_ENGINES[engine_name]

    # Check session
    has_session = _check_session(engine_name)
    if optional_session:
        status = "session OK" if has_session else "no session (optional)"
    else:
        status = "session OK" if has_session else "NO SESSION (login required)"
    print(f"\n[{engine_name}] {status} — starting test with query: '{query}'")

    import importlib
    mod = importlib.import_module(module_path)
    adapter_cls = getattr(mod, class_name)
    adapter = adapter_cls()

    t0 = time.time()
    try:
        result = await adapter.search(query)
    except Exception as e:
        from api_engine.base import EngineResult
        result = EngineResult(engine=engine_name, query=query, error=str(e))
    elapsed = time.time() - t0

    _print_result(engine_name, result, elapsed)
    return engine_name, result, elapsed


async def main():
    parser = argparse.ArgumentParser(
        description="Test Playwright citation extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available engines:
  国内: deepseek, doubao, qwen, wenxin, yuanbao
  海外: chatgpt, gemini, grok, claude, copilot

Note: copilot works without login. All others require a valid session.
        """,
    )
    parser.add_argument(
        "--engines", "-e",
        nargs="+",
        default=["deepseek", "copilot"],
        choices=ENGINE_NAMES + ["all", "cn", "global", "available"],
        help="Engines to test. 'all'=全部, 'cn'=国内, 'global'=海外, 'available'=有session的. (default: deepseek copilot)",
    )
    parser.add_argument(
        "--query", "-q",
        default="小米汽车",
        help='Test query (default: "小米汽车")',
    )
    parser.add_argument(
        "--parallel", "-p",
        action="store_true",
        help="Run engines in parallel (faster but uses more resources)",
    )
    args = parser.parse_args()

    # Resolve engine groups
    selected = args.engines
    if "all" in selected:
        selected = ENGINE_NAMES
    elif "cn" in selected:
        selected = ["deepseek", "doubao", "qwen", "wenxin", "yuanbao"]
    elif "global" in selected:
        selected = ["chatgpt", "gemini", "grok", "claude", "copilot"]
    elif "available" in selected:
        selected = [
            k for k, (_, _, optional) in ALL_ENGINES.items()
            if _check_session(k) or optional
        ]
        if not selected:
            print("No engines with sessions found. Try --engines copilot (no login needed).")
            return

    print(f"Query: '{args.query}'")
    print(f"Engines: {selected}")
    print(f"Mode: {'parallel' if args.parallel else 'sequential'}")
    print()

    results = {}
    timings = {}

    if args.parallel:
        # Run all engines in parallel
        tasks = [test_engine(e, args.query) for e in selected]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        for tr in task_results:
            if isinstance(tr, Exception):
                print(f"  Task failed: {tr}")
            else:
                name, result, elapsed = tr
                results[name] = result
                timings[name] = elapsed
    else:
        # Run sequentially
        for engine in selected:
            name, result, elapsed = await test_engine(engine, args.query)
            results[name] = result
            timings[name] = elapsed

    # Cleanup
    try:
        await close_browser()
    except Exception:
        pass

    # Summary table
    print(f"\n{'='*80}")
    print(f"  SUMMARY — Query: '{args.query}'")
    print(f"{'='*80}")
    print(f"  {'Engine':<12} {'Status':<10} {'Answer':<14} {'Citations':<12} {'Time':<10} {'Notes'}")
    print(f"  {'-'*12} {'-'*10} {'-'*14} {'-'*12} {'-'*10} {'-'*20}")

    for name in selected:
        r = results.get(name)
        if r is None:
            print(f"  {name:<12} {'SKIP':<10} {'—':<14} {'—':<12} {'—':<10}")
            continue
        t = timings.get(name, 0)
        if r.error:
            status = "ERROR"
            ans_len = "—"
            cites = "—"
            notes = r.error[:40]
        else:
            status = "OK"
            ans_len = f"{len(r.answer or '')} chars"
            cites = str(len(r.citations or []))
            notes = ""
        print(f"  {name:<12} {status:<10} {ans_len:<14} {cites:<12} {t:.1f}s{'':<5} {notes}")

    # Total citations
    total_cites = sum(
        len(r.citations or []) for r in results.values() if r and not r.error
    )
    print(f"\n  Total citations across all engines: {total_cites}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
