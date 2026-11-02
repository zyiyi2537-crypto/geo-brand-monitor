#!/usr/bin/env python3
"""Diagnose what happens when an un-logged-in browser hits chatgpt.com.

Loads chatgpt.com headed (with the same Linux-disguise stealth as
chatgpt_login.py) and records:
  - full URL navigation chain (every redirect)
  - all console messages (errors, warnings)
  - every HTTP response (status, url) with non-2xx highlighted
  - final landing URL + page <title>
  - body text first 500 chars (for the auth-error page text)

Output goes to /tmp/chatgpt_diagnose.json so we can inspect afterward.

Usage:
    venv/bin/python backend/scripts/diagnose_chatgpt_redirect.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browser_engine.anti_detect import (
    _pick_profile,
    get_launch_options,
    get_context_options_international,
    build_stealth_js_for_profile,
)


async def main() -> None:
    profile = _pick_profile(platform_filter="Linux x86_64")

    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = None
    try:
        browser = await pw.chromium.launch(
            **get_launch_options(headless=False, profile=profile, channel="chrome")
        )
    except Exception:
        browser = await pw.chromium.launch(
            **get_launch_options(headless=False, profile=profile)
        )

    ctx = await browser.new_context(
        **get_context_options_international(profile=profile)
    )
    await ctx.add_init_script(
        build_stealth_js_for_profile(profile, international=True)
    )

    page = await ctx.new_page()

    nav_chain: list[dict] = []
    console_msgs: list[dict] = []
    responses: list[dict] = []
    requests_failed: list[dict] = []

    page.on("framenavigated", lambda f: (
        f == page.main_frame
        and nav_chain.append({"t": time.time(), "url": f.url})
    ))
    page.on("console", lambda m: console_msgs.append({
        "t": time.time(),
        "type": m.type,
        "text": m.text[:500],
    }))

    def _on_response(r):
        try:
            responses.append({
                "t": time.time(),
                "status": r.status,
                "url": r.url,
                "ct": r.headers.get("content-type", "")[:80],
            })
        except Exception:
            pass

    page.on("response", _on_response)
    page.on("requestfailed", lambda r: requests_failed.append({
        "t": time.time(),
        "url": r.url,
        "failure": r.failure,
    }))

    print("Navigating to https://chatgpt.com/ ...")
    nav_chain.append({"t": time.time(), "url": "https://chatgpt.com/ (start)"})
    try:
        await page.goto(
            "https://chatgpt.com/",
            wait_until="networkidle",
            timeout=45000,
        )
    except Exception as e:
        print(f"  goto warning: {type(e).__name__}: {e}")

    # Let SPA settle
    await asyncio.sleep(3)

    final_url = page.url
    title = await page.title()

    # Page body snippet
    body_text = ""
    try:
        body_text = await page.evaluate(
            "() => document.body ? document.body.innerText.slice(0, 1000) : ''"
        )
    except Exception:
        pass

    # Cookie snapshot
    cookies = await ctx.cookies()
    cookie_names = sorted({c["name"] for c in cookies})

    out = {
        "final_url": final_url,
        "final_title": title,
        "body_text_first_1000": body_text,
        "navigation_chain": [n["url"] for n in nav_chain],
        "cookies": cookie_names,
        "non_2xx_responses": [
            r for r in responses
            if r["status"] >= 300 and r["status"] not in (301, 302, 303, 307, 308)
        ][:50],
        "redirect_responses": [
            r for r in responses
            if r["status"] in (301, 302, 303, 307, 308)
        ][:50],
        "console_errors": [
            m for m in console_msgs if m["type"] in ("error", "warning")
        ][:30],
        "requests_failed": requests_failed[:30],
        "total_responses": len(responses),
        "total_console_msgs": len(console_msgs),
    }

    out_path = "/tmp/chatgpt_diagnose.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 70)
    print("Final landing URL:", final_url)
    print("Page title:       ", title)
    print()
    print("Navigation chain:")
    for i, n in enumerate(nav_chain):
        print(f"  {i}: {n['url']}")
    print()
    print(f"Cookies: {len(cookie_names)} total")
    print(f"  names: {cookie_names}")
    print()
    print(f"Non-2xx (non-redirect) responses: {len(out['non_2xx_responses'])}")
    for r in out["non_2xx_responses"][:10]:
        print(f"  {r['status']} {r['url'][:120]}")
    print()
    print(f"3xx redirects: {len(out['redirect_responses'])}")
    for r in out["redirect_responses"][:10]:
        print(f"  {r['status']} {r['url'][:120]}")
    print()
    print(f"Console errors/warnings: {len(out['console_errors'])}")
    for m in out["console_errors"][:10]:
        print(f"  [{m['type']}] {m['text'][:200]}")
    print()
    print(f"Body text (first 500 chars):")
    print(f"  {body_text[:500]!r}")
    print()
    print(f"Full output: {out_path}")
    print("=" * 70)

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
