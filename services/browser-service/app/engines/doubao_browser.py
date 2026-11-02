"""Doubao (豆包) browser adapter — automates www.doubao.com.

Doubao is ByteDance's AI chat product. The 2026-04 UI exposes skills as
buttons in the chat action bar: 快速, 超能模式, PPT 生成, 图像生成,
帮我写作, and 更多 (which opens 深入研究, 编程, etc.).

DOM notes (2026-04, Semi Design):
  - Input: <textarea class="semi-input-textarea semi-input-textarea-autosize">
    with placeholder="发消息...". A hidden textarea (height=0) must be avoided.
  - Skill buttons: div/button elements with Tailwind classes, text-based matching.
  - "深入研究" (deep research): behind the "更多" menu, provides web-cited answers.
  - Response: streaming markdown in the last assistant message bubble.
    Doubao renders references as superscript links [1][2] with <a href>.
  - Citations also appear in a "参考来源" section or collapsible source cards.

Network capture:
  The chat completion API streams SSE responses. Each chunk may contain
  structured citation data (url, title). We intercept all /api/ responses
  to extract these before falling back to DOM scraping.

Requires: a valid Doubao session (run scripts/doubao_login.py first).
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
from typing import List

from ..browser import (
    create_stealth_page,
    create_headed_page,
    human_delay,
    human_move_mouse,
    human_click,
    human_scroll,
    simulate_browsing,
    save_page_session,
)
from ..anti_detect import _pick_profile


async def _close_headed(ctx, browser=None, pw=None) -> None:
    """Close headed browser context, browser, and playwright instance."""
    try:
        await ctx.close()
    except Exception:
        pass
    if browser:
        try:
            await browser.close()
        except Exception:
            pass
    if pw:
        try:
            await pw.stop()
        except Exception:
            pass
from .base import Citation, EngineAdapter, EngineResult
from ..session_store import report_session_outcome


def _is_xvfb_display() -> bool:
    """Check if current DISPLAY was set by our Xvfb module."""
    import os
    display = os.environ.get("DISPLAY", "")
    return display.startswith(":") and display.lstrip(":").isdigit()


# CloakBrowser/某些代理路径下,豆包 SSE JSON 的 title 字段会以 CP1252
# codepoint(\uXXXX)形式把 UTF-8 字节编进去,json.loads 出来全是 'ä¸–çºªäº\x81'
# 这种乱码。手工 CP1252 表 + latin-1 fallback 反编码。跟 yuanbao_browser.py
# 同款实现,只是局部化在豆包里(两个 engine 都自带,日后可以提到 base.py)。
_CP1252_HIGH = {
    0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84, 0x2026: 0x85,
    0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88, 0x2030: 0x89, 0x0160: 0x8A,
    0x2039: 0x8B, 0x0152: 0x8C, 0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92,
    0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
    0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B, 0x0153: 0x9C,
    0x017E: 0x9E, 0x0178: 0x9F,
}


def _fix_mojibake(s: str) -> str:
    """还原 'UTF-8 bytes decoded as CP1252/Latin-1' mojibake('世'→'ä¸–')。

    仅在含典型 mojibake 引导字符且能干净往返时改;否则原样返回避免误伤干净串。"""
    if not s or not any(c in s for c in "äÃâåæçèéêëìíîï"):
        return s
    try:
        bs = bytearray()
        for ch in s:
            cp = ord(ch)
            if cp < 0x100:
                bs.append(cp)
            elif cp in _CP1252_HIGH:
                bs.append(_CP1252_HIGH[cp])
            else:
                return s
        return bs.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return s


# Hosts to exclude from citation results
_DOUBAO_BLOCK_HOSTS = (
    "doubao.com",
    "bytedance.com",
    "volcengine.com",
    "tiktok.com",
    "ibytedapm.com",
    "lf-flow-web-cdn.doubao.com",
    "bdurl.net",
    "byteimg.com",
    "bytednsdoc.com",
    "bytegoofa.com",
    "bytegecko.com",
    "byteoversea.com",
    "bdurl.net",
    "snssdk.com",
    "pstatp.com",
    "bytecss.cn",
    "bytetos.com",
    "feiliao.com",
    "iesdouyin.com",
)


class DoubaoBrowserAdapter(EngineAdapter):
    name = "豆包"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://www.doubao.com/chat/"

    async def is_available(self) -> bool:
        return (await self.verify_session())["status"] == "ok"

    async def verify_session(self) -> dict:
        from ..session_verifier import verify_account_session
        return await verify_account_session(self, "doubao", probe_new_chat=True)

    # D4c(2026-05-18):hot browser protocol —— EngineSession 用 _create_hot_page +
    # _prepare_page + _query_with_page + _close_hot_page 复用 cloakbrowser ctx.
    # search() **不动**,保持 one-shot 零回归.
    async def _create_hot_page(self):
        """豆包专用:Xvfb + headed + cloakbrowser/patchright + channel=chrome.

        参数全跟 search() 那一段对齐 — profile pin Linux x86_64,channel=chrome.
        """
        import os
        # Xvfb 启动(若 DISPLAY 未设)
        if os.name != "nt" and not os.environ.get("DISPLAY"):
            from ..xvfb import start_xvfb
            start_xvfb()
        profile = _pick_profile(platform_filter="Win32" if os.name == "nt" else "Linux x86_64")
        page, ctx = await create_headed_page(
            "doubao",
            profile=profile,
            record_video=self._record_video,
            channel="chrome",
        )
        return page, ctx

    async def _close_hot_page(self, page, ctx) -> None:
        """豆包专用:cloakbrowser 的 headed_browser + pw_ref 也要 close."""
        headed_browser = getattr(page, "_headed_browser", None)
        headed_pw = getattr(page, "_pw_ref", None)
        await _close_headed(ctx, headed_browser, headed_pw)


    #
    # 注意 doubao 特殊性(deploy doc 第 9 节):
    #   - 走 create_headed_page (cloakbrowser / patchright + Xvfb)
    #   - 每条 query 之前必须 simulate_browsing 暖身(ByteDance 看时序)
    #   - per-char keyboard.type(60-220ms 抖动),不能 fill / insert_text
    #   - 发送优先 send button,Enter 兜底
    #   - CAPTCHA 路径要 dump screenshot + 报 FailureType=captcha 让 pool 隔离
    #   - 没法在 _prepare_page 里做 simulate_browsing(那是 per-query 行为)
    async def _prepare_page(self, page, ctx) -> None:
        """Hot init:goto + 网络抓包 listener + popups + 预检 captcha.

        不做 _start_new_chat / simulate_browsing — 那俩 per-query.
        """
        # 网络抓包 — listener 挂 page,每次 query 前 clear list
        self._captured_bodies = []

        def _on_response(response):
            url_l = response.url.lower()
            if not any(kw in url_l for kw in ("/api/", "chat", "completion", "search")):
                return
            ctype = (response.headers.get("content-type") or "").lower()
            if ctype and not any(
                t in ctype for t in ("json", "event-stream", "text/plain", "text/html")
            ):
                return
            try:
                asyncio.create_task(self._capture_body(response, self._captured_bodies))
            except Exception:
                pass

        page.on("response", _on_response)

        await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
        await human_delay(3, 5)
        # 初始 captcha 预检(很罕见,但出现就该立即放弃这个 session)
        if await self._check_captcha(page):
            raise RuntimeError(
                "captcha on initial load — session needs rotate (login_lost/captcha state)"
            )
        await self._dismiss_popups(page)

    async def _query_with_page(self, page, ctx, query: str) -> EngineResult:
        """Hot query:reset chat → warm-up → input → submit → wait → extract.

        captcha mid-query → 返回 error,EngineSession 据此调 rotate.
        """
        # 清上一轮的网络 body 累积
        self._captured_bodies = []

        sys.__stdout__.write("[Doubao-hot] start new chat\n"); sys.__stdout__.flush()
        await self._start_new_chat(page)

        sys.__stdout__.write("[Doubao-hot] simulate warm-up\n"); sys.__stdout__.flush()
        try:
            await simulate_browsing(page, duration=random.uniform(3.0, 6.0))
        except Exception as e:
            sys.__stdout__.write(f"[Doubao-hot] simulate warning: {e}\n"); sys.__stdout__.flush()

        input_el = await self._find_input(page)
        if input_el is None:
            return EngineResult(engine=self.name, query=query, error="input not found")

        try:
            box = await input_el.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await human_click(page, cx, cy)
            else:
                await input_el.click()
        except Exception:
            await input_el.click()
        await human_delay(1.2, 2.8)

        typed_query = f"{query},请展示引用来源"
        for ch in typed_query:
            await page.keyboard.type(ch, delay=random.randint(60, 220))
        await human_delay(0.8, 2.2)

        # Submit
        submitted = False
        try:
            send_btn = page.locator(
                "[data-testid='send-button'], "
                "button[aria-label='发送'], "
                "button[aria-label='Send'], "
                "button:has(svg) >> nth=-1"
            ).first
            if await send_btn.is_visible(timeout=1500):
                await send_btn.click()
                submitted = True
        except Exception:
            pass
        if not submitted:
            await page.keyboard.press("Enter")

        # Post-submit CAPTCHA(豆包关键防线)
        await human_delay(3, 5)
        if await self._check_captcha(page):
            return EngineResult(
                engine=self.name, query=query,
                error="CAPTCHA: ByteDance challenged the request after submit",
            )

        await self._wait_for_stable_answer(page, max_wait=90, stable_secs=3.0)
        await human_delay(1.0, 2.0)

        answer = await self._extract_answer(page)
        citations = await self._extract_citations(page, answer)
        return EngineResult(engine=self.name, query=query, answer=answer, citations=citations,
            citation_collection=getattr(page, "_geo_citation_collection", {}), source_url=page.url)

    async def search(self, query: str) -> EngineResult:
        import os
        # Pin a single device profile for the whole query lifecycle.
        # Force "Linux x86_64" so what we CLAIM matches what vm03 actually
        # IS — Linux + Mesa + freetype fonts. If we keep claiming "Mac M1"
        # but render on Linux/Xvfb, ByteDance compares canvas/font output
        # to the UA-declared platform and instantly flags the mismatch.
        # Linux Chrome users are uncommon but real; not a bot signal by
        # itself, while UA-vs-renderer mismatch IS one.
        profile = _pick_profile(platform_filter="Win32" if os.name == "nt" else "Linux x86_64")

        # Doubao runs ByteDance's anti-bot stack which fingerprints headless
        # Chromium reliably (window.chrome shape, Permissions API behavior,
        # WebGL precision drift, etc.) regardless of stealth scripts. The only
        # reliable bypass is launching real headed Chromium against an Xvfb
        # virtual display. Auto-start Xvfb if no DISPLAY is set.
        if os.name != "nt" and not os.environ.get("DISPLAY"):
            from ..xvfb import start_xvfb
            if start_xvfb():
                sys.__stdout__.write(
                    "[Doubao] Xvfb started for headed Chromium "
                    f"(DISPLAY={os.environ.get('DISPLAY')})\n"
                )
                sys.__stdout__.flush()

        use_headed = (
            (os.name == "nt" or bool(os.environ.get("DISPLAY")))
            and os.environ.get("DOUBAO_HEADED") != "0"
        )

        try:
            if use_headed:
                # channel="chrome" forces the real google-chrome binary —
                # only the real binary has the matching TLS JA3 + native
                # Sec-CH-UA full-version-list that ByteDance compares
                # against. Bundled Chromium has subtly different TLS
                # extension order, ALPN, and brand string that flag bot.
                page, ctx = await create_headed_page(
                    "doubao",
                    profile=profile,
                    record_video=self._record_video,
                    channel="chrome",
                )
                headed_browser = getattr(page, "_headed_browser", None)
                headed_pw = getattr(page, "_pw_ref", None)
            else:
                page, ctx = await create_stealth_page(
                    "doubao", record_video=self._record_video, profile=profile
                )
                headed_browser = None
                headed_pw = None

            # Check for captcha before proceeding
            await self._check_captcha(page)

            # Network capture: intercept chat API responses for citation URLs
            captured_bodies: List[str] = []
            self._captured_bodies = captured_bodies

            def _on_response(response):
                url_l = response.url.lower()
                if not any(kw in url_l for kw in ("/api/", "chat", "completion", "search")):
                    return
                ctype = (response.headers.get("content-type") or "").lower()
                if ctype and not any(
                    t in ctype
                    for t in ("json", "event-stream", "text/plain", "text/html")
                ):
                    return
                try:
                    asyncio.create_task(self._capture_body(response, captured_bodies))
                except Exception:
                    pass

            page.on("response", _on_response)

            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            await human_delay(3, 5)

            # Confirm WHICH chrome binary we actually launched. fallback in
            # create_headed_page silently switches to bundled chromium if
            # channel="chrome" failed — we need to know.
            try:
                import subprocess as _sp
                # Match BOTH possible binaries: real google-chrome AND bundled chromium
                pids_raw = _sp.check_output(
                    ["pgrep", "-f", "(chrome-linux64/chrome|google-chrome)"],
                    text=True,
                ).strip().split("\n")[:5]
                bins = set()
                for p in pids_raw:
                    p = p.strip()
                    if not p:
                        continue
                    try:
                        import os as _os
                        bins.add(_os.readlink(f"/proc/{p}/exe"))
                    except Exception:
                        continue
                sys.__stdout__.write(f"[Doubao-binary] {sorted(bins)}\n")
                sys.__stdout__.flush()
            except Exception as e:
                sys.__stdout__.write(f"[Doubao-binary] probe failed: {e}\n")
                sys.__stdout__.flush()

            # Dump our own chromium process command-line so we can verify
            # --enable-automation is actually stripped (it's the canonical
            # "controlled browser" tell — must NOT be in args).
            try:
                import subprocess as _sp
                pids = _sp.check_output(
                    ["pgrep", "-f", "(chrome-linux64/chrome|google-chrome)"], text=True
                ).strip().split("\n")[:5]
                for pid in pids:
                    if not pid.strip():
                        continue
                    try:
                        with open(f"/proc/{pid.strip()}/cmdline", "rb") as f:
                            argv = f.read().split(b"\x00")
                        flags = sorted({
                            a.decode("utf-8", "ignore")
                            for a in argv
                            if a.startswith(b"--") and any(
                                k in a for k in (
                                    b"automation", b"webdriver", b"debugging",
                                    b"AutomationControlled", b"sandbox",
                                )
                            )
                        })
                        if flags:
                            sys.__stdout__.write(
                                f"[Doubao-procargs] pid={pid.strip()} flags={flags}\n"
                            )
                            sys.__stdout__.flush()
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            # Fingerprint diagnostic: log UA, platform, canvas to stdout.
            # canvas_hash 是对完整 toDataURL 的 djb2 哈希(不是末 40 字节)—
            # PNG 的 base64 末段几乎恒定,看不出 anti_detect.py 的 ^Math.random
            # 微扰是否真的改变了像素。哈希全字符串才能看出每次跑 hash 不同。
            try:
                fp = await page.evaluate("""() => {
                    const ua = navigator.userAgent;
                    const plat = navigator.platform;
                    let canvasLen = 0;
                    let canvasHash = '(no canvas)';
                    try {
                        const c = document.createElement('canvas');
                        c.width = 64; c.height = 64;
                        const ctx2 = c.getContext('2d');
                        ctx2.textBaseline = 'top';
                        ctx2.font = '14px Arial';
                        ctx2.fillText('fp_test', 2, 2);
                        const s = c.toDataURL();
                        canvasLen = s.length;
                        let h = 5381;
                        for (let i = 0; i < s.length; i++) {
                            h = ((h << 5) + h + s.charCodeAt(i)) | 0;
                        }
                        canvasHash = (h >>> 0).toString(16).padStart(8, '0');
                    } catch(e) { canvasHash = e.message; }
                    const wl = typeof navigator.webdriver !== 'undefined' ? navigator.webdriver : '(undefined)';
                    return { ua, plat, canvasHash, canvasLen, webdriver: wl };
                }""")
                sys.__stdout__.write(
                    f"[Doubao-fingerprint] UA={fp['ua']}  "
                    f"platform={fp['plat']}  "
                    f"canvas_hash={fp['canvasHash']} (len={fp['canvasLen']})  "
                    f"webdriver={fp['webdriver']}\n"
                )
                sys.__stdout__.flush()
            except Exception as e:
                sys.__stdout__.write(f"[Doubao-fingerprint] probe failed: {e}\n")
                sys.__stdout__.flush()

            # patchright 已经在 CDP 层做 stealth,不需要再叠我们的 mouse 行为
            # 模拟(simulate_browsing/human_click)—— 那些反而可能在 Xvfb 下挂死
            # mouse.move(steps=N) 调用。input 用 fill() 一次性灌,patchright 会
            # 用 isTrusted 输入事件,ByteDance 看到的跟真人粘贴一样自然。
            sys.__stdout__.write("[Doubao-step] dismiss popups\n"); sys.__stdout__.flush()
            await self._dismiss_popups(page)

            # Click "新对话" to start a fresh conversation. /chat/ auto-resumes
            # the last session,导致连续多 query 在同一会话里堆栈,
            # _get_last_assistant_text 永远抓到的是上一轮答案 / 侧栏标题。
            sys.__stdout__.write("[Doubao-step] start new chat\n"); sys.__stdout__.flush()
            await self._start_new_chat(page)

            # Warm-up: ByteDance escalates from slider to image CAPTCHA when a
            # fresh context jumps straight from goto → focus input → submit.
            # 3-6 秒鼠标乱晃 + 微 scroll 让 timing chain 看起来像人在"环顾一下页面"。
            # 之前 DEV 版本砍掉了这段(理由"patchright 已经做 stealth"),实测拿到
            # fresh session 也照样挑 CAPTCHA — patchright 治 CDP signal,治不了
            # 行为时序 signal。
            sys.__stdout__.write("[Doubao-step] simulate browsing warm-up\n"); sys.__stdout__.flush()
            try:
                await simulate_browsing(page, duration=random.uniform(3.0, 6.0))
            except Exception as e:
                sys.__stdout__.write(f"[Doubao-step] simulate_browsing warning: {e}\n"); sys.__stdout__.flush()

            sys.__stdout__.write("[Doubao-step] find input\n"); sys.__stdout__.flush()
            input_el = await self._find_input(page)
            if input_el is None:
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query, error="input not found"
                )

            # Click input with human-like mouse path, then a "thinking pause"
            # before typing (real users focus → think → type, not focus → type).
            sys.__stdout__.write("[Doubao-step] click input + thinking pause\n"); sys.__stdout__.flush()
            try:
                box = await input_el.bounding_box()
                if box:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    await human_click(page, cx, cy)
                else:
                    await input_el.click()
            except Exception:
                await input_el.click()
            await human_delay(1.2, 2.8)

            typed_query = f"{query}，请展示引用来源"
            # Per-char typing with random delay. fill() / insert_text 一次性灌全文
            # 是最强的 bot signature — ByteDance 单看这一项就足以从 slider CAPTCHA
            # 升级到图像 CAPTCHA(后者我们解不了)。60-220ms 抖动 ≈ 真人中文输入法
            # 节奏(每个汉字一次回车或一次选词)。
            sys.__stdout__.write("[Doubao-step] per-char type query\n"); sys.__stdout__.flush()
            for ch in typed_query:
                await page.keyboard.type(ch, delay=random.randint(60, 220))

            # Post-typing review pause (humans scan their own message before sending).
            await human_delay(0.8, 2.2)

            # Submit ONCE: prefer the send button (what real users click), fall
            # back to Enter only if the button is missing. Double-submitting
            # (Enter + button click) is itself a bot signal.
            sys.__stdout__.write("[Doubao-step] submit\n"); sys.__stdout__.flush()
            submitted = False
            try:
                send_btn = page.locator(
                    "[data-testid='send-button'], "
                    "button[aria-label='发送'], "
                    "button[aria-label='Send'], "
                    "button:has(svg) >> nth=-1"
                ).first
                if await send_btn.is_visible(timeout=1500):
                    await send_btn.click()
                    submitted = True
            except Exception:
                pass
            if not submitted:
                await page.keyboard.press("Enter")
            sys.__stdout__.write(f"[Doubao-step] submitted via={'btn' if submitted else 'Enter'}\n"); sys.__stdout__.flush()

            # Check for CAPTCHA after submit. We do NOT do a close-and-reopen
            # "retry" here: the previous version closed the original context and
            # opened a brand-new one at /chat/, which has no CAPTCHA on the
            # fresh page (the CAPTCHA was on the closed page). _check_captcha
            # would then return False, the system would falsely report
            # "CAPTCHA cleared!", and the resubmit would trigger the
            # image-classification CAPTCHA we cannot solve. Cleaner to fail
            # fast on a single submission than to give ByteDance a second
            # automation signal.
            await human_delay(3, 5)
            sys.__stdout__.write("[Doubao-step] check captcha\n"); sys.__stdout__.flush()
            if await self._check_captcha(page):
                screenshot_dir = "/tmp/doubao_captcha"
                os.makedirs(screenshot_dir, exist_ok=True)
                ts = int(asyncio.get_event_loop().time())

                # Dump iframe geometry + page error indicators for diagnosis.
                try:
                    diag = await page.evaluate("""() => {
                        const iframes = Array.from(document.querySelectorAll('iframe')).map(f => {
                            const r = f.getBoundingClientRect();
                            const cs = getComputedStyle(f);
                            return {
                                src: f.src,
                                rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
                                visible: cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0,
                                z: cs.zIndex,
                            };
                        });
                        // Collect any visible error/toast text shown on the page
                        const errorTexts = [];
                        for (const sel of ['[class*="error"]', '[class*="Error"]',
                                            '[class*="toast"]', '[class*="Toast"]',
                                            '[class*="message-error"]', '[class*="failed"]']) {
                            for (const el of document.querySelectorAll(sel)) {
                                const cs = getComputedStyle(el);
                                if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                                const t = (el.textContent || '').trim();
                                if (t && t.length < 200) errorTexts.push(sel + ': ' + t);
                            }
                        }
                        return { iframes, errorTexts: errorTexts.slice(0, 10) };
                    }""")
                    sys.__stdout__.write(f"[Doubao-diag] iframes: {json.dumps(diag.get('iframes', []), ensure_ascii=False)}\n")
                    sys.__stdout__.write(f"[Doubao-diag] error_texts: {json.dumps(diag.get('errorTexts', []), ensure_ascii=False)}\n")
                except Exception as e:
                    sys.__stdout__.write(f"[Doubao-diag] probe failed: {e}\n")

                # Dump captured network bodies (the real chat API response is here)
                try:
                    bodies_path = f"{screenshot_dir}/bodies_{ts}.txt"
                    with open(bodies_path, "w") as f:
                        for i, b in enumerate(captured_bodies):
                            f.write(f"=== body {i} ({len(b)} bytes) ===\n")
                            f.write(b[:5000])
                            f.write("\n\n")
                    sys.__stdout__.write(f"[Doubao-diag] {len(captured_bodies)} api bodies → {bodies_path}\n")
                except Exception as e:
                    sys.__stdout__.write(f"[Doubao-diag] body dump failed: {e}\n")

                try:
                    await page.screenshot(path=f"{screenshot_dir}/captcha_{ts}.png")
                    html_dump = await page.content()
                    with open(f"{screenshot_dir}/page_{ts}.html", "w") as f:
                        f.write(html_dump)
                    sys.__stdout__.write(
                        f"[Doubao] CAPTCHA detected (mode={'headed' if use_headed else 'headless'}) — "
                        f"screenshot {screenshot_dir}/captcha_{ts}.png  html {screenshot_dir}/page_{ts}.html\n"
                    )
                    sys.__stdout__.flush()
                except Exception:
                    pass

                # 拿 video path 必须在 ctx 还活着时,但文件直到 ctx.close()
                # 才完整刷盘 — 所以顺序是:capture path → save session → close ctx
                # → return。之前少了 close,headed 下视频文件被截断。
                video_path = await self._capture_video(page)
                await save_page_session("doubao", ctx)
                await _close_headed(ctx, headed_browser, headed_pw)
                hint = (
                    "Run scripts/doubao_login.py on a desktop and re-upload the session."
                    if use_headed
                    else "Install Xvfb and set DISPLAY so Doubao can run headed."
                )
                # 上报 pool: 这条 session 被 CAPTCHA 挑了,calculate captcha_count + 1.
                # 累计达阈值(目前 3 次)backend 会自动 quarantine,下次 check-out 跳过。
                report_session_outcome("doubao", captcha_triggered=True)
                return EngineResult(
                    engine=self.name, query=query,
                    error=(
                        "CAPTCHA: ByteDance challenged the request after submit. "
                        f"{hint}"
                    ),
                    video_path=video_path,
                )

            # Wait for response — longer timeout after CAPTCHA recovery
            max_wait = 90
            sys.__stdout__.write("[Doubao-step] wait_for_stable_answer\n"); sys.__stdout__.flush()
            await self._wait_for_stable_answer(page, max_wait=max_wait, stable_secs=3.0)
            sys.__stdout__.write("[Doubao-step] answer stabilized\n"); sys.__stdout__.flush()
            await human_delay(1.0, 2.0)

            # Debug: dump screenshot after answer wait (CAPTCHA path)
            if headed_browser:
                try:
                    import os
                    dbg = "/tmp/doubao_captcha"
                    os.makedirs(dbg, exist_ok=True)
                    await page.screenshot(path=f"{dbg}/after_answer_{int(asyncio.get_event_loop().time())}.png")
                    html_dump = await page.evaluate("() => document.body.innerHTML")
                    with open(f"{dbg}/after_answer.html", "w") as f:
                        f.write(html_dump)
                    sys.__stdout__.write(
                        f"[Doubao-debug] post-answer dump saved ({len(html_dump)} bytes)\n"
                    )
                    sys.__stdout__.flush()
                except Exception:
                    pass

            # Debug probe
            await self._probe_page(page)

            # Extract answer + citations
            answer = await self._extract_answer(page)
            citations = await self._extract_citations(page, answer)

            await save_page_session("doubao", ctx)

            video_path = None
            if self._record_video:
                try:
                    from ..video_store import get_video_path
                    video_path = await get_video_path(page)
                except Exception:
                    pass

            await _close_headed(ctx, headed_browser, headed_pw)

            # 成功 path:session 安全过关,告诉 pool no CAPTCHA → 不动 captcha_count。
            report_session_outcome("doubao", captcha_triggered=False)
            return EngineResult(
                engine=self.name,
                query=query,
                answer=answer,
                citations=citations,
                citation_collection=getattr(page, "_geo_citation_collection", {}),
                source_url=page.url,
                video_path=video_path,
            )
        except Exception as e:
            # 例外:不知道是 CAPTCHA 还是别的,保守按 no-CAPTCHA 处理(避免误隔离)。
            report_session_outcome("doubao", captcha_triggered=False)
            return EngineResult(engine=self.name, query=query, error=str(e))

    async def _capture_video(self, page) -> str | None:
        """Capture video path from page before context is closed."""
        if not self._record_video:
            return None
        try:
            from ..video_store import get_video_path
            return await get_video_path(page)
        except Exception:
            return None

    # ── Popup dismissal ────────────────────────────────────────

    async def _check_captcha(self, page) -> bool:
        """Check if ByteDance CAPTCHA is present/active. Returns True if blocked.

        Only matches HIGH-CONFIDENCE CAPTCHA signals. The previous version had
        broad heuristics ([class*='captcha'], [class*='overlay'], hidden input
        + any modal) that false-positive on Doubao's normal error states (e.g.
        the red ⚠️ that appears next to a rate-limited message has no CAPTCHA
        UI but used to trip the broad selector). Let real CAPTCHA flows be
        flagged by the SDK iframe / explicit container; everything else falls
        through and lets the answer-waiting path run.
        """
        try:
            which = await page.evaluate("""() => {
                // 1. ByteDance CAPTCHA SDK loads its widget in an iframe whose
                //    src points at verify.zijieapi.com or a /captcha/ path.
                for (const iframe of document.querySelectorAll('iframe')) {
                    const src = iframe.src || '';
                    if (src.includes('verify.zijieapi.com')
                        || src.includes('verifycenter')
                        || /\\/captcha\\//.test(src)) {
                        const r = iframe.getBoundingClientRect();
                        if (r.width > 100 && r.height > 100) return 'iframe:' + src.slice(0, 80);
                    }
                }
                // 2. Explicit slider container the SDK injects when active.
                const slider = document.getElementById('captcha_container')
                    || document.querySelector('#captcha-sdk, .captcha-sdk-container');
                if (slider) {
                    const style = getComputedStyle(slider);
                    if (style.display !== 'none' && style.visibility !== 'hidden'
                        && slider.offsetWidth > 50 && slider.innerHTML.length > 0) {
                        return 'slider';
                    }
                }
                // 3. Image-classification CAPTCHA: ByteDance renders a modal
                //    with clickable image tiles. Require BOTH a visible
                //    captcha-named container AND >= 4 clickable images.
                for (const ov of document.querySelectorAll(
                    '[class*="captcha"], [class*="Captcha"]'
                )) {
                    const s = getComputedStyle(ov);
                    if (s.display === 'none' || s.visibility === 'hidden') continue;
                    if (ov.offsetWidth < 200 || ov.offsetHeight < 150) continue;
                    if (ov.querySelectorAll('img').length >= 4) return 'image_modal';
                }
                return '';
            }""")
            if which:
                sys.__stdout__.write(f"[Doubao] _check_captcha matched: {which}\n")
                sys.__stdout__.flush()
                return True
            return False
        except Exception:
            return False

    async def _wait_for_captcha_clear(self, page, timeout: int = 120) -> bool:
        """Poll until CAPTCHA disappears or timeout. Returns True if cleared."""
        poll_interval = 2.0
        elapsed = 0.0
        while elapsed < timeout:
            if not await self._check_captcha(page):
                # Extra check: wait a bit and re-verify it stays gone
                await asyncio.sleep(1.5)
                if not await self._check_captcha(page):
                    return True
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if int(elapsed) % 10 == 0:
                remaining = int(timeout - elapsed)
                sys.__stdout__.write(
                    f"[Doubao] Still waiting for CAPTCHA... ({remaining}s remaining)\n"
                )
                sys.__stdout__.flush()
        return False

    async def _dismiss_popups(self, page) -> None:
        for sel in [
            "text=我知道了",
            "text=同意",
            "text=Accept",
            "text=接受全部",
            "text=不再提示",
            "text=关闭",
            "text=下载电脑版",
            "[aria-label='close']",
            "[aria-label='Close']",
            "[class*='close'] >> visible=true",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    await human_delay(0.3, 0.6)
            except Exception:
                continue

    async def _start_new_chat(self, page) -> None:
        """Accept an already-empty welcome page, otherwise verify chat reset."""
        async def _is_welcome_page() -> bool:
            return await page.evaluate(r"""() => {
                if (location.pathname.replace(/\/$/, '') !== '/chat' || location.search) return false;
                const visible = el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
                const input = [...document.querySelectorAll('textarea, [contenteditable="true"]')]
                    .some(el => visible(el) && !el.disabled && !el.readOnly && el.getAttribute('aria-disabled') !== 'true');
                const welcome = [...document.querySelectorAll('h1, h2, h3, div, p')]
                    .some(el => visible(el) && /^(有什么我能帮你的吗[？?]?|有什么可以帮你[？?]?|你好[，,]我是豆包[！!。.]?)$/.test((el.innerText || '').trim()));
                const rows = document.querySelectorAll('[class*="message-list-"] .v_list_row, [data-testid="receive_message"], [data-testid="send_message"]').length;
                return input && welcome && rows === 0;
            }""")

        if await _is_welcome_page():
            return
        candidates = [
            "[class*='nav-link-']:has-text('新对话')",
            "[class*='sidebar_nav_item']:has-text('新对话')",
            "div.font-semibold:text-is('新对话')",
            "button:text-is('新对话')",
            "[role='button']:text-is('新对话')",
            "text=新对话",
        ]

        async def _count_rows() -> int:
            try:
                return await page.evaluate("""() => {
                    const list = document.querySelector('[class*="message-list-"]');
                    if (!list) return 0;
                    return list.querySelectorAll('.v_list_row').length;
                }""")
            except Exception:
                return -1

        url_before = page.url
        rows_before = await _count_rows()

        for attempt in range(2):
            clicked = False
            for sel in candidates:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        clicked = True
                        sys.__stdout__.write(
                            f"[Doubao-new-chat] attempt {attempt+1} clicked via {sel!r}\n"
                        )
                        sys.__stdout__.flush()
                        break
                except Exception:
                    continue
            if not clicked:
                sys.__stdout__.write(
                    f"[Doubao-new-chat] attempt {attempt+1}: button not found\n"
                )
                sys.__stdout__.flush()
                await human_delay(0.5, 1.0)
                continue  # 进下一轮 attempt,而不是 return 整个函数 — 否则后续 query 进旧会话

            # 等 reset 生效:URL 变到 `/chat/`(无 slug)OR 行数减少
            reset_ok = False
            for _ in range(25):  # 25 × 0.2s = 5s
                await asyncio.sleep(0.2)
                url_now = page.url
                # URL 校验:斜杠后没有 slug = /chat/ 或 /chat
                url_reset = (
                    url_now.endswith("/chat/") or url_now.endswith("/chat")
                ) and url_now != url_before
                rows_now = await _count_rows()
                rows_reset = rows_before > 0 and rows_now == 0
                if await _is_welcome_page() or rows_reset or (url_reset and rows_now == 0):
                    reset_ok = True
                    sys.__stdout__.write(
                        f"[Doubao-new-chat] verified reset (url_reset={url_reset} "
                        f"rows {rows_before}->{rows_now})\n"
                    )
                    sys.__stdout__.flush()
                    break

            if reset_ok:
                await human_delay(0.5, 1.0)  # 再给 UI 一点 settle 时间
                return

            sys.__stdout__.write(
                f"[Doubao-new-chat] attempt {attempt+1}: reset NOT verified after 5s "
                f"(url stayed={url_before == page.url}, rows {rows_before}->{await _count_rows()})\n"
            )
            sys.__stdout__.flush()
            await human_delay(0.5, 1.0)  # 重试前小歇

        # 2 轮都没 reset 成功 — raise 让 EngineSession 归 error,runner 不抽取竞品,避免污染数据.
        # 历史教训(2026-05-14 run_id=20):reset 失败时 silent return,后续 query 进残留会话,
        # doubao 拿到"泡泡玛特 vs MINISO LAND"的串扰回复并被 LLM 抽成竞品,污染 brand-growth 数据.
        # Keep the service log ASCII-safe on Windows GBK consoles. A logging
        # failure here must never turn an otherwise valid answer into a search error.
        sys.__stdout__.write("[Doubao-new-chat] [WARN] both attempts failed to verify reset\n")
        sys.__stdout__.flush()
        raise RuntimeError(
            "doubao new-chat reset failed after 2 attempts — refusing to send query into "
            "a stale session (would contaminate answer with prior conversation)"
        )

    # ── Enable web search toggle ───────────────────────────────

    # ── Input detection ────────────────────────────────────────

    async def _find_input(self, page):
        """Find the chat input element. Returns the locator or None."""
        # 2026-04 update: Doubao switched from contenteditable to Semi Design textarea.
        # Must target the visible textarea (placeholder="发消息..."), not the hidden one (height=0).
        for sel in [
            "textarea.semi-input-textarea",
            "textarea[placeholder='发消息...']",
            "textarea[placeholder]",
            "[contenteditable='true'][class*='input']",
            "[contenteditable='true'][class*='editor']",
            "[contenteditable='true']",
        ]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    box = await el.bounding_box()
                    if box and box["height"] > 5:
                        return el
            except Exception:
                continue
        return None

    # ── Response waiting ───────────────────────────────────────

    async def _wait_for_stable_answer(
        self, page, max_wait: float = 120.0, stable_secs: float = 2.0
    ) -> None:
        """Poll the last assistant message's inner_text until stable.

        Uses the same engine-agnostic approach as Qwen: wait for the
        answer text to stop changing for `stable_secs` seconds.
        """
        poll_interval = 0.8
        last_text = ""
        stable_since = None
        elapsed = 0.0

        while elapsed < max_wait:
            try:
                cur = await self._get_last_assistant_text(page)
            except Exception:
                cur = last_text

            # Need substantive content (>8 chars) to consider stable
            if cur and len(cur.strip()) > 8 and cur == last_text:
                if stable_since is None:
                    stable_since = elapsed
                elif elapsed - stable_since >= stable_secs:
                    return
            else:
                last_text = cur
                stable_since = None

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

    async def _get_last_assistant_text(self, page) -> str:
        """Get the text content of the last assistant message bubble.

        必须 scope 到 .message-list-* 主消息区。Doubao 2026-04 侧栏的
        会话列表用 chat-item-*,标题里就有 .content-* 类的标题文本(例如
        "脑部疾病生物制药公司及引用来源"),如果用 [class*='content-']
        这种宽匹配,会把侧栏最后一条会话标题当成"最新答案",所有 query
        返回都变成同一段侧栏标题。修复:
          1) 只在 .message-list- 主区(或退化到无 sidebar 的 page)里找
          2) 拒绝 chat-item-* / nav-link-* / sidebar-* 命中
        """
        # 主路径:JS 内做"在 .message-list- 里找最后一个 receive 行"。
        # 避开侧栏(chat-item-*)与导航(nav-link-*)。
        try:
            text = await page.evaluate("""() => {
                // 优先 .message-list-*(Doubao 2026-04 主消息区)。
                const list = document.querySelector('[class*="message-list-"]');
                const root = list || document.body;
                const rows = root.querySelectorAll('.v_list_row');
                for (let i = rows.length - 1; i >= 0; i--) {
                    const row = rows[i];
                    // 跳过 user side(send-msg)
                    if (row.querySelector('[class*="send-msg"], [data-send]')) continue;
                    // 跳过被 sidebar 包裹的(防御性 — message-list 内不该出现)
                    if (row.closest('[class*="chat-item-"], [class*="nav-link-"], [class*="sidebar"], nav')) continue;
                    // 优先抓答案正文容器(content-pWK1u_ 这种 hash class)
                    const contentEl = row.querySelector('[class*="content-"]:not([class*="chat-item-"]):not([class*="send-msg"])');
                    const text = (contentEl ? contentEl.innerText : row.innerText) || '';
                    if (text.trim().length > 10) return text;
                }
                return '';
            }""")
            if text and text.strip():
                return text
        except Exception:
            pass

        # 退化路径:在 .message-list- 内试更具体的 selectors
        for sel in [
            "[class*='message-list-'] [class*='markdown-body']",
            "[class*='message-list-'] [class*='markdown']",
            "[class*='message-list-'] [class*='rich-text']",
            "[class*='message-list-'] [class*='content-'][class*='pWK']",
        ]:
            try:
                els = await page.locator(sel).all()
                if els:
                    text = await els[-1].inner_text()
                    if text and text.strip():
                        return text
            except Exception:
                continue

        return ""

    # ── Network capture ────────────────────────────────────────

    async def _capture_body(self, response, bucket: List[str]) -> None:
        """Read a response body and stash text containing URL-like content."""
        try:
            text = await response.text()
        except Exception:
            return
        if not text or "http" not in text:
            return
        bucket.append(text[:400_000])
        # Optional debug dump (set GEO_DOUBAO_DUMP_BODIES=1 to re-enable).
        # Useful when adding new citation field shapes; off by default to
        # avoid filling /tmp.
        import os as _os
        if _os.environ.get("GEO_DOUBAO_DUMP_BODIES", "").strip() in ("1", "true"):
            try:
                dump_dir = "/tmp/doubao_bodies"
                _os.makedirs(dump_dir, exist_ok=True)
                ts = int(asyncio.get_event_loop().time() * 1000)
                url_short = response.url[:80].replace("/", "_").replace(":", "")
                with open(f"{dump_dir}/{ts}_{url_short}.txt", "w") as f:
                    f.write(f"URL: {response.url}\n")
                    f.write(f"Status: {response.status}\n")
                    f.write(f"Content-Type: {response.headers.get('content-type','')}\n")
                    f.write("---\n")
                    f.write(text[:200_000])
            except Exception:
                pass

    # ── Answer extraction ──────────────────────────────────────

    async def _extract_answer(self, page) -> str:
        """Extract the answer text from the last assistant message."""
        # Use the shared text-extraction logic
        text = await self._get_last_assistant_text(page)
        if text:
            cleaned = text
            for noise in ("参考来源", "参考资料", "来源：", "以上信息来源于"):
                cleaned = cleaned.replace(noise, "")
            return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return ""

    # ── Citation extraction (multi-path) ───────────────────────

    async def _extract_source_panel(self, page) -> List[Citation]:
        """Read numbered entries from the current answer's actual source panel.

        Preserve its numbered entries, including repeated URLs. The platform's
        declared total counts entries, so URL deduplication cannot establish
        whether the panel was fully read.
        """
        read_panel = """() => {
            const pattern = /^(?:搜索\\s*\\d+\\s*个关键词[，,]\\s*)?参考\\s*\\d+\\s*篇资料$/;
            const headers = [...document.querySelectorAll('div,span,button')].filter(el =>
                pattern.test((el.innerText || '').trim()) &&
                ![...el.children].some(child => pattern.test((child.innerText || '').trim())));
            const header = headers[headers.length - 1];
            if (!header) return [];
            let container = header.parentElement;
            for (let depth = 0; container && depth < 6; depth++, container = container.parentElement) {
                const links = [...container.querySelectorAll('a[href^="http"]')].filter(a =>
                    /^\\d+[.．]\\s/.test((a.innerText || '').trim()));
                if (links.length) return links.map(a => ({href:a.href, title:(a.innerText || '').trim()}));
            }
            return [];
        }"""
        try:
            links = await page.evaluate(read_panel) or []
            if not links:
                header = page.get_by_text(re.compile(
                    r"^(?:搜索\s*\d+\s*个关键词[，,]\s*)?参考\s*\d+\s*篇资料$"
                )).last
                if await header.count():
                    await header.dispatch_event("click")
                    await page.wait_for_timeout(500)
                    links = await page.evaluate(read_panel) or []
            return [Citation.from_url(
                link["href"], title=re.sub(r"^\d+[.．]\s*", "", link["title"]), position=i,
            ) for i, link in enumerate(links, 1)]
        except Exception as exc:
            sys.__stdout__.write(f"[Doubao-probe] source panel failed: {type(exc).__name__}\n")
            sys.__stdout__.flush()
            return []

    async def _extract_citations(self, page, answer: str) -> List[Citation]:
        """Read every source entry of this answer before AI verification."""
        from .reference_collector import collect_all_references
        citations, metadata = await collect_all_references(page, "doubao", answer)
        page._geo_citation_collection = metadata
        return citations

    # ── Debug probe ────────────────────────────────────────────

    async def _probe_page(self, page) -> None:
        """Dump debug info about the current page state for offline analysis."""
        try:
            probe = await page.evaluate("""() => {
                // Buttons and interactive elements
                const buttons = [];
                document.querySelectorAll(
                    'button, [role="button"], div[tabindex], [contenteditable]'
                ).forEach(el => {
                    const text = (el.innerText || '').trim();
                    if (text && text.length <= 30) {
                        buttons.push({
                            tag: el.tagName,
                            text: text,
                            cls: (typeof el.className === 'string' ? el.className : '').slice(0, 120),
                            ce: el.getAttribute('contenteditable'),
                            role: el.getAttribute('role'),
                        });
                    }
                });
                // Key phrase counts
                const body_text = document.body.innerText || '';
                const keywords = {};
                ['联网搜索', '参考来源', '参考资料', '来源', '引用',
                 '搜索', 'Search', 'Source', 'Reference', 'citation'
                ].forEach(kw => {
                    keywords[kw] = (body_text.match(new RegExp(kw, 'gi')) || []).length;
                });
                // Count links
                const httpLinks = document.querySelectorAll('a[href^="http"]').length;
                return { buttons: buttons.slice(0, 40), keywords, httpLinks };
            }""")

            sys.__stdout__.write(
                f"[Doubao-probe] keywords={probe['keywords']} "
                f"httpLinks={probe['httpLinks']}\n"
            )
            sys.__stdout__.write("[Doubao-probe] buttons:\n")
            for b in probe["buttons"]:
                sys.__stdout__.write(f"  {b}\n")
            sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[Doubao-probe] failed: {type(e).__name__}: {e}\n")
            sys.__stdout__.flush()

        # Dump body HTML for first-run analysis
        try:
            import os
            dump_path = "/tmp/doubao_q1_body.html"
            if not os.path.exists(dump_path):
                body_html = await page.evaluate("() => document.body.innerHTML")
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(body_html)
                sys.__stdout__.write(
                    f"[Doubao-probe] dumped body HTML ({len(body_html)} bytes) -> {dump_path}\n"
                )
                sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[Doubao-probe] dump failed: {type(e).__name__}: {e}\n")
            sys.__stdout__.flush()
