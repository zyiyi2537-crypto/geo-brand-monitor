#!/usr/bin/env python3
"""Manual interactive login for browser-service engines.

Run on vm03 to launch a headed Chrome via browser-service's own anti-detect
stack (channel=chrome for Doubao, full stealth profile, persistent context),
let the operator log in + solve CAPTCHA via VNC, then save the session.

The session is saved to /opt/browser-service/data/browser_sessions/<engine>.json
— the same path browser-service reads at startup, so the next /search call
will pick it up.

Usage (on vm03, with Xvfb already running on :99):
    cd /opt/browser-service
    DISPLAY=:99 venv/bin/python manual_login.py doubao

Steps:
    1. VNC into vm03:5900 (after running setup_vnc.sh)
    2. Run this script in an SSH terminal
    3. In the VNC window: log in, send a test query, drag images to solve CAPTCHA
    4. Wait until you see a clean AI response (no CAPTCHA visible)
    5. Press Enter in the SSH terminal — session is saved
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.browser import create_headed_page, save_page_session
from app.anti_detect import _pick_profile

# Per-engine config: chat URL, fingerprint platform pin, channel
_ENGINE_CFG = {
    "doubao":   ("https://www.doubao.com/chat/", "Linux x86_64", "chrome"),
    "qwen":     ("https://www.qianwen.com/",      None,           None),
    "deepseek": ("https://chat.deepseek.com/",    None,           None),
    "wenxin":   ("https://yiyan.baidu.com/",      None,           None),
    "yuanbao":  ("https://yuanbao.tencent.com/",  None,           None),
}


async def main():
    parser = argparse.ArgumentParser(description="保存一个平台的浏览器登录态")
    parser.add_argument("engine", choices=tuple(_ENGINE_CFG))
    parser.add_argument("--account", default="default", help="账号编号，例如 acct-001")
    args = parser.parse_args()
    engine = args.engine
    account_id = args.account
    if account_id != "default":
        from app.session_store import _account_id
        account_id = _account_id(account_id)
    # Every login window starts with a clean browser context so a new account
    # can never inherit cookies from another saved account.
    os.environ["BROWSER_LOGIN_SKIP_SESSION"] = "1"
    url, platform, channel = _ENGINE_CFG[engine]

    profile = _pick_profile(platform_filter=platform) if platform else _pick_profile()
    print(f"[{engine}] launching headed Chrome")
    print(f"  channel: {channel or 'bundled chromium'}")
    print(f"  UA:      {profile['ua']}")
    print(f"  platform:{profile['platform']}")
    print(f"  DISPLAY: {os.environ.get('DISPLAY', '(unset)')}")

    page, ctx = await create_headed_page(
        engine,
        profile=profile,
        channel=channel,
    )
    headed_browser = getattr(page, "_headed_browser", None)
    headed_pw = getattr(page, "_pw_ref", None)

    # Shrink viewport so the page layout reflows into the small Xvfb screen
    # (默认 ctx 是 1920x1080,但 VNC 投到 Mac 上时 Xvfb 通常缩到 1280x720,
    # 1080 高的 viewport 输入框被裁在屏外,manual_login 没法 submit).
    # 优先读 MANUAL_LOGIN_VIEWPORT="W,H"。
    # 默认 1280x600 — 因为 Playwright 的 viewport 是 PAGE viewport,
    # 浏览器实际窗口 = page + ~95px (tab + URL bar),所以 720 page 会让
    # 整个窗口 815 高,在 1280x720 Xvfb 下底部 95px 出屏。1280x600 留够空间。
    import os as _os
    vp_raw = _os.environ.get("MANUAL_LOGIN_VIEWPORT", "1280,600").strip()
    try:
        vw, vh = (int(x) for x in vp_raw.split(","))
    except ValueError:
        vw, vh = 1280, 720
    try:
        await page.set_viewport_size({"width": vw, "height": vh})
        print(f"  viewport: {vw}x{vh}")
    except Exception as e:
        print(f"  set_viewport_size warning: {e}")

    print(f"  → opening {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"  goto warning: {e} (browser still open, continuing)")

    print("\n" + "=" * 64)
    print(f"  Browser open on DISPLAY={os.environ.get('DISPLAY')}")
    print("  VNC into vm03:5900 (via SSH tunnel) to see the window.")
    print()
    print("  In the VNC window:")
    print("    1. Log in if needed")
    print("    2. Send a test query (e.g. type '你好' and submit)")
    print("    3. If CAPTCHA pops up — drag images to solve it")
    print("    4. Wait for a clean AI response (no CAPTCHA visible)")
    print()
    print("  Once verified, return here and press Enter to save.")
    print("=" * 64 + "\n")

    await asyncio.get_event_loop().run_in_executor(
        None, input, ">>> Press Enter when done (or Ctrl+C to abort): "
    )

    print(f"\n[{engine}] saving session...")
    await save_page_session(engine, ctx, account_id=account_id)

    # Stats
    state = await ctx.storage_state()
    n_cookies = len(state.get("cookies", []))
    n_origins = len(state.get("origins", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    print(f"  saved: {n_cookies} cookies, {n_origins} origins, {n_ls} localStorage entries")

    try:
        await ctx.close()
    except Exception:
        pass
    if headed_browser:
        try:
            await headed_browser.close()
        except Exception:
            pass
    if headed_pw:
        try:
            await headed_pw.stop()
        except Exception:
            pass

    print(f"\n[{engine}] account={account_id} done. Now test:")
    print(f"  curl -X POST http://127.0.0.1:8092/search -H 'Content-Type: application/json' \\")
    print(f"    -d '{{\"engine\":\"{engine}\",\"query\":\"小米汽车\"}}'")


if __name__ == "__main__":
    asyncio.run(main())
