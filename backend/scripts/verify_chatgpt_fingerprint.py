#!/usr/bin/env python3
"""Verify the cross-machine Linux fingerprint disguise BEFORE login.

The whole CF cross-machine plan rests on one assumption: Playwright's
extra_http_headers actually overrides Chromium's automatic Sec-CH-UA-Platform
header. If it doesn't, Mac-launched Chromium will still send "macOS" in the
header, and the cf_clearance issued there will be invalidated the moment
the AWS Linux runtime presents it.

This script proves (or disproves) that assumption WITHOUT requiring an
OpenAI login or passing CF challenge — it captures the very first request
out of the browser and dumps both the HTTP-side and JS-side fingerprint.

Run this BEFORE chatgpt_login.py. If anything fails, do not proceed.

Usage:
    venv/bin/python backend/scripts/verify_chatgpt_fingerprint.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browser_engine.anti_detect import (
    _pick_profile,
    get_launch_options,
    get_context_options_international,
    build_stealth_js_for_profile,
)


async def main() -> int:
    print("=" * 70)
    print("ChatGPT cross-machine fingerprint verification")
    print("=" * 70)

    profile = _pick_profile(platform_filter="Linux x86_64")
    print("Profile chosen:")
    print(f"  platform:           {profile['platform']}")
    print(f"  ua_platform_label:  {profile.get('ua_platform_label')}")
    print(f"  ua (truncated):     {profile['ua'][:80]}...")
    print(f"  ua_brands:          {profile.get('ua_brands')}")
    print()

    if profile["platform"] != "Linux x86_64":
        print("FAIL: _pick_profile did not return Linux profile.")
        return 2

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed. Run: pip install playwright")
        return 2

    pw = await async_playwright().start()

    browser = None
    used_channel = None
    for ch in ("chrome", None):
        try:
            opts = get_launch_options(headless=False, profile=profile, channel=ch)
            browser = await pw.chromium.launch(**opts)
            used_channel = ch or "bundled-chromium"
            break
        except Exception as e:
            print(f"  launch channel={ch!r}: failed ({type(e).__name__}: {e})")
    if browser is None:
        print("FAIL: could not launch browser with any channel.")
        await pw.stop()
        return 2
    print(f"Browser launched via: {used_channel}")
    if used_channel == "bundled-chromium":
        print("  WARN: real Chrome not available. Sec-CH-UA brand list may")
        print("        not include 'Google Chrome' — CF will likely reject.")
        print("        Install with: venv/bin/playwright install chrome")
    print()

    ctx = await browser.new_context(
        **get_context_options_international(profile=profile)
    )
    await ctx.add_init_script(
        build_stealth_js_for_profile(profile, international=True)
    )
    page = await ctx.new_page()

    captured: dict = {}

    def on_request(req):
        if not captured and req.is_navigation_request():
            captured.update(dict(req.headers))
            captured["__url"] = req.url

    page.on("request", on_request)

    # We just need to fire one navigation to capture the headers Chromium
    # actually sends. chatgpt.com is the realistic target — even if CF
    # blocks the response, the request headers are what matter.
    print("Loading https://chatgpt.com/ (only to capture outgoing headers)...")
    try:
        await page.goto(
            "https://chatgpt.com/",
            wait_until="domcontentloaded",
            timeout=20000,
        )
    except Exception as e:
        print(f"  goto warning: {type(e).__name__}: {e}")
        print("  (this is fine — we only need the request headers, not the response)")
    print()

    # JS fingerprint
    js_fp = await page.evaluate(
        """async () => {
        const out = {
            'navigator.userAgent': navigator.userAgent,
            'navigator.platform': navigator.platform,
            'navigator.webdriver': navigator.webdriver,
            'has userAgentData': !!navigator.userAgentData,
            'userAgentData.platform': null,
            'getHighEntropyValues.platform': null,
            'getHighEntropyValues.platformVersion': null,
        };
        if (navigator.userAgentData) {
            out['userAgentData.platform'] = navigator.userAgentData.platform;
            try {
                const h = await navigator.userAgentData.getHighEntropyValues(
                    ['platform', 'platformVersion']
                );
                out['getHighEntropyValues.platform'] = h.platform;
                out['getHighEntropyValues.platformVersion'] = h.platformVersion;
            } catch (e) {
                out['getHighEntropyValues.platform'] = '<error: ' + e.message + '>';
            }
        }
        return out;
    }"""
    )

    print("=== JS fingerprint ===")
    for k, v in js_fp.items():
        print(f"  {k:40} = {v}")
    print()

    print("=== HTTP request headers ===")
    print(f"  url: {captured.get('__url', '<no nav captured>')}")
    for h in (
        "user-agent",
        "sec-ch-ua",
        "sec-ch-ua-platform",
        "sec-ch-ua-mobile",
        "accept-language",
    ):
        v = captured.get(h, "<missing>")
        print(f"  {h:40} = {v}")
    print()

    # Verdict
    print("=== Verdict ===")
    failures: list[str] = []

    h_platform = captured.get("sec-ch-ua-platform", "").strip('"')
    if h_platform == "Linux":
        print("  [OK]   HTTP sec-ch-ua-platform = 'Linux'")
    else:
        print(
            f"  [FAIL] HTTP sec-ch-ua-platform = '{h_platform}' "
            f"(expected 'Linux')"
        )
        failures.append("sec-ch-ua-platform header not overridden")

    h_brands = captured.get("sec-ch-ua", "")
    if "Google Chrome" in h_brands:
        print("  [OK]   HTTP sec-ch-ua includes 'Google Chrome'")
    elif "Chromium" in h_brands:
        print(f"  [WARN] HTTP sec-ch-ua = '{h_brands}'")
        print("         CF expects 'Google Chrome' brand. Use channel='chrome'.")
    else:
        print(f"  [WARN] HTTP sec-ch-ua = '{h_brands}'")

    js_uap = js_fp.get("userAgentData.platform")
    if js_uap == "Linux":
        print("  [OK]   JS  navigator.userAgentData.platform = 'Linux'")
    else:
        print(f"  [FAIL] JS  navigator.userAgentData.platform = {js_uap!r}")
        failures.append("navigator.userAgentData.platform not overridden")

    js_high = js_fp.get("getHighEntropyValues.platform")
    if js_high == "Linux":
        print("  [OK]   JS  getHighEntropyValues({platform}) = 'Linux'")
    else:
        print(f"  [FAIL] JS  getHighEntropyValues({{platform}}) = {js_high!r}")
        failures.append("getHighEntropyValues not overridden")

    js_ua = js_fp.get("navigator.userAgent", "")
    if "Linux" in js_ua and "X11" in js_ua:
        print("  [OK]   JS  navigator.userAgent contains Linux/X11")
    else:
        print(
            f"  [FAIL] JS  navigator.userAgent missing Linux marker: "
            f"{js_ua[:80]}..."
        )
        failures.append("navigator.userAgent not overridden")

    js_wd = js_fp.get("navigator.webdriver")
    if js_wd in (False, None):
        print(f"  [OK]   JS  navigator.webdriver = {js_wd}")
    else:
        print(f"  [FAIL] JS  navigator.webdriver = {js_wd}")
        failures.append("webdriver flag visible")

    print()
    if failures:
        print(f"VERIFICATION FAILED ({len(failures)} issue(s)):")
        for f in failures:
            print(f"  - {f}")
        print()
        print("DO NOT run chatgpt_login.py until these are fixed.")
        print()
        print("If sec-ch-ua-platform is the failing one:")
        print("  Playwright's extra_http_headers does not override Chromium's")
        print("  automatic client hints in this version. Workarounds:")
        print("  1. --user-agent-client-hints-platform launch flag (try first)")
        print("  2. Switch to patchright (binary-level override)")
        print("  3. Server-side login via Xvfb+VNC (eliminates cross-machine issue)")
        rc = 1
    else:
        print("ALL CHECKS PASSED.")
        print("Linux disguise is consistent across HTTP headers + JS.")
        print()
        print("Next: venv/bin/python backend/scripts/chatgpt_login.py")
        rc = 0

    print()
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, input, ">>> Press Enter to close browser: "
        )
    except (EOFError, KeyboardInterrupt):
        pass

    await browser.close()
    await pw.stop()
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
