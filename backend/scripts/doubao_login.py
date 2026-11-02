#!/usr/bin/env python3
"""Doubao (豆包) session management — saves full storage_state (cookies + localStorage).

Mode 1 (local, has GUI):
    python backend/scripts/doubao_login.py
    → launches headed browser, manual login, auto-saves full state

Mode 2 (server, no GUI — import token):
    python backend/scripts/doubao_login.py --token 'eyJhbGci...'
    → saves the token into localStorage + cookies for headless use

Mode 3 (server, no GUI — import full state JSON):
    python backend/scripts/doubao_login.py --import state.json
    → imports a previously exported storage_state file

Mode 4 (export from browser DevTools):
    1. Open www.doubao.com, log in
    2. DevTools → Console:
       JSON.stringify({
         cookies: document.cookie.split('; ').map(c => {
           const [name,...v] = c.split('=');
           return {name, value:v.join('='), domain:'.doubao.com', path:'/'};
         }),
         localStorage: Object.entries(localStorage).map(([k,v]) => ({name:k, value:v}))
       })
    3. Copy the output, save as state.json, then:
       python backend/scripts/doubao_login.py --import state.json
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browser_engine.session_store import (
    save_storage_state,
    load_storage_state,
    clear_session,
)

ORIGIN = "https://www.doubao.com"


def import_state(path: str):
    """Import full state from a JSON file."""
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        # Format A: Playwright storage_state {"cookies": [...], "origins": [...]}
        if "cookies" in data and "origins" in data:
            save_storage_state("doubao", data)
            n_cookies = len(data.get("cookies", []))
            n_ls = sum(len(o.get("localStorage", [])) for o in data.get("origins", []))
            print(f"Imported full state: {n_cookies} cookies, {n_ls} localStorage entries")
            return

        # Format B: DevTools export {"cookies": [...], "localStorage": [...]}
        if "cookies" in data or "localStorage" in data:
            cookies = data.get("cookies", [])
            ls_items = data.get("localStorage", [])
            normalized_cookies = []
            for c in cookies:
                entry = {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ".doubao.com"),
                    "path": c.get("path", "/"),
                }
                for field in ("expirationDate", "expires", "httpOnly", "secure", "sameSite"):
                    if c.get(field) is not None:
                        key = "expires" if field == "expirationDate" else field
                        entry[key] = c[field]
                normalized_cookies.append(entry)

            state = {
                "cookies": normalized_cookies,
                "origins": [
                    {
                        "origin": ORIGIN,
                        "localStorage": ls_items,
                    }
                ]
                if ls_items
                else [],
            }
            save_storage_state("doubao", state)
            print(
                f"Imported: {len(normalized_cookies)} cookies, {len(ls_items)} localStorage entries"
            )
            return

    # Format C: plain cookie list
    if isinstance(data, list):
        normalized = []
        for c in data:
            normalized.append(
                {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ".doubao.com"),
                    "path": c.get("path", "/"),
                }
            )
        save_storage_state("doubao", {"cookies": normalized, "origins": []})
        print(f"Imported {len(normalized)} cookies (no localStorage)")
        return

    print("Error: unrecognized format.")
    sys.exit(1)


def import_token(token: str):
    """Import a session/auth token into cookies + localStorage for Doubao."""
    ls_items = [
        {"name": "session_token", "value": token},
        {"name": "auth_token", "value": token},
    ]

    cookies = [
        {
            "name": "sessionid",
            "value": token,
            "domain": ".doubao.com",
            "path": "/",
        },
        {
            "name": "sid_guard",
            "value": token,
            "domain": ".doubao.com",
            "path": "/",
        },
    ]

    existing = load_storage_state("doubao") or {"cookies": [], "origins": []}
    existing["cookies"] = _merge_by_name(existing.get("cookies", []), cookies)

    existing_origins = existing.get("origins", [])
    origin_entry = None
    for o in existing_origins:
        if o.get("origin") == ORIGIN:
            origin_entry = o
            break
    if origin_entry is None:
        origin_entry = {"origin": ORIGIN, "localStorage": []}
        existing_origins.append(origin_entry)
    origin_entry["localStorage"] = _merge_by_name(
        origin_entry.get("localStorage", []), ls_items
    )
    existing["origins"] = existing_origins

    save_storage_state("doubao", existing)
    print(
        f"Token saved to localStorage ({len(ls_items)} keys) + cookies ({len(cookies)} entries)"
    )
    print("Run --status to verify, then test with the entity/competitive-intel endpoint.")


def _merge_by_name(existing: list, new: list) -> list:
    """Merge entries by 'name' field, new values override existing."""
    merged = {item.get("name"): item for item in existing}
    for item in new:
        merged[item.get("name")] = item
    return list(merged.values())


def show_status():
    """Show current Doubao session status."""
    state = load_storage_state("doubao")
    if not state:
        print("Doubao session: no saved state")
        return

    cookies = state.get("cookies", [])
    origins = state.get("origins", [])
    print("Doubao session:")
    print(f"  Cookies: {len(cookies)}")
    for c in cookies:
        print(f"    {c.get('name')}: {str(c.get('value', ''))[:50]}...")

    for o in origins:
        ls = o.get("localStorage", [])
        print(f"  localStorage ({o.get('origin', '?')}): {len(ls)} entries")
        for item in ls:
            val = str(item.get("value", ""))
            print(
                f"    {item.get('name')}: {val[:60]}{'...' if len(val) > 60 else ''}"
            )

    all_names = {c.get("name", "") for c in cookies}
    ls_names = set()
    for o in origins:
        for item in o.get("localStorage", []):
            ls_names.add(item.get("name", ""))
    auth_indicators = {
        "token",
        "session_token",
        "auth_token",
        "session",
        "sessionid",
        "sid_guard",
        "passport_csrf_token",
        "sid_tt",
    }
    found = (all_names | ls_names) & auth_indicators
    print(f"  Auth indicators: {', '.join(found) if found else 'none found'}")


async def interactive_login():
    """Launch headed browser for manual login (requires GUI).
    Saves full storage_state including localStorage.

    After login, sends a test message to trigger any CAPTCHA.
    If CAPTCHA appears, waits for manual completion before saving.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )
        sys.exit(1)

    print("Launching browser for Doubao login...")
    print("Log in manually, then press Enter here to save session.\n")

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
        print("Opening https://www.doubao.com/chat/ ...")
        await page.goto("https://www.doubao.com/chat/", timeout=30000)
        print("Page loaded. Please log in in the browser window.")
    except Exception as e:
        print(f"Warning: page load issue ({e}), browser should still be open.")

    # Wait for user to complete login
    await asyncio.get_event_loop().run_in_executor(
        None, input, "\n>>> Press Enter after login is complete: "
    )

    # Send a test message to trigger CAPTCHA
    print("\nSending test message to check for CAPTCHA...")
    try:
        textarea = page.locator(
            "textarea.semi-input-textarea, "
            "textarea[placeholder='发消息...'], "
            "textarea, "
            "[contenteditable='true']"
        ).first
        await textarea.click()
        await asyncio.sleep(0.3)
        await textarea.type("你好", delay=80)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await asyncio.sleep(3)

        # Check if CAPTCHA appeared
        has_captcha = await _check_captcha(page)
        if has_captcha:
            print("\n*** CAPTCHA detected! ***")
            print("Please complete the CAPTCHA verification in the browser window.")
            print("(Select matching images and drag them to the target area)")
            await asyncio.get_event_loop().run_in_executor(
                None, input, "\n>>> Press Enter after CAPTCHA is completed: "
            )
            await asyncio.sleep(2)

            # Verify CAPTCHA is gone
            still_captcha = await _check_captcha(page)
            if still_captcha:
                print("Warning: CAPTCHA may still be present. Continuing anyway...")
            else:
                print("CAPTCHA cleared successfully!")
    except Exception as e:
        print(f"Test message step skipped: {e}")

    # Save full storage_state (cookies + localStorage)
    state = await ctx.storage_state()
    save_storage_state("doubao", state)

    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    print(f"\nSaved full state: {n_cookies} cookies, {n_ls} localStorage entries")
    print("Session saved. You can now run headless Doubao queries.")

    await browser.close()
    await pw.stop()


async def _check_captcha(page) -> bool:
    """Check if ByteDance CAPTCHA is present."""
    try:
        return await page.evaluate("""() => {
            const el = document.getElementById('captcha_container');
            if (el) {
                const style = getComputedStyle(el);
                if (style.display !== 'none' && el.innerHTML.length > 0) return true;
            }
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
                const src = iframe.src || '';
                if (src.includes('captcha') || src.includes('verifycenter') || src.includes('verify.zijieapi.com')) {
                    return true;
                }
            }
            return false;
        }""")
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Doubao session management")
    parser.add_argument(
        "--import",
        dest="import_file",
        metavar="FILE",
        help="Import state from a JSON file (cookies + localStorage)",
    )
    parser.add_argument(
        "--token", metavar="TOKEN", help="Import a session/auth token directly"
    )
    parser.add_argument(
        "--status", action="store_true", help="Show current session status"
    )
    parser.add_argument(
        "--clear", action="store_true", help="Clear saved session"
    )
    args = parser.parse_args()

    if args.clear:
        clear_session("doubao")
        print("Session cleared.")
    elif args.status:
        show_status()
    elif args.import_file:
        import_state(args.import_file)
    elif args.token:
        import_token(args.token)
    else:
        asyncio.run(interactive_login())


if __name__ == "__main__":
    main()
