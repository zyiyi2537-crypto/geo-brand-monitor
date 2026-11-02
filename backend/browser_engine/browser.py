"""Shared Playwright browser lifecycle management.

Provides a singleton browser instance that all browser adapters share, with
anti-detection and session support.
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Optional

from .anti_detect import (
    build_stealth_js_for_profile,
    _pick_profile,
    get_context_options,
    get_context_options_international,
    get_launch_options,
)
from .session_store import load_storage_state, load_engine_profile, save_storage_state


async def apply_stealth_to_context(
    context, *, international: bool = False, profile: dict | None = None
) -> None:
    """Inject stealth JS at context level so it runs on every page navigation.

    The profile passed here MUST match the UA used for the context — otherwise
    navigator.userAgent (set by Playwright from context UA) will contradict
    navigator.platform / WebGL renderer (set by this stealth JS), which is an
    instant tell for advanced anti-bot systems (e.g. ByteDance / Doubao).
    """
    if profile is None:
        profile = _pick_profile()
    js = build_stealth_js_for_profile(profile, international=international)
    await context.add_init_script(js)

# Note: we previously layered playwright-stealth on top of our own stealth JS,
# but its randomized profile selection was reintroducing UA/platform/WebGL
# mismatches (the same fingerprint inconsistency we now guard against
# explicitly). All stealth is applied via apply_stealth_to_context() bound to
# a single per-session profile.

_browser = None
_lock = None
_pw_instance = None  # Keep reference to prevent GC


async def get_browser():
    """Get or create the shared Playwright browser instance.

    The launch UA arg is mostly cosmetic — actual UA is set per-context in
    create_stealth_page(). What matters is that the browser is launched once
    and reused across contexts, so per-context profile selection drives the
    visible fingerprint.
    """
    global _browser, _lock, _pw_instance
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if _browser is None or not _browser.is_connected():
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                raise RuntimeError(
                    "playwright is not installed. Run: pip install playwright && playwright install chromium"
                )
            _pw_instance = await async_playwright().start()

            # Set PLAYWRIGHT_HEADLESS=0 for headed mode (e.g. for debugging)
            use_headless = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"
            _browser = await _pw_instance.chromium.launch(**get_launch_options(headless=use_headless))
        return _browser


async def create_stealth_page(
    engine_name: str,
    *,
    locale: str | None = None,
    timezone_id: str | None = None,
    record_video: bool = False,
    profile: dict | None = None,
):
    """Create a new browser page with anti-detection and full session state.

    Args:
        engine_name: Engine identifier for session loading (e.g. "deepseek", "gemini").
        locale: Override locale (e.g. "en-US"). Defaults to "zh-CN".
        timezone_id: Override timezone (e.g. "America/New_York"). Defaults to "Asia/Shanghai".
        record_video: If True, record the session as an MP4 video.
        profile: Pre-picked UA/platform/WebGL profile dict. Pass the same
            profile across multiple page creations within one query lifecycle
            (e.g. headless → headed CAPTCHA retry) so the device identity
            stays consistent. If omitted, a random profile is picked.
    """
    international = locale is not None and locale != "zh-CN"
    browser = await get_browser()

    # Pick ONE profile up-front and use it everywhere: context UA, stealth JS
    # platform/vendor, and WebGL renderer. Mismatching these is the #1 way
    # ByteDance-style anti-bot systems detect Playwright.
    if profile is None:
        profile = _pick_profile()

    if locale and timezone_id:
        ctx_opts = get_context_options(
            locale=locale, timezone_id=timezone_id, profile=profile
        )
    elif international:
        ctx_opts = get_context_options_international(profile=profile)
    else:
        ctx_opts = get_context_options(profile=profile)

    # Restore full storage_state (cookies + localStorage) if available
    state = load_storage_state(engine_name)
    if state:
        ctx_opts["storage_state"] = state

    # Video recording
    if record_video:
        from .video_store import get_snapshot_dir
        video_dir = str(get_snapshot_dir(engine_name))
        ctx_opts["record_video_dir"] = video_dir
        ctx_opts["record_video_size"] = {"width": 1920, "height": 1080}

    context = await browser.new_context(**ctx_opts)

    # Apply stealth at context level BEFORE creating the page so init scripts
    # run on the very first navigation. Always apply our profile-bound stealth
    # JS — playwright-stealth's randomized injection would re-pick a different
    # platform and reintroduce the very mismatch we're guarding against.
    await apply_stealth_to_context(
        context, international=international, profile=profile
    )

    page = await context.new_page()
    return page, context


async def create_headed_page(
    engine_name: str,
    *,
    locale: str | None = None,
    timezone_id: str | None = None,
    profile: dict | None = None,
):
    """Create a headed (visible) browser page for manual CAPTCHA handling.

    Launches a separate browser instance (not the shared headless one) with
    a visible window. When the adapter detects CAPTCHA, it can call this to
    let the user manually complete verification in the browser window.

    Pass `profile` to keep the device fingerprint identical to the headless
    context that just hit the CAPTCHA — switching profiles mid-flow looks
    like "different device", which escalates ByteDance's challenge.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright is not installed")

    international = locale is not None and locale != "zh-CN"
    pw = await async_playwright().start()

    if profile is None:
        profile = _pick_profile()
    browser = await pw.chromium.launch(**get_launch_options(headless=False, profile=profile))

    if locale and timezone_id:
        ctx_opts = get_context_options(
            locale=locale, timezone_id=timezone_id, profile=profile
        )
    elif international:
        ctx_opts = get_context_options_international(profile=profile)
    else:
        ctx_opts = get_context_options(profile=profile)

    state = load_storage_state(engine_name)
    if state:
        ctx_opts["storage_state"] = state

    context = await browser.new_context(**ctx_opts)

    await apply_stealth_to_context(
        context, international=international, profile=profile
    )

    page = await context.new_page()

    # Attach pw + browser references so caller can close them later
    page._pw_ref = pw
    page._headed_browser = browser
    return page, context


async def create_persistent_chrome_context(
    engine_name: str,
    *,
    profile: dict,
    locale: str = "en-US",
    timezone_id: str = "America/New_York",
):
    """Create a persistent Chrome context for Cloudflare-gated engines.

    Uses launch_persistent_context + channel="chrome" so that:
    1. Real Chrome binary → Sec-CH-UA brand includes "Google Chrome"
    2. Persistent user_data_dir → CF sees a "mature profile" with cache/history
    3. Saved profile dict → fingerprint matches the login-time identity

    Each engine gets its own user_data_dir so cookies/cache/history persist
    across runs. storage_state is injected via add_cookies() + localStorage
    eval (launch_persistent_context doesn't accept storage_state directly).
    """
    from playwright.async_api import async_playwright
    from pathlib import Path

    pw = await async_playwright().start()

    use_headless = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"

    # Try real Chrome first (Sec-CH-UA brand "Google Chrome"); on hosts
    # without it (notably Linux ARM64 — Google publishes no Chrome ARM64
    # binary), fall back to bundled chromium. Our extra_http_headers in
    # get_context_options already forces the Sec-CH-UA brand list to
    # include "Google Chrome" so HTTP-layer brand check still passes.
    #
    # NOTE: we deliberately use launch + new_context, NOT
    # launch_persistent_context. Empirically the persistent-context
    # variant trips a Cloudflare deep challenge ("Just a moment...")
    # even on a clean user_data_dir with no cookies — likely because
    # Chromium writes default Preferences / Local State that look like
    # a "half-aged" profile to CF's heuristics. Plain new_context with
    # storage_state replay is what verify_chatgpt_fingerprint already
    # proved passes CF on this server's IP.
    browser = None
    last_err = None
    for ch in ("chrome", None):
        try:
            launch_opts = get_launch_options(
                headless=use_headless, profile=profile, channel=ch,
            )
            browser = await pw.chromium.launch(**launch_opts)
            break
        except Exception as e:
            last_err = e
            continue
    if browser is None:
        await pw.stop()
        raise RuntimeError(
            f"Could not launch Chrome or bundled Chromium: {last_err}"
        )

    ctx_opts = get_context_options(
        locale=locale, timezone_id=timezone_id, profile=profile,
    )
    context = await browser.new_context(**ctx_opts)

    # Order matters here. Cloudflare flags any browser whose first request
    # already carries a session-token cookie ("cookie replay" pattern) and
    # serves a deep "Just a moment..." challenge that we cannot pass without
    # interactive Turnstile. To avoid this:
    #
    #   1. Apply stealth init script first.
    #   2. Open a fresh page and goto each origin from state — this lets CF
    #      see a clean browser, issue cf_clearance + infra cookies normally.
    #   3. Only THEN inject the saved session-token + other auth cookies.
    #   4. Reload so the server-side sees the now-authenticated request.
    #
    # localStorage is injected during step 2 (we are already on the origin).
    state = load_storage_state(engine_name)

    await apply_stealth_to_context(context, international=True, profile=profile)
    page = await context.new_page()

    if state and state.get("origins"):
        for origin in state["origins"]:
            origin_url = origin.get("origin")
            if not origin_url:
                continue
            try:
                # Clean first visit — no auth cookies yet — so CF treats us
                # as a normal first-time visitor. CF serves a transparent
                # challenge page; the embedded JS auto-solves and redirects
                # to the real origin in a few seconds. wait_until="load" +
                # explicit URL polling ensures we don't stop on the middle
                # challenge page.
                await page.goto(origin_url, wait_until="load", timeout=45000)
                for _ in range(60):
                    cur_url = page.url or ""
                    try:
                        cur_title = await page.title() or ""
                    except Exception:
                        cur_title = ""
                    if (
                        "__cf_chl_rt_tk" not in cur_url
                        and "/cdn-cgi/challenge-platform" not in cur_url
                        and "Just a moment" not in cur_title
                        and "Verifying" not in cur_title
                    ):
                        break
                    await asyncio.sleep(0.5)
                for item in origin.get("localStorage", []):
                    await page.evaluate(
                        "([k, v]) => localStorage.setItem(k, v)",
                        [item["name"], item["value"]],
                    )
            except Exception:
                pass

    if state and state.get("cookies"):
        # Strip Cloudflare's own session cookies before injecting. They are
        # machine-specific (CF binds them to TLS fingerprint + IP); replaying
        # CF cookies from another host triggers a deep "Just a moment..."
        # challenge on the new host. Let CF re-issue these naturally — our
        # stealth + Linux profile already proved able to clear CF on a clean
        # browser via verify_chatgpt_fingerprint.
        _CF_OWNED = {"__cf_bm", "__cflb", "_cfuvid", "cf_clearance"}
        safe_cookies = [
            c for c in state["cookies"]
            if c.get("name") not in _CF_OWNED
        ]
        if safe_cookies:
            await context.add_cookies(safe_cookies)
            try:
                await page.reload(wait_until="load", timeout=45000)
                # Same CF challenge wait as the first goto.
                for _ in range(60):
                    cur_url = page.url or ""
                    try:
                        cur_title = await page.title() or ""
                    except Exception:
                        cur_title = ""
                    if (
                        "__cf_chl_rt_tk" not in cur_url
                        and "/cdn-cgi/challenge-platform" not in cur_url
                        and "Just a moment" not in cur_title
                        and "Verifying" not in cur_title
                    ):
                        break
                    await asyncio.sleep(0.5)
            except Exception:
                pass

    # Caller must close in reverse order: ctx.close() → browser.close() → pw.stop()
    page._pw_ref = pw
    page._headed_browser = browser
    return page, context


async def save_page_session(engine_name: str, context) -> None:
    """Save full storage_state (cookies + localStorage) for next run."""
    state = await context.storage_state()
    save_storage_state(engine_name, state)


async def human_delay(min_s: float = 1.0, max_s: float = 3.0) -> None:
    """Random delay to simulate human timing."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def human_type(page, selector: str, text: str, delay_ms: int = 0) -> None:
    """Type text with random per-keystroke delay to simulate human typing."""
    el = page.locator(selector)
    await el.click()
    for ch in text:
        await el.type(ch, delay=random.randint(50, 200))
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)


async def human_move_mouse(page, x: int, y: int, steps: int = 10) -> None:
    """Move mouse to (x,y) with intermediate steps simulating human movement."""
    await page.mouse.move(x, y, steps=steps)


async def human_scroll(page, direction: str = "down", amount: int = 3) -> None:
    """Simulate human scrolling with random delta and pauses."""
    delta = 300 if direction == "down" else -300
    for _ in range(amount):
        await page.mouse.wheel(0, delta + random.randint(-50, 50))
        await asyncio.sleep(random.uniform(0.2, 0.5))


async def human_click(page, x: int, y: int) -> None:
    """Simulate a human click: move mouse, small pause, then click."""
    await human_move_mouse(page, x, y, steps=random.randint(5, 15))
    await asyncio.sleep(random.uniform(0.05, 0.15))
    await page.mouse.click(x, y)


async def simulate_browsing(page, duration: float = 3.0) -> None:
    """Simulate natural browsing behavior: random mouse moves, scrolls, pauses.

    Call this after page load to establish a human-like interaction history
    before submitting any queries.
    """
    import time
    start = time.monotonic()

    viewport = page.viewport_size or {"width": 1920, "height": 1080}
    w, h = viewport["width"], viewport["height"]

    # Random mouse movements across the page
    moves = random.randint(3, 6)
    for _ in range(moves):
        if time.monotonic() - start > duration:
            break
        x = random.randint(100, w - 100)
        y = random.randint(100, h - 200)
        await human_move_mouse(page, x, y, steps=random.randint(8, 20))
        await asyncio.sleep(random.uniform(0.3, 0.8))

    # Natural scrolling — scan the page like a real user
    if time.monotonic() - start < duration:
        scroll_times = random.randint(1, 3)
        for _ in range(scroll_times):
            if time.monotonic() - start > duration:
                break
            await human_scroll(page, "down", amount=random.randint(1, 3))
            await asyncio.sleep(random.uniform(0.3, 0.6))

    # Occasional scroll back up
    if random.random() < 0.3 and time.monotonic() - start < duration:
        await human_scroll(page, "up", amount=random.randint(1, 2))

    # Final pause
    remaining = duration - (time.monotonic() - start)
    if remaining > 0:
        await asyncio.sleep(min(remaining, 1.0))


async def close_browser() -> None:
    """Shut down the shared browser instance."""
    global _browser
    if _browser and _browser.is_connected():
        await _browser.close()
    _browser = None
