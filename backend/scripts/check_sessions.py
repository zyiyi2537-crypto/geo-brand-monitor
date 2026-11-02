#!/usr/bin/env python3
"""Unified browser session health check & re-login tool.

Usage:
    # Check all sessions — shows status table, no login
    python backend/scripts/check_sessions.py

    # Check + re-login invalid ones interactively (requires GUI)
    python backend/scripts/check_sessions.py --fix

    # Check specific platform(s) only
    python backend/scripts/check_sessions.py --only qwen deepseek

    # Re-login all platforms regardless of status
    python backend/scripts/check_sessions.py --fix --all
"""

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browser_engine.session_store import load_storage_state, save_storage_state
from browser_engine.browser import create_stealth_page, close_browser

# ── Platform definitions ──────────────────────────────────────────

PLATFORMS = {
    "qwen": {
        "label": "通义千问",
        "origin": "https://chat.qwen.ai",
        "chat_url": "https://chat.qwen.ai/",
        "login_selector": "textarea.message-input-textarea",
    },
    "deepseek": {
        "label": "DeepSeek",
        "origin": "https://chat.deepseek.com",
        "chat_url": "https://chat.deepseek.com/",
        "login_selector": "textarea",
    },
    "wenxin": {
        "label": "文心一言",
        "origin": "https://chat.baidu.com",
        "chat_url": "https://chat.baidu.com/",
        "login_selector": "textarea, [contenteditable='true']",
    },
    "doubao": {
        "label": "豆包",
        "origin": "https://www.doubao.com",
        "chat_url": "https://www.doubao.com/chat/",
        "login_selector": "[contenteditable='true'], textarea",
    },
}

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ── Local session analysis (no browser needed) ────────────────────

def analyze_session(name: str) -> dict:
    """Analyze saved session file without launching browser."""
    info = {
        "name": name,
        "label": PLATFORMS[name]["label"],
        "has_session": False,
        "total_cookies": 0,
        "valid_cookies": 0,
        "expired_cookies": 0,
        "session_cookies": 0,
        "ls_entries": 0,
        "expired_names": [],
        "online": None,  # None = not tested
    }

    state = load_storage_state(name)
    if not state:
        return info

    info["has_session"] = True
    now = time.time()

    for c in state.get("cookies", []):
        info["total_cookies"] += 1
        exp = c.get("expires", -1)
        if exp <= 0:
            info["session_cookies"] += 1
        elif exp < now:
            info["expired_cookies"] += 1
            info["expired_names"].append(c["name"])
        else:
            info["valid_cookies"] += 1

    for o in state.get("origins", []):
        info["ls_entries"] += len(o.get("localStorage", []))

    return info


# ── Online check via Playwright ────────────────────────────────────

async def check_online(name: str) -> bool:
    """Launch headless browser, navigate to chat URL, check if logged in."""
    cfg = PLATFORMS[name]
    try:
        page, ctx = await create_stealth_page(name)
        await page.goto(cfg["chat_url"], wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        count = await page.locator(cfg["login_selector"]).count()
        await ctx.close()
        return count > 0
    except Exception:
        return False


# ── Interactive re-login ───────────────────────────────────────────

async def interactive_relogin(name: str) -> bool:
    """Launch headed browser for manual re-login."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(f"  {RED}playwright not installed{RESET}")
        return False

    cfg = PLATFORMS[name]
    print(f"\n  {CYAN}Opening {cfg['chat_url']} for {cfg['label']} login...{RESET}")
    print(f"  Log in manually, then come back here and press Enter.\n")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
    )
    page = await ctx.new_page()

    try:
        await page.goto(cfg["chat_url"], timeout=30000)
    except Exception as e:
        print(f"  Warning: page load issue ({e}), browser should still be open.")

    await asyncio.get_event_loop().run_in_executor(
        None, input, f"  >>> Press Enter after login is complete: "
    )

    state = await ctx.storage_state()
    save_storage_state(name, state)

    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    print(f"  {GREEN}Saved: {n_cookies} cookies, {n_ls} localStorage entries{RESET}")

    await browser.close()
    await pw.stop()
    return True


# ── Main flow ──────────────────────────────────────────────────────

async def run_check(names: list[str], do_fix: bool, fix_all: bool) -> int:
    results = []

    # Phase 1: Local analysis
    print(f"\n{BOLD}{'Platform':<16} {'Session':>8} {'Cookies':>20} {'localStorage':>13} {'Status':>10}{RESET}")
    print("─" * 72)

    for name in names:
        info = analyze_session(name)
        results.append(info)

        session_str = f"{GREEN}YES{RESET}" if info["has_session"] else f"{RED}NO{RESET}"
        cookie_str = (
            f"{GREEN}{info['valid_cookies']}{RESET}/"
            f"{YELLOW}{info['session_cookies']}{RESET}/"
            f"{RED}{info['expired_cookies']}{RESET}"
            if info["has_session"]
            else "—"
        )
        ls_str = str(info["ls_entries"]) if info["has_session"] else "—"
        print(f"  {info['label']:<14} {session_str:>18}  {cookie_str:>20}  {ls_str:>12}  {'':>10}")

    print()

    # Phase 2: Online check
    print(f"{BOLD}Checking login status (headless browser)...{RESET}\n")

    for info in results:
        name = info["name"]
        if not info["has_session"]:
            info["online"] = False
            print(f"  {info['label']}: {RED}NO SESSION — skipped{RESET}")
            continue

        info["online"] = await check_online(name)
        status = f"{GREEN}ONLINE{RESET}" if info["online"] else f"{RED}OFFLINE{RESET}"
        print(f"  {info['label']}: {status}")

    await close_browser()

    # Phase 3: Summary
    print(f"\n{BOLD}Summary{RESET}")
    print("─" * 50)

    need_fix = []
    for info in results:
        label = info["label"]
        if not info["has_session"]:
            status = f"{RED}NO SESSION{RESET}"
            need_fix.append(info["name"])
        elif not info["online"]:
            status = f"{RED}SESSION INVALID{RESET}"
            need_fix.append(info["name"])
        elif info["expired_cookies"] > 0:
            status = f"{YELLOW}DEGRADED ({info['expired_cookies']} expired){RESET}"
            if fix_all:
                need_fix.append(info["name"])
        else:
            status = f"{GREEN}OK{RESET}"
            if fix_all:
                need_fix.append(info["name"])
        print(f"  {label}: {status}")

    # Phase 4: Fix if requested
    if do_fix and need_fix:
        print(f"\n{BOLD}Platforms to re-login: "
              f"{', '.join(PLATFORMS[n]['label'] for n in need_fix)}{RESET}")

        for name in need_fix:
            cfg = PLATFORMS[name]
            print(f"\n{CYAN}═══ {cfg['label']} ═══{RESET}")
            ok = await interactive_relogin(name)
            if ok:
                # Verify new session
                online = await check_online(name)
                await close_browser()
                verdict = f"{GREEN}VERIFIED{RESET}" if online else f"{YELLOW}saved but unverified{RESET}"
                print(f"  {cfg['label']}: {verdict}")
            else:
                print(f"  {cfg['label']}: {RED}re-login failed{RESET}")
    elif do_fix and not need_fix:
        print(f"\n  {GREEN}All sessions are valid, nothing to fix.{RESET}")
    elif need_fix and not do_fix:
        print(f"\n  {YELLOW}Tip: run with --fix to re-login invalid sessions{RESET}")

    print()
    return 1 if any(not info["online"] for info in results if info["has_session"]) else 0


def main():
    parser = argparse.ArgumentParser(
        description="Check browser session health and optionally re-login"
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Launch interactive re-login for invalid sessions",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="With --fix, re-login ALL platforms (even valid ones)",
    )
    parser.add_argument(
        "--only", nargs="+", choices=list(PLATFORMS.keys()),
        help="Only check specific platform(s)",
    )
    args = parser.parse_args()

    names = args.only or list(PLATFORMS.keys())
    exit_code = asyncio.run(run_check(names, args.fix, args.all))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
