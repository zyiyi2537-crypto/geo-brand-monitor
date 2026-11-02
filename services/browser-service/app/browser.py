"""Shared Playwright browser lifecycle management.

Provides a singleton browser instance that all browser adapters share, with
anti-detection and session support.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
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
            _browser = await _pw_instance.chromium.launch(**get_launch_options(
                headless=use_headless, channel="chrome" if os.name == "nt" else None
            ))
        return _browser


def _windows_profile_for_browser(profile: dict, browser) -> dict:
    """Keep the declared Chrome version aligned with the launched binary."""
    if os.name != "nt":
        return profile
    version = str(browser.version)
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
        return profile
    native = dict(profile)
    native["ua"] = re.sub(r"Chrome/[\d.]+", f"Chrome/{version}", profile["ua"])
    return native


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
    profile = _windows_profile_for_browser(profile, browser)

    if locale and timezone_id:
        ctx_opts = get_context_options(
            locale=locale, timezone_id=timezone_id, profile=profile
        )
    elif international:
        ctx_opts = get_context_options_international(profile=profile)
    else:
        ctx_opts = get_context_options(profile=profile)

    # Restore full storage_state (cookies + localStorage) if available
    state = None if os.environ.get("BROWSER_LOGIN_SKIP_SESSION") == "1" else load_storage_state(engine_name)
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


def _sticky_id_from_state(state: dict | None) -> str | None:
    """从 storage_state 算一个稳定的账号标识(用于 proxy sticky session)。
    取 cookie 集合里最长的那个值(通常是登录 token)做 hash —— 跨重新加载稳定,
    不依赖 check-out 时机。"""
    if not state:
        return None
    cookies = state.get("cookies") or []
    if not cookies:
        return None
    longest = max((c.get("value", "") or "") for c in cookies)
    if not longest:
        return None
    import hashlib
    return hashlib.md5(longest.encode("utf-8")).hexdigest()[:10]


def _engine_proxy(engine_name: str, state: dict | None = None) -> dict | None:
    """按账号粘定的出口代理。仅对 PROXY_ENGINES 列出的引擎启用(如 deepseek)。

    sticky:proxy 用户名追加 `-session-acct<id>`,同一账号永远走同一出口 IP,避免
    "异地登录"风控。id 优先取刚 check-out 的会话 id,取不到则从 storage_state 算稳定 hash。

    ENV: PROXY_ENGINES(逗号分隔) / ENGINE_PROXY_SERVER / ENGINE_PROXY_USER / ENGINE_PROXY_PASS
    """
    # 按账号出口标记(egress)优先:'host' 强制本机 IP(不走代理)、'proxy' 强制走代理;
    # None 时回落到引擎级默认(PROXY_ENGINES 白名单)。这样同一引擎里部分账号走代理 IP、
    # 部分走本机 IP,实现"每 IP 不同平台 + 1 账号/IP"的精确拓扑。
    egress = None
    try:
        from .session_store import get_last_egress
        egress = get_last_egress(engine_name)
    except Exception:  # noqa: BLE001
        egress = None
    if egress == "host":
        return None
    if egress != "proxy":
        engines = [e.strip() for e in os.environ.get("PROXY_ENGINES", "").split(",") if e.strip()]
        if engine_name not in engines:
            return None
    server = os.environ.get("ENGINE_PROXY_SERVER", "").strip()
    user = os.environ.get("ENGINE_PROXY_USER", "").strip()
    pw = os.environ.get("ENGINE_PROXY_PASS", "").strip()
    if not (server and user and pw):
        return None
    sid = None
    try:
        from .session_store import get_last_checkout_id
        sid = get_last_checkout_id(engine_name)
    except Exception:  # noqa: BLE001
        sid = None
    if sid is None:
        sid = _sticky_id_from_state(state)
    username = f"{user}-session-acct{sid}" if sid else user
    return {"server": server, "username": username, "password": pw}


async def create_headed_page(
    engine_name: str,
    *,
    locale: str | None = None,
    timezone_id: str | None = None,
    profile: dict | None = None,
    record_video: bool = False,
    channel: str | None = None,
):
    """Create a headed (visible) browser page for manual CAPTCHA handling.

    Launches a separate browser instance (not the shared headless one) with
    a visible window. When the adapter detects CAPTCHA, it can call this to
    let the user manually complete verification in the browser window.

    Pass `profile` to keep the device fingerprint identical to the headless
    context that just hit the CAPTCHA — switching profiles mid-flow looks
    like "different device", which escalates ByteDance's challenge.

    When `record_video` is True, Playwright records the session to
    data/snapshots/{engine}/*.webm (file is finalized only after the caller
    closes the context).

    Backend(2026-05-13 起):默认 **CloakBrowser**(github.com/CloakHQ/CloakBrowser),
    49+ 个源码级 C++ patches,比 patchright 的 runtime CDP patch 更彻底。
    设置 `DOUBAO_BACKEND=patchright` 可切回 patchright 兜底。

    无论哪个 backend 都不能再叠 `apply_stealth_to_context`(我们的 ~13KB stealth
    JS)—— 那会让 Chrome network service 炸 ERR_NAME_NOT_RESOLVED(2026-05-12
    bisect 确认)。两个 stealth backend 都已经在 CDP/编译层把 navigator/webgl/
    permissions 等 spoof 干完了,我们手写的反而干扰。
    """
    backend = os.environ.get("DOUBAO_BACKEND", "playwright" if os.name == "nt" else "cloakbrowser").lower()
    international = locale is not None and locale != "zh-CN"

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

    state = None if os.environ.get("BROWSER_LOGIN_SKIP_SESSION") == "1" else load_storage_state(engine_name)
    if state:
        ctx_opts["storage_state"] = state

    # 按账号粘定出口代理(仅 PROXY_ENGINES,如 deepseek)。必须在 load_storage_state
    # 之后取,sticky session id 来自刚 check-out 的会话。
    proxy = _engine_proxy(engine_name, state)
    if proxy:
        ctx_opts["proxy"] = proxy
        import sys
        sys.__stdout__.write(f"[proxy] {engine_name} via {proxy['username'].rsplit('-session-',1)[-1]}\n")
        sys.__stdout__.flush()

    if record_video:
        from .video_store import get_snapshot_dir
        ctx_opts["record_video_dir"] = str(get_snapshot_dir(engine_name))
        ctx_opts["record_video_size"] = {"width": 1920, "height": 1080}

    pw = None
    browser = None

    if backend == "cloakbrowser":
        try:
            from cloakbrowser import launch_context_async
        except ImportError:
            raise RuntimeError("cloakbrowser is not installed (pip install cloakbrowser)")
        # CloakBrowser 自带 stealth chromium binary,没有 channel 概念。
        # launch_context_async 直接返回 context(无独立 browser 句柄),
        # 关闭只需 close context;pw_ref/headed_browser 设 None 让 close 兼容路径走过。
        launch_args = None
        if (os.environ.get("GEO_BROWSER_BACKGROUND", "").strip() == "1"
                and os.environ.get("GEO_BROWSER_PRIVATE_DESKTOP", "").strip() != "1"):
            launch_args = ["--start-minimized", "--window-position=-32000,-32000"]
        context = await launch_context_async(headless=False, args=launch_args, **ctx_opts)
    else:
        # Windows uses the installed Chrome through standard Playwright.
        if backend == "playwright":
            from playwright.async_api import async_playwright
        else:
            try:
                from patchright.async_api import async_playwright
            except ImportError:
                raise RuntimeError("patchright is not installed (pip install patchright)")
        if channel is None and os.name == "nt":
            channel = "chrome"
        pw = await async_playwright().start()
        last_err = None
        for ch in (channel, None) if channel else (None,):
            try:
                launch_opts = get_launch_options(headless=False, profile=profile, channel=ch)
                browser = await pw.chromium.launch(**launch_opts)
                break
            except Exception as e:
                last_err = e
                continue
        if browser is None:
            await pw.stop()
            raise RuntimeError(f"create_headed_page: launch failed (channel={channel}): {last_err}")
        profile = _windows_profile_for_browser(profile, browser)
        if os.name == "nt":
            ctx_opts["user_agent"] = profile["ua"]
        context = await browser.new_context(**ctx_opts)

    page = await context.new_page()

    # Attach pw + browser references so caller can close them later (both None
    # for cloakbrowser since it manages lifecycle internally).
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
    state = None if os.environ.get("BROWSER_LOGIN_SKIP_SESSION") == "1" else load_storage_state(engine_name)

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


async def save_page_session(engine_name: str, context, account_id: str | None = None) -> None:
    """Save full storage_state (cookies + localStorage) for next run."""
    state = await context.storage_state()
    save_storage_state(engine_name, state, account_id=account_id)


_HUMAN_DELAY_SCALE = float(os.environ.get("BROWSER_DELAY_SCALE", "1.0"))


async def human_delay(min_s: float = 1.0, max_s: float = 3.0) -> None:
    """Random delay to simulate human timing.

    全局缩放因子 BROWSER_DELAY_SCALE(env)允许在不动 100+ 调用点的前提下
    集体提速。默认 1.0(原值);production 推荐 0.25-0.4(对应日批跑批速度
    提升 1.5-2x,反检测信号略减但仍非零)。如果检测到 captcha 增多,把它
    调回去就行。设 0 完全跳过(测试用,不要 production)。
    """
    if _HUMAN_DELAY_SCALE <= 0:
        return
    await asyncio.sleep(random.uniform(min_s * _HUMAN_DELAY_SCALE, max_s * _HUMAN_DELAY_SCALE))


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
