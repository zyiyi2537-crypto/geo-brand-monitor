#!/usr/bin/env python3
"""Grok session management — saves full storage_state (cookies + localStorage).

Mode 1 (local, has GUI):
    python backend/scripts/grok_login.py
    → launches headed browser, manual login via X/Twitter account, auto-saves full state

Mode 2 (server, no GUI — import full state JSON):
    python backend/scripts/grok_login.py --import state.json
    → imports a previously exported storage_state file

Mode 3 (export from browser DevTools):
    1. Open grok.com, log in with X/Twitter account
    2. DevTools → Application → Storage → Copy cookies + localStorage
    3. Save as state.json, then:
       python backend/scripts/grok_login.py --import state.json
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browser_engine.session_store import (
    save_storage_state, load_storage_state, clear_session,
    save_engine_profile,
)

ENGINE = "grok"
ORIGIN = "https://grok.com"
CHAT_URL = "https://grok.com/"


def import_state(path: str):
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "cookies" in data and "origins" in data:
            save_storage_state(ENGINE, data)
            n_cookies = len(data.get("cookies", []))
            n_ls = sum(len(o.get("localStorage", [])) for o in data.get("origins", []))
            print(f"Imported full state: {n_cookies} cookies, {n_ls} localStorage entries")
            return

        if "cookies" in data or "localStorage" in data:
            cookies = data.get("cookies", [])
            ls_items = data.get("localStorage", [])
            normalized_cookies = []
            for c in cookies:
                entry = {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ".grok.com"),
                    "path": c.get("path", "/"),
                }
                for field in ("expirationDate", "expires", "httpOnly", "secure", "sameSite"):
                    if c.get(field) is not None:
                        key = "expires" if field == "expirationDate" else field
                        entry[key] = c[field]
                normalized_cookies.append(entry)

            state = {
                "cookies": normalized_cookies,
                "origins": [{
                    "origin": ORIGIN,
                    "localStorage": ls_items,
                }] if ls_items else [],
            }
            save_storage_state(ENGINE, state)
            print(f"Imported: {len(normalized_cookies)} cookies, {len(ls_items)} localStorage entries")
            return

    print("Error: unrecognized format. Expected Playwright storage_state or DevTools export.")
    sys.exit(1)


def show_status():
    state = load_storage_state(ENGINE)
    if not state:
        print(f"{ENGINE} session: no saved state")
        return

    cookies = state.get("cookies", [])
    origins = state.get("origins", [])
    print(f"{ENGINE} session:")
    print(f"  Cookies: {len(cookies)}")
    for c in cookies:
        print(f"    {c.get('name')}: {str(c.get('value', ''))[:50]}...")

    for o in origins:
        ls = o.get("localStorage", [])
        print(f"  localStorage ({o.get('origin', '?')}): {len(ls)} entries")
        for item in ls:
            val = str(item.get("value", ""))
            print(f"    {item.get('name')}: {val[:60]}{'...' if len(val) > 60 else ''}")

    all_names = {c.get("name", "") for c in cookies}
    # X/Twitter SSO cookies + Grok-specific auth
    auth_indicators = {"auth_token", "ct0", "twid", "sessionid",
                       "grok_session", "sso_token", "bearer_token"}
    found = all_names & auth_indicators
    print(f"  Auth indicators: {', '.join(found) if found else 'none found'}")


async def interactive_login():
    """Headed login with Linux profile for cross-machine CF session reuse.

    Forces a Linux fingerprint so the cf_clearance cookie issued here
    stays valid on the AWS Linux server. Uses channel="chrome" when
    available for Sec-CH-UA brand consistency.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    from browser_engine.anti_detect import (
        _pick_profile,
        get_launch_options,
        get_context_options_international,
        build_stealth_js_for_profile,
    )

    profile = _pick_profile(platform_filter="Linux x86_64")
    print(f"Launching browser for {ENGINE} login...")
    print(f"Cross-machine profile: UA={profile['ua'][:80]}...")
    print(f"  Sec-CH-UA-Platform will be: {profile.get('ua_platform_label', 'Linux')}")
    print("Note: this browser will identify as Linux even on macOS/Windows.")
    print("This is intentional — the same profile must work on the AWS server.\n")
    print("Log in with your X/Twitter account, then press Enter here to save session.\n")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(
            **get_launch_options(headless=False, profile=profile, channel="chrome")
        )
    except Exception as e:
        print(f"WARNING: channel=chrome failed ({e})")
        print("Falling back to bundled Chromium. CF may reject this browser.")
        print("Recommended: install Chrome via 'playwright install chrome'\n")
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

    try:
        print(f"Opening {CHAT_URL} ...")
        await page.goto(CHAT_URL, timeout=30000, wait_until="domcontentloaded")
        print("Page loaded. Please log in in the browser window.")
        print("Tip: X SSO sometimes asks for ARKoseLabs FunCaptcha — solve it manually.")
    except Exception as e:
        print(f"Warning: page load issue ({e}), browser should still be open.")

    await asyncio.get_event_loop().run_in_executor(
        None, input, "\n>>> Press Enter after login is complete: "
    )

    state = await ctx.storage_state()
    save_storage_state(ENGINE, state)
    save_engine_profile(ENGINE, profile)

    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    cookie_names = {c.get("name", "") for c in state.get("cookies", [])}
    has_cf = "cf_clearance" in cookie_names
    auth_indicators = {"auth_token", "ct0", "twid", "sso_token"}
    found = cookie_names & auth_indicators
    print(f"\nSaved full state: {n_cookies} cookies, {n_ls} localStorage entries")
    print(f"Saved profile:    {ENGINE}_profile.json (platform={profile['platform']})")
    print(f"  cf_clearance cookie:       {'YES' if has_cf else 'NO  ← Cloudflare did NOT pass'}")
    print(f"  X/Twitter auth cookies:    {', '.join(sorted(found)) if found else 'NONE  ← login did NOT complete'}")

    if not found:
        print("\nERROR: X/Twitter login did not complete. Do NOT upload.")
        await browser.close()
        await pw.stop()
        sys.exit(1)

    print("\nSession viable. Upload with:")
    print(f"  bash backend/scripts/upload_{ENGINE}_session.sh")

    await browser.close()
    await pw.stop()


def main():
    parser = argparse.ArgumentParser(description=f"{ENGINE} session management")
    parser.add_argument("--import", dest="import_file", metavar="FILE",
                        help="Import state from a JSON file")
    parser.add_argument("--status", action="store_true",
                        help="Show current session status")
    parser.add_argument("--clear", action="store_true",
                        help="Clear saved session")
    args = parser.parse_args()

    if args.clear:
        clear_session(ENGINE)
        print("Session cleared.")
    elif args.status:
        show_status()
    elif args.import_file:
        import_state(args.import_file)
    else:
        asyncio.run(interactive_login())


if __name__ == "__main__":
    main()
