#!/usr/bin/env python3
"""Harvest engine sessions on a user's machine, upload to central pool.

跑一次,自动过 5 个 engine(doubao/qwen/deepseek/wenxin/yuanbao):
  - 启 headed Chromium 打开各 engine 的 chat 页
  - 检测登录态;没登录就提示用户在 VNC/本机窗口里登录 + 过 CAPTCHA
  - 抓 context.storage_state() → POST /api/engine-sessions/upload

用法:
  pip install playwright httpx
  playwright install chromium

  export ENGINE_SESSION_API=https://api.example.com   # 默认 prod
  export ENGINE_SESSION_HARVEST_TOKEN=<token-from-ops>
  python harvest_sessions.py [doubao qwen ...]        # 不指定 = 全部 5 个

  # 自定义 label(默认机器 hostname):
  python harvest_sessions.py --label alice-mac

只依赖 playwright + httpx,**不依赖** GEO 仓库的任何其他模块 ——
可以单文件拷给非技术用户运行。

设计选择:
  - 用 Playwright bundled Chromium(不是用户系统 Chrome)— 让 vm03 上的
    patchright Chromium 复用时 TLS/JA3 指纹尽量一致,减少 ByteDance 风控
    "cookie 跨 client 漂移"误判
  - 单次登录后不退出,让用户验证一次"我能正常聊一句"再保存,确认 session 真活
  - 失败时 print 清晰指引,不静默继续下一个 engine
"""
from __future__ import annotations

import argparse
import asyncio
import os
import platform as _platform
import socket
import sys
from typing import Optional

try:
    import httpx
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: missing deps. Run: pip install playwright httpx && playwright install chromium")
    sys.exit(1)


# ── Per-engine config: chat URL + "已登录"检测 selector ────────────


_ENGINE_CFG = {
    # engine_key → (chat_url, "登录后才出现"的 selector,用于检测 logged_in)
    "doubao":   ("https://www.doubao.com/chat/",   "textarea.semi-input-textarea, textarea[placeholder='发消息...']"),
    "qwen":     ("https://chat.qwen.ai/",          "textarea.message-input-textarea"),
    "deepseek": ("https://chat.deepseek.com/",     "textarea"),
    "wenxin":   ("https://yiyan.baidu.com/",       "textarea, [contenteditable='true']"),
    "yuanbao":  ("https://yuanbao.tencent.com/",   "textarea, [contenteditable='true']"),
}


# ── Helpers ────────────────────────────────────────────────────────


def _default_label() -> str:
    """username@hostname,带 OS 后缀。"""
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "anon"
    host = socket.gethostname()
    osname = _platform.system().lower()
    return f"{user}@{host}-{osname}"


def _api_base() -> str:
    return (os.environ.get("ENGINE_SESSION_API") or "https://api.vigilath.com").rstrip("/")


def _harvest_token() -> str:
    tok = (os.environ.get("ENGINE_SESSION_HARVEST_TOKEN") or "").strip()
    if not tok:
        print("ERROR: set ENGINE_SESSION_HARVEST_TOKEN environment variable.")
        print("       Ask ops for the current token.")
        sys.exit(1)
    return tok


async def _harvest_one(engine: str, label: str, pw, api_base: str, token: str) -> bool:
    """Returns True iff successfully uploaded."""
    if engine not in _ENGINE_CFG:
        print(f"  [{engine}] unknown engine, skip")
        return False
    url, logged_in_sel = _ENGINE_CFG[engine]

    print(f"\n{'─' * 60}")
    print(f"  [{engine}] launching headed Chromium → {url}")

    # 用 bundled Chromium。不传 channel="chrome" — 故意用 Playwright 自带的,
    # 这样不管用户系统装的什么 Chrome 版本,vm03 那边 patchright 也用 bundled,
    # 两边渲染 / TLS 指纹更接近。
    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context(
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"  [{engine}] goto warning: {e}")

    print(f"  [{engine}] window opened. In the browser window:")
    print(f"           1. Log in if needed (phone / WeChat / etc.)")
    print(f"           2. Send a test message (e.g. type '你好' and submit)")
    print(f"           3. Solve CAPTCHA if any pops up")
    print(f"           4. Wait until you see a real AI response")
    print()
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, input, f"  [{engine}] >>> Press Enter when done (or 's' + Enter to skip): "
        )
    except KeyboardInterrupt:
        print(f"\n  [{engine}] aborted by user")
        await context.close()
        await browser.close()
        return False

    # 检测是否真的登录了
    try:
        logged_in = await page.locator(logged_in_sel).count() > 0
    except Exception:
        logged_in = False
    if not logged_in:
        print(f"  [{engine}] WARN: login signal selector ({logged_in_sel}) not found —")
        print(f"           session may not actually be logged in. Saving anyway,")
        print(f"           but server-side may reject if cookies list is empty.")

    state = await context.storage_state()
    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    ua = await page.evaluate("() => navigator.userAgent")
    plat = await page.evaluate("() => navigator.platform")
    # best-effort 抓页面上的掩码手机号当账号展示名;抓不到不影响上传
    try:
        handle = await page.evaluate(
            "() => { const m = (document.body.innerText || '')"
            ".match(/\\b1[3-9]\\d\\*{3,6}\\d{2,4}\\b/); return m ? m[0] : null; }"
        )
    except Exception:
        handle = None

    print(f"  [{engine}] captured: cookies={n_cookies} localStorage={n_ls}")

    if n_cookies == 0:
        print(f"  [{engine}] SKIP upload: zero cookies (not logged in)")
        await context.close()
        await browser.close()
        return False

    # Upload
    print(f"  [{engine}] uploading to {api_base}/api/engine-sessions/upload ...")
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{api_base}/api/engine-sessions/upload",
                headers={"X-Harvest-Token": token},
                json={
                    "engine": engine,
                    "storage_state": state,
                    "source_label": label,
                    "account_handle": handle,
                    "user_agent": ua,
                    "platform": plat,
                    "ttl_days": 7,
                },
            )
        if r.status_code in (200, 201):
            data = r.json()
            verb = "renewed" if data.get("renewed") else "uploaded (new)"
            print(f"  [{engine}] ✓ {verb} id={data.get('id')} "
                  f"handle={data.get('account_handle') or '-'} expires={data.get('expires_at')}")
            ok = True
        else:
            print(f"  [{engine}] ✗ server returned {r.status_code}: {r.text[:300]}")
            ok = False
    except Exception as e:
        print(f"  [{engine}] ✗ upload failed: {e}")
        ok = False

    await context.close()
    await browser.close()
    return ok


async def main():
    parser = argparse.ArgumentParser(description="Harvest engine sessions and upload to central pool")
    parser.add_argument("engines", nargs="*", help=f"engines to harvest (default: all {list(_ENGINE_CFG)})")
    parser.add_argument("--label", default=None, help=f"source label (default: {_default_label()})")
    args = parser.parse_args()

    engines = args.engines or list(_ENGINE_CFG)
    label = args.label or _default_label()
    api_base = _api_base()
    token = _harvest_token()

    print(f"  API   : {api_base}")
    print(f"  Label : {label}")
    print(f"  Engines: {engines}")

    results = {}
    async with async_playwright() as pw:
        for engine in engines:
            results[engine] = await _harvest_one(engine, label, pw, api_base, token)

    print(f"\n{'═' * 60}")
    print(f"  SUMMARY")
    print(f"{'═' * 60}")
    for engine, ok in results.items():
        print(f"    {engine:<10} {'✓ uploaded' if ok else '✗ failed / skipped'}")


if __name__ == "__main__":
    asyncio.run(main())
