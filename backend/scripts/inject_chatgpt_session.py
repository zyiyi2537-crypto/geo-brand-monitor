#!/usr/bin/env python3
"""Inject a chatgpt.com session-token cookie copied from a daily browser.

Why this exists:
  ChatGPT login via Playwright is blocked by Google SSO's anti-fraud
  whenever an account is "Continue with Google" only (no OpenAI password).
  Google rejects freshly-spawned Linux/Playwright browsers.

  But OpenAI's __Secure-next-auth.session-token is a JWT that is NOT
  bound to device fingerprint or IP. So we sidestep OAuth entirely:
  copy the cookie from a daily Chrome session that's already logged in,
  inject it into Playwright's persistent profile, and let Playwright
  separately negotiate Cloudflare with the Linux disguise stack.

How to get the token value:
  1. Open chatgpt.com in your daily Chrome (must be logged in).
  2. F12 → Application → Cookies → https://chatgpt.com
  3. Find __Secure-next-auth.session-token (or .0/.1 chunks).
  4. Save Value field(s) to file(s) — see Usage below.

Usage:
  # Single cookie (no .0/.1 suffix):
  pbpaste > /tmp/chatgpt_token.txt
  venv/bin/python backend/scripts/inject_chatgpt_session.py /tmp/chatgpt_token.txt

  # Chunked cookies (.0 + .1):
  # 1. In daily Chrome DevTools, double-click the .0 Value cell, Ctrl+A,
  #    Ctrl+C, then on Mac:  pbpaste > /tmp/c0.txt
  # 2. Same for .1:  pbpaste > /tmp/c1.txt
  # 3. Run with the files in chunk order:
  venv/bin/python backend/scripts/inject_chatgpt_session.py /tmp/c0.txt /tmp/c1.txt
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from browser_engine.session_store import (
    save_storage_state,
    save_engine_profile,
)

ENGINE = "chatgpt"
ORIGIN = "https://chatgpt.com"


def read_token_chunks() -> dict[str, str]:
    """Read session-token value(s) from file paths in argv.

    sys.argv[1:] is a list of file paths in chunk order:
      - 1 file  → single cookie, no suffix
                 (cookie name: __Secure-next-auth.session-token)
      - 2+ files → chunked cookies
                 (cookie name: __Secure-next-auth.session-token.{0,1,...})

    File-based input avoids terminal paste corruption / truncation that
    happens with input() on multi-thousand-character JWT chunks.
    """
    paths = sys.argv[1:]
    if not paths:
        print("ERROR: no token file path given.")
        print()
        print("Usage:")
        print("  Single cookie (no suffix):")
        print("    pbpaste > /tmp/token.txt")
        print(f"    {sys.argv[0]} /tmp/token.txt")
        print()
        print("  Chunked cookies (.0 + .1):")
        print("    # paste .0 value into clipboard, then:")
        print("    pbpaste > /tmp/c0.txt")
        print("    # paste .1 value, then:")
        print("    pbpaste > /tmp/c1.txt")
        print(f"    {sys.argv[0]} /tmp/c0.txt /tmp/c1.txt")
        sys.exit(1)

    chunks: dict[str, str] = {}
    for i, p in enumerate(paths):
        if not os.path.isfile(p):
            print(f"ERROR: not a file: {p}")
            sys.exit(1)
        with open(p, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if not v:
            print(f"ERROR: file is empty: {p}")
            sys.exit(1)
        # Single file → no suffix; multiple files → .0, .1, ...
        key = "" if len(paths) == 1 else str(i)
        chunks[key] = v

    return chunks


async def main() -> int:
    chunks = read_token_chunks()
    print()
    print(f"Got {len(chunks)} chunk(s):")
    for k, v in chunks.items():
        suffix = f".{k}" if k else ""
        print(f"  __Secure-next-auth.session-token{suffix}  ({len(v)} chars)")
    print()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed.")
        return 1

    from pathlib import Path
    from browser_engine.anti_detect import (
        _pick_profile,
        get_launch_options,
        get_context_options_international,
        build_stealth_js_for_profile,
    )

    profile = _pick_profile(platform_filter="Linux x86_64")
    user_data_dir = Path(os.environ.get(
        "BROWSER_PROFILE_DIR",
        os.path.join(os.path.dirname(__file__), "..", "data", "browser_profiles"),
    )) / ENGINE
    user_data_dir.mkdir(parents=True, exist_ok=True)

    print(f"user_data_dir: {user_data_dir}")
    print(f"profile:       {profile['platform']} ({profile['ua'][:60]}...)")
    print()

    pw = await async_playwright().start()

    ctx = None
    used_channel = None
    for ch in ("chrome", None):
        try:
            launch_opts = get_launch_options(headless=False, profile=profile, channel=ch)
            ctx_opts = get_context_options_international(profile=profile)
            ctx_opts.update({k: v for k, v in launch_opts.items() if k not in ctx_opts})
            ctx = await pw.chromium.launch_persistent_context(
                str(user_data_dir), **ctx_opts,
            )
            used_channel = ch or "bundled-chromium"
            break
        except Exception as e:
            print(f"  channel={ch!r} failed: {type(e).__name__}: {e}")
    if ctx is None:
        print("FAIL: could not launch browser")
        await pw.stop()
        return 1
    print(f"Launched via: {used_channel}")
    print()

    await ctx.add_init_script(
        build_stealth_js_for_profile(profile, international=True)
    )

    # Step 1: pass Cloudflare and let chatgpt.com set its own infrastructure
    # cookies (cf_clearance, __cf_bm, oai-did, etc.) BEFORE we inject the
    # session-token. If we inject too early, chatgpt's first goto will see
    # an inconsistent state (token without supporting infra cookies) and
    # bounce to /api/auth/error.
    page = await ctx.new_page()
    print("[1/3] Loading chatgpt.com to negotiate Cloudflare and set infra cookies...")
    try:
        await page.goto(ORIGIN + "/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        print(f"  goto warning: {type(e).__name__}: {e}")

    cookies_now = await ctx.cookies(ORIGIN)
    cookie_names = {c["name"] for c in cookies_now}
    has_cf = "cf_clearance" in cookie_names
    print(f"  cookies after first load: {len(cookie_names)}")
    print(f"  cf_clearance: {'YES' if has_cf else 'NO'}")
    if not has_cf:
        print("  WARN: no cf_clearance — CF challenge not passed; injection")
        print("        may still work but server reuse will be unreliable.")
    print()

    # Step 2: inject the session-token cookie(s).
    # NextAuth chunks the JWT into __Secure-next-auth.session-token.{0,1,...}
    # when the encoded value exceeds the 4KB single-cookie limit. We must
    # inject ALL chunks; a partial JWT is unparseable server-side.
    print(f"[2/3] Injecting {len(chunks)} session-token cookie(s)...")
    expires_at = int(time.time()) + 30 * 24 * 3600
    cookies_to_add = []
    for k, v in chunks.items():
        name = (
            "__Secure-next-auth.session-token"
            if k == ""
            else f"__Secure-next-auth.session-token.{k}"
        )
        cookies_to_add.append({
            "name": name,
            "value": v,
            "domain": ".chatgpt.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
            "expires": expires_at,
        })
        print(f"  {name}  ({len(v)} chars)")
    await ctx.add_cookies(cookies_to_add)
    print()

    # Step 3: reload chatgpt.com — should now show logged-in UI
    print("[3/3] Reloading chatgpt.com to verify session...")
    try:
        await page.goto(ORIGIN + "/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
    except Exception as e:
        print(f"  goto warning: {type(e).__name__}: {e}")

    final_url = page.url
    title = await page.title()
    print(f"  final URL: {final_url}")
    print(f"  title:     {title}")

    # Detect login state
    is_error_page = "/api/auth/error" in final_url
    is_login_redirect = (
        "auth.openai.com" in final_url
        or "/auth/login" in final_url
    )
    has_prompt_input = await page.locator(
        "#prompt-textarea, [data-testid='prompt-textarea'], "
        "[contenteditable='true']"
    ).count() > 0

    print(f"  prompt input visible: {has_prompt_input}")
    print()

    cookies_final = await ctx.cookies(ORIGIN)
    cookie_names_final = {c["name"] for c in cookies_final}
    has_cf_final = "cf_clearance" in cookie_names_final
    session_chunks_final = sorted(
        n for n in cookie_names_final
        if n == "__Secure-next-auth.session-token"
        or n.startswith("__Secure-next-auth.session-token.")
    )
    has_session_final = bool(session_chunks_final)

    print("=" * 60)
    print(f"cf_clearance:                       {'YES' if has_cf_final else 'NO'}")
    print(f"session-token (chunks present):     {session_chunks_final or 'NONE'}")
    print(f"On login error page:                {is_error_page}")
    print(f"Redirected to login:                {is_login_redirect}")
    print(f"Logged-in UI visible:               {has_prompt_input}")
    print("=" * 60)

    if is_error_page:
        print()
        print("FAIL: still landing on /api/auth/error.")
        print("Possible causes:")
        print("  1. Token was copied wrong (re-check the Value field)")
        print("  2. Token already expired or revoked (login again in daily Chrome)")
        print("  3. Token is from a different chatgpt account variant (.com vs .com/g/...)")
        await asyncio.get_event_loop().run_in_executor(
            None, input, "\n>>> Browser left open for inspection. Enter to close: "
        )
        await ctx.close()
        await pw.stop()
        return 2

    if not has_prompt_input:
        print()
        print("WARN: prompt input not detected. Might be a transient render delay.")
        print("Browser left open for manual confirmation.")
        await asyncio.get_event_loop().run_in_executor(
            None, input, "\n>>> Confirm visually, then Enter to save and close: "
        )

    # Save storage_state + profile for upload to AWS
    state = await ctx.storage_state()
    save_storage_state(ENGINE, state)
    save_engine_profile(ENGINE, profile)

    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    print()
    print(f"Saved storage_state: {n_cookies} cookies, {n_ls} localStorage entries")
    print(f"Saved profile:       {ENGINE}_profile.json (platform={profile['platform']})")
    print()
    print("Next steps:")
    print(f"  1. Verify locally: grep prompt-textarea in chatgpt_browser.py path")
    print(f"  2. Upload to AWS:  bash backend/scripts/upload_{ENGINE}_session.sh")

    await ctx.close()
    await pw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
