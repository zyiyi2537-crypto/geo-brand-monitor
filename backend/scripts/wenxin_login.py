#!/usr/bin/env python3
"""Wenxin (文心一言) session management — saves full storage_state.

Mode 1 (local, has GUI):
    python backend/scripts/wenxin_login.py
    → launches headed browser, manual login (scan QR or phone code), auto-saves

Mode 2 (server, no GUI — import full state JSON):
    python backend/scripts/wenxin_login.py --import state.json

Mode 3 (export from browser DevTools):
    1. Open yiyan.baidu.com, log in
    2. DevTools → Console:
       JSON.stringify({
         cookies: document.cookie.split('; ').map(c => {
           const [name,...v] = c.split('=');
           return {name, value:v.join('='), domain:'.baidu.com', path:'/'};
         }),
         localStorage: Object.entries(localStorage).map(([k,v]) => ({name:k, value:v}))
       })
    3. Save output as state.json, then:
       python backend/scripts/wenxin_login.py --import state.json
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browser_engine.session_store import (
    save_storage_state, load_storage_state, clear_session,
)

ORIGIN = "https://yiyan.baidu.com"
DEFAULT_DOMAIN = ".baidu.com"
SESSION_KEY = "wenxin"


def import_state(path: str):
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "cookies" in data and "origins" in data:
            save_storage_state(SESSION_KEY, data)
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
                    "domain": c.get("domain", DEFAULT_DOMAIN),
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
            save_storage_state(SESSION_KEY, state)
            print(f"Imported: {len(normalized_cookies)} cookies, {len(ls_items)} localStorage entries")
            return

    if isinstance(data, list):
        normalized = []
        for c in data:
            normalized.append({
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", DEFAULT_DOMAIN),
                "path": c.get("path", "/"),
            })
        save_storage_state(SESSION_KEY, {"cookies": normalized, "origins": []})
        print(f"Imported {len(normalized)} cookies (no localStorage)")
        return

    print("Error: unrecognized format.")
    sys.exit(1)


def show_status():
    state = load_storage_state(SESSION_KEY)
    if not state:
        print("Wenxin session: no saved state")
        return

    cookies = state.get("cookies", [])
    origins = state.get("origins", [])
    print(f"Wenxin session:")
    print(f"  Cookies: {len(cookies)}")
    for c in cookies:
        print(f"    {c.get('name')}: {str(c.get('value', ''))[:50]}...")

    for o in origins:
        ls = o.get("localStorage", [])
        print(f"  localStorage ({o.get('origin', '?')}): {len(ls)} entries")
        for item in ls:
            val = str(item.get("value", ""))
            print(f"    {item.get('name')}: {val[:60]}{'...' if len(val) > 60 else ''}")

    # Baidu auth cookies
    all_names = {c.get("name", "") for c in cookies}
    auth_indicators = {"BDUSS", "PTOKEN", "STOKEN", "SESSIONID", "BAIDUID"}
    found = all_names & auth_indicators
    print(f"  Auth indicators: {', '.join(found) if found else 'none found (BDUSS/PTOKEN expected)'}")


async def interactive_login():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    print("Launching browser for Wenxin (文心一言) login...")
    print("Log in manually (scan QR or phone code), then press Enter here to save session.\n")

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
        print(f"Opening {ORIGIN}/ ...")
        await page.goto(f"{ORIGIN}/", timeout=30000)
        print("Page loaded. Please log in in the browser window.")
    except Exception as e:
        print(f"Warning: page load issue ({e}), browser should still be open.")

    await asyncio.get_event_loop().run_in_executor(
        None, input, "\n>>> Press Enter after login is complete: "
    )

    state = await ctx.storage_state()
    save_storage_state(SESSION_KEY, state)

    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    print(f"\nSaved full state: {n_cookies} cookies, {n_ls} localStorage entries")

    await browser.close()
    await pw.stop()


def main():
    parser = argparse.ArgumentParser(description="Wenxin (文心一言) session management")
    parser.add_argument("--import", dest="import_file", metavar="FILE",
                        help="Import state from a JSON file (cookies + localStorage)")
    parser.add_argument("--status", action="store_true",
                        help="Show current session status")
    parser.add_argument("--clear", action="store_true",
                        help="Clear saved session")
    args = parser.parse_args()

    if args.clear:
        clear_session(SESSION_KEY)
        print("Session cleared.")
    elif args.status:
        show_status()
    elif args.import_file:
        import_state(args.import_file)
    else:
        asyncio.run(interactive_login())


if __name__ == "__main__":
    main()
