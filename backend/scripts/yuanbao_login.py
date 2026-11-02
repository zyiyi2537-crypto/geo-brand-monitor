#!/usr/bin/env python3
"""Yuanbao (腾讯元宝) session management — saves full storage_state.

Mode 1 (local, has GUI):
    python backend/scripts/yuanbao_login.py
    → launches headed browser, manual login, auto-saves full state

Mode 2 (server, no GUI — import full state JSON):
    python backend/scripts/yuanbao_login.py --import state.json
    → imports a previously exported storage_state file

Mode 3 (export from browser DevTools):
    1. Open yuanbao.tencent.com, log in
    2. DevTools → Console:
       JSON.stringify({
         cookies: document.cookie.split('; ').map(c => {
           const [name,...v] = c.split('=');
           return {name, value:v.join('='), domain:'.tencent.com', path:'/'};
         }),
         localStorage: Object.entries(localStorage).map(([k,v]) => ({name:k, value:v}))
       })
    3. Copy the output, save as state.json, then:
       python backend/scripts/yuanbao_login.py --import state.json
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

ORIGIN = "https://yuanbao.tencent.com"


def import_state(path: str):
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "cookies" in data and "origins" in data:
            save_storage_state("yuanbao", data)
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
                    "domain": c.get("domain", ".tencent.com"),
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
                    "localStorage": [
                        {"name": item.get("name", ""), "value": item.get("value", "")}
                        for item in ls_items
                    ],
                }],
            }
            save_storage_state("yuanbao", state)
            print(f"Imported DevTools format: {len(normalized_cookies)} cookies, {len(ls_items)} localStorage entries")
            return

    print(f"Unrecognized format in {path}")
    sys.exit(1)


async def interactive_login():
    from playwright.async_api import async_playwright
    from browser_engine.anti_detect import get_launch_options, get_context_options

    pw = await async_playwright().start()
    opts = get_launch_options(headless=False)
    browser = await pw.chromium.launch(**opts)

    ctx_opts = get_context_options()
    existing = load_storage_state("yuanbao")
    if existing:
        ctx_opts["storage_state"] = existing

    context = await browser.new_context(**ctx_opts)
    page = await context.new_page()

    await page.goto(ORIGIN, wait_until="domcontentloaded")
    print(f"\nOpened {ORIGIN}")
    print("Log in manually, then press Enter here to save session...")
    await asyncio.get_event_loop().run_in_executor(None, input)

    state = await context.storage_state()
    save_storage_state("yuanbao", state)
    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    print(f"Session saved: {n_cookies} cookies, {n_ls} localStorage entries")

    await context.close()
    await browser.close()
    await pw.stop()


def main():
    parser = argparse.ArgumentParser(description="Yuanbao session manager")
    parser.add_argument("--import", dest="import_file", help="Import state from JSON file")
    parser.add_argument("--clear", action="store_true", help="Clear saved session")
    parser.add_argument("--show", action="store_true", help="Show current session info")
    args = parser.parse_args()

    if args.clear:
        clear_session("yuanbao")
        print("Session cleared")
        return

    if args.show:
        state = load_storage_state("yuanbao")
        if state:
            n_cookies = len(state.get("cookies", []))
            n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
            print(f"Session exists: {n_cookies} cookies, {n_ls} localStorage entries")
        else:
            print("No session found")
        return

    if args.import_file:
        import_state(args.import_file)
        return

    asyncio.run(interactive_login())


if __name__ == "__main__":
    main()
