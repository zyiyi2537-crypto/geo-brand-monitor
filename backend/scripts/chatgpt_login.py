#!/usr/bin/env python3
"""ChatGPT session management — saves full storage_state (cookies + localStorage).

Mode 1 (local, has GUI):
    python backend/scripts/chatgpt_login.py
    → launches headed browser, manual login via OpenAI account, auto-saves full state

Mode 2 (server, no GUI — import full state JSON):
    python backend/scripts/chatgpt_login.py --import state.json
    → imports a previously exported storage_state file

Mode 3 (export from browser DevTools):
    1. Open chatgpt.com, log in with OpenAI account
    2. DevTools → Application → Storage → Copy cookies + localStorage
    3. Save as state.json, then:
       python backend/scripts/chatgpt_login.py --import state.json

After saving locally, upload the session to the browser-service:
    curl -X PUT http://browser-service:8091/sessions/chatgpt \\
         -H 'content-type: application/json' \\
         -d "{\\"storage_state\\": $(cat backend/data/browser_sessions/chatgpt.json)}"
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

ENGINE = "chatgpt"
ORIGIN = "https://chatgpt.com"
CHAT_URL = "https://chatgpt.com/"


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
                    "domain": c.get("domain", ".chatgpt.com"),
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
    auth_indicators = {"__Secure-next-auth.session-token", "__Host-next-auth.csrf-token",
                       "_cfuvid", "cf_clearance", "_dd_s", "oai-did",
                       "__Secure-next-auth.callback-url"}
    found = all_names & auth_indicators
    print(f"  Auth indicators: {', '.join(found) if found else 'none found'}")


async def interactive_login():
    """Headed login via persistent Chrome context (mirrors runtime path).

    Uses launch_persistent_context with the SAME user_data_dir that the
    runtime adapter uses. This matters because:

    1. OpenAI's anti-fraud flags "freshly spawned browser" (no cache,
       no history, no cookies) and bounces the OAuth flow to
       /api/auth/error. A persistent profile that has visited a few
       pages looks like a real returning user.

    2. cookies/localStorage/cache that login establishes ARE the
       same bytes the runtime will read on next start — no two-stage
       export/inject dance, no race condition between cookie
       persistence and storage_state replay.

    3. cf_clearance issued here is valid for runtime out of the box.

    Forces Linux profile so HTTP Sec-CH-UA-Platform + JS
    navigator.userAgentData both say "Linux", matching the AWS server.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    from pathlib import Path
    from browser_engine.anti_detect import (
        _pick_profile,
        get_launch_options,
        get_context_options_international,
        build_stealth_js_for_profile,
    )

    # Force Linux profile for cross-machine consistency
    profile = _pick_profile(platform_filter="Linux x86_64")

    # Same user_data_dir the runtime adapter uses — login and runtime
    # share one persistent profile.
    user_data_dir = Path(os.environ.get(
        "BROWSER_PROFILE_DIR",
        os.path.join(os.path.dirname(__file__), "..", "data", "browser_profiles"),
    )) / ENGINE
    user_data_dir.mkdir(parents=True, exist_ok=True)

    print(f"Launching browser for {ENGINE} login...")
    print(f"  user_data_dir:      {user_data_dir}")
    print(f"  Cross-machine UA:   {profile['ua'][:80]}...")
    print(f"  Sec-CH-UA-Platform: {profile.get('ua_platform_label', 'Linux')}")
    print("Browser identifies as Linux even on macOS/Windows — intentional.\n")
    print("Log in with email/password (NOT Google SSO — Google rejects")
    print("freshly-spawned browsers, even with stealth).")
    print("Then press Enter here to save the session.\n")

    pw = await async_playwright().start()

    # launch_persistent_context replaces launch + new_context.
    # All launch args + context options merge into one call.
    launch_opts = None
    used_channel = None
    for ch in ("chrome", None):
        try:
            launch_opts = get_launch_options(
                headless=False, profile=profile, channel=ch,
            )
            ctx_opts = get_context_options_international(profile=profile)
            ctx_opts.update({k: v for k, v in launch_opts.items() if k not in ctx_opts})
            ctx = await pw.chromium.launch_persistent_context(
                str(user_data_dir), **ctx_opts,
            )
            used_channel = ch or "bundled-chromium"
            break
        except Exception as e:
            print(f"  launch channel={ch!r} failed: {type(e).__name__}: {e}")
    if used_channel is None or ctx is None:
        print("FAIL: could not launch any Chrome/Chromium.")
        await pw.stop()
        sys.exit(1)
    print(f"  Launched via:       {used_channel}\n")

    await ctx.add_init_script(
        build_stealth_js_for_profile(profile, international=True)
    )

    page = await ctx.new_page()

    try:
        print(f"Opening {CHAT_URL} ...")
        await page.goto(CHAT_URL, timeout=30000, wait_until="domcontentloaded")
        print("Page loaded. In the browser window:")
        print("  1. Click 'Log in'")
        print("  2. Enter email — DO NOT click 'Continue with Google'")
        print("  3. After clicking Continue, enter your OpenAI password")
        print("  4. Once chatgpt.com main UI loads, come back here")
    except Exception as e:
        print(f"Warning: page load issue ({e}), browser should still be open.")

    await asyncio.get_event_loop().run_in_executor(
        None, input, "\n>>> Press Enter after login is complete: "
    )

    # Export storage_state for cross-machine upload (server side still
    # needs the JSON path until we ship a user_data_dir tar upload).
    state = await ctx.storage_state()
    save_storage_state(ENGINE, state)
    save_engine_profile(ENGINE, profile)

    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    cookie_names = {c.get("name", "") for c in state.get("cookies", [])}
    has_cf = "cf_clearance" in cookie_names
    has_session = any(n.startswith("__Secure-next-auth.session-token") for n in cookie_names)
    print(f"\nSaved full state: {n_cookies} cookies, {n_ls} localStorage entries")
    print(f"Saved profile:    {ENGINE}_profile.json (platform={profile['platform']})")
    print(f"  cf_clearance cookie:                    {'YES' if has_cf else 'NO  ← Cloudflare did NOT pass'}")
    print(f"  __Secure-next-auth.session-token:       {'YES' if has_session else 'NO  ← OpenAI login did NOT complete'}")

    if not (has_cf and has_session):
        print("\nERROR: session not viable for server-side use.")
        if not has_cf:
            print("  cf_clearance MISSING — Cloudflare challenge was not passed.")
        if not has_session:
            print("  session-token MISSING — OpenAI login did not complete.")
            print("  Most common cause: you used 'Continue with Google'.")
            print("  Google rejects freshly-spawned Playwright browsers.")
            print("  Use email + OpenAI password directly instead.")
        print("\nTroubleshooting:")
        print("  1. Re-run and use email/password (not Google SSO)")
        print("  2. Wait 30+ minutes if you've been retrying (CF rate-limits)")
        print("  3. Use a residential IP / VPN exit")
        print(f"  4. Inspect: ls {user_data_dir} (persistent profile dir)")
        await ctx.close()
        await pw.stop()
        sys.exit(1)

    print("\nSession viable. Upload with:")
    print(f"  bash backend/scripts/upload_{ENGINE}_session.sh")

    await ctx.close()
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
