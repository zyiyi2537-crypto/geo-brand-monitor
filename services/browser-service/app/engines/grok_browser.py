"""Grok browser adapter — automates grok.com.

Grok is xAI's AI chatbot with built-in web search. The Playwright adapter:
1. Navigates to the Grok chat interface
2. Detects redirect to X/Twitter SSO when no session
3. Dismisses popups and onboarding overlays
4. Submits queries and waits for streaming responses
5. Extracts answer text and multi-path citations

DOM notes (2026-04, Next.js):
  - Input: `textarea[placeholder*='What do you want to know']` (primary) or
    a `[contenteditable='true']` rich-text fallback
  - Submit: button[aria-label='Submit'] / button[type='submit'] / send arrow icon
  - Stop: button[aria-label='Stop'] visible while streaming
  - Response: streaming markdown in `.response-text` / `.markdown-body`
  - Citations: numbered source chips above the answer + expandable source cards
  - Network: `/api/rest/...` JSON responses carry citation arrays

Login: grok.com gates most queries behind X SSO. Without session, navigation
redirects to `x.com/i/flow/login` or `accounts.x.com`. We detect this and
return a clear error pointing at scripts/grok_login.py.

Cloudflare: x.com sits behind CF turnstile in some regions. Same detection
strategy as ChatGPT.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import List
from urllib.parse import urlparse

from ..browser import create_stealth_page, human_delay, save_page_session
from ..anti_detect import _pick_profile
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text, extract_citations_from_json


_GROK_BLOCK_HOSTS = (
    "grok.com",
    "x.com",
    "twitter.com",
    "t.co",
    "pscp.tv",
    "xai.com",
    "twimg.com",
    "abs.twimg.com",
    "pbs.twimg.com",
    "api.x.com",
    "api.twitter.com",
    "accounts.x.com",
    "cloudflare.com",
)

_LOGIN_URL_MARKERS = (
    "x.com/i/flow/login",
    "x.com/login",
    "accounts.x.com",
    "twitter.com/login",
    "/i/flow/login",
    "/login?",
)


class GrokBrowserAdapter(EngineAdapter):
    name = "Grok"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://grok.com/"

    async def is_available(self) -> bool:
        try:
            page, ctx = await create_stealth_page(
                "grok", locale="en-US", timezone_id="America/New_York"
            )
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            await human_delay(2, 3)
            current_url = page.url or ""
            if any(m in current_url for m in _LOGIN_URL_MARKERS):
                await ctx.close()
                return False
            logged_in = await page.locator(
                "textarea[placeholder*='know' i], "
                "textarea[placeholder], textarea, "
                "[contenteditable='true'], input[type='text']"
            ).count() > 0
            await ctx.close()
            return logged_in
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            profile = _pick_profile()
            page, ctx = await create_stealth_page(
                "grok", locale="en-US", timezone_id="America/New_York",
                record_video=self._record_video, profile=profile,
            )

            # Network capture: intercept API responses for structured citations
            captured_bodies: List[str] = []

            def _on_response(response):
                # response.text() 是 coroutine,同步 handler 里直接调会漏 await(body 成了
                # coroutine 对象,引用永远捕不到)。调度成 task 在事件循环里 await 读取 ——
                # 与 doubao/yuanbao 的 _capture_body 同思路。
                async def _grab():
                    try:
                        ct = (response.headers.get("content-type") or "").lower()
                        if "json" not in ct and "text" not in ct:
                            return
                        body = await response.text()
                        if len(body) > 500:
                            captured_bodies.append(body[:100000])
                    except Exception:
                        pass
                asyncio.create_task(_grab())

            page.on("response", _on_response)

            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            await human_delay(3, 5)

            # Login redirect check — fail fast with clear error
            current_url = page.url or ""
            if any(m in current_url for m in _LOGIN_URL_MARKERS):
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query,
                    error=(
                        "Not logged in — grok.com redirected to X/Twitter SSO. "
                        "Run scripts/grok_login.py and upload session via "
                        "PUT /sessions/grok."
                    ),
                )

            # Cloudflare challenge check
            cf_error = await self._check_cloudflare(page)
            if cf_error:
                await ctx.close()
                return EngineResult(engine=self.name, query=query, error=cf_error)

            # Dismiss popups (cookie banners, onboarding tours, upgrade modals)
            await self._dismiss_popups(page)

            # Find input — Grok 2026-04 uses a textarea with placeholder
            # "What do you want to know?", but the rollout sometimes ships a
            # contenteditable rich-text wrapper instead.
            input_el = await self._find_input(page)
            if input_el is None:
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query,
                    error="input not found — grok.com DOM may have changed",
                )
            await input_el.click()
            await human_delay(0.3, 0.6)
            try:
                await input_el.fill(query)
            except Exception:
                await input_el.type(query, delay=20)
            await human_delay(0.5, 1.5)

            # Submit
            submitted = False
            try:
                send_btn = page.locator(
                    "button[aria-label='Submit'], "
                    "button[aria-label='Send'], "
                    "button[aria-label*='send' i], "
                    "button[aria-label*='submit' i], "
                    "button[type='submit']"
                ).first
                if await send_btn.is_visible(timeout=2000):
                    await send_btn.click()
                    submitted = True
            except Exception:
                pass
            if not submitted:
                await page.keyboard.press("Enter")

            # Wait for response
            await human_delay(5, 8)
            await self._wait_for_response(page)

            await human_delay(1, 2)

            # Debug probe
            await self._probe_page(page)

            # Extract answer
            answer = await self._extract_answer(page)

            # Extract citations
            citations = await self._extract_citations(page, answer, captured_bodies)

            await save_page_session("grok", ctx)

            video_path = None
            if self._record_video:
                try:
                    from ..video_store import get_video_path
                    video_path = await get_video_path(page)
                except Exception:
                    pass

            await ctx.close()

            return EngineResult(
                engine=self.name,
                query=query,
                answer=answer,
                citations=citations,
                video_path=video_path,
            )
        except Exception as e:
            return EngineResult(engine=self.name, query=query, error=str(e))

    async def _check_cloudflare(self, page) -> str | None:
        """Detect Cloudflare turnstile / challenge pages. Returns error text if blocked."""
        try:
            blocked = await page.evaluate("""() => {
                for (const f of document.querySelectorAll('iframe')) {
                    const src = f.src || '';
                    if (src.includes('challenges.cloudflare.com')
                        || src.includes('cdn-cgi/challenge-platform')) {
                        const r = f.getBoundingClientRect();
                        if (r.width > 50 && r.height > 50) return 'turnstile';
                    }
                }
                const t = document.body.innerText || '';
                if (/Verify you are human|Checking your browser|Just a moment/i.test(t)
                    && t.length < 1500) {
                    return 'interstitial';
                }
                return '';
            }""")
            if blocked:
                return f"Blocked by Cloudflare ({blocked}). Try again later or rotate proxy/IP."
        except Exception:
            pass
        return None

    async def _find_input(self, page):
        """Locate Grok's chat input. Prefer the placeholder-matched textarea
        (most stable), fall back to generic textarea / contenteditable."""
        for sel in [
            "textarea[placeholder*='know' i]",
            "textarea[placeholder*='ask' i]",
            "textarea[placeholder]",
            "textarea.auto-resize",
            "textarea",
            "[contenteditable='true']",
            "input[type='text']",
        ]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    box = await el.bounding_box()
                    if box and box.get("height", 0) > 5:
                        return el
            except Exception:
                continue
        return None

    async def _extract_answer(self, page) -> str:
        """Extract the latest assistant response."""
        for sel in [
            ".response-content-markdown",
            ".markdown-body",
            ".response-text",
            "[class*='message-content']",
            "[class*='response-message']",
            "[class*='response']",
            ".markdown",
            "div.prose",
        ]:
            try:
                els = await page.locator(sel).all()
                if els:
                    text = await els[-1].inner_text()
                    if len(text.strip()) > 20:
                        return text
            except Exception:
                continue
        return ""

    async def _dismiss_popups(self, page) -> None:
        """Dismiss onboarding overlays, cookie banners, upgrade modals, etc."""
        try:
            for text in [
                "Accept", "Got it", "Dismiss", "Close", "Skip",
                "No thanks", "Not now", "Continue", "Start chatting",
                "Maybe later",
            ]:
                btn = page.locator(f"text={text}").first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await human_delay(0.3, 0.6)
        except Exception:
            pass

        try:
            for sel in [
                "[aria-label='Close']", "[aria-label='Dismiss']",
                "button.close", "[class*='close-button']",
                "[class*='dismiss']",
            ]:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await human_delay(0.3, 0.6)
        except Exception:
            pass

    async def _wait_for_response(self, page, timeout: int = 120) -> None:
        """Wait for Grok response completion."""
        # Strategy 1: stop / streaming indicator disappears.
        # Note: Grok's spinner/loading classes appear and disappear on every
        # interaction, so we anchor on the explicit stop button — broad
        # [class*="loading"] etc. would never go to zero on a busy UI.
        try:
            await page.wait_for_function(
                """() => {
                    const stopBtns = document.querySelectorAll(
                        'button[aria-label="Stop"], '
                        + 'button[aria-label="Cancel"], '
                        + 'button[aria-label*="stop" i]'
                    );
                    return stopBtns.length === 0;
                }""",
                timeout=timeout * 1000,
            )
        except Exception:
            pass

        # Strategy 2: text stability
        try:
            last_text = ""
            stable_count = 0
            for _ in range(30):
                await human_delay(1, 1)
                try:
                    els = await page.locator(
                        ".response-content-markdown, .markdown-body, "
                        ".response-text, [class*='message-content'], "
                        ".markdown, div.prose"
                    ).all()
                    if not els:
                        continue
                    current = await els[-1].inner_text()
                    if current == last_text and current.strip():
                        stable_count += 1
                        if stable_count >= 2:
                            return
                    else:
                        stable_count = 0
                        last_text = current
                except Exception:
                    continue
        except Exception:
            pass

    async def _probe_page(self, page) -> None:
        """Debug probe for offline analysis."""
        try:
            probe = await page.evaluate("""() => {
                const buttons = [];
                document.querySelectorAll('button, [role="button"]').forEach(el => {
                    const text = (el.innerText || '').trim();
                    if (text && text.length <= 30) {
                        buttons.push({
                            tag: el.tagName,
                            text: text,
                            cls: (typeof el.className === 'string' ? el.className : '').slice(0, 120),
                            aria: el.getAttribute('aria-label') || '',
                        });
                    }
                });
                const body_text = (document.body.innerText || '');
                const keywords = {};
                ['Sources', 'References', 'source', 'citation', 'Search',
                 '来源', '参考', 'Sign in', 'Verify you are human'].forEach(kw => {
                    keywords[kw] = (body_text.match(new RegExp(kw, 'gi')) || []).length;
                });
                const links = document.querySelectorAll('a[href^="http"]');
                const url = location.href;
                return { buttons: buttons.slice(0, 30), keywords, linkCount: links.length, url };
            }""")
            sys.__stdout__.write(
                f"[Grok-probe] url={probe['url']} keywords={probe['keywords']} links={probe['linkCount']}\n"
            )
            for b in probe['buttons']:
                sys.__stdout__.write(
                    f"  btn: {b['tag']} text={b['text']!r} aria={b['aria']!r}\n"
                )
            sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[Grok-probe] failed: {e}\n")
            sys.__stdout__.flush()

    async def _extract_citations(
        self, page, answer: str, captured_bodies: List[str]
    ) -> List[Citation]:
        """Multi-path citation extraction."""
        citations: List[Citation] = []
        seen: set[str] = set()

        def _add(url: str, title: str = "", snippet: str = "", position: int = 0) -> None:
            url = url.strip().rstrip("\\").rstrip(")")
            parsed = urlparse(url)
            host = parsed.netloc.replace("www.", "")
            if not host or any(bh in host for bh in _GROK_BLOCK_HOSTS):
                return
            if url in seen:
                return
            seen.add(url)
            citations.append(Citation.from_url(url, title=title, snippet=snippet, position=position))

        # Path 1: Parse structured citations from captured JSON
        for body in captured_bodies:
            try:
                data = json.loads(body)
                for c in extract_citations_from_json(data, _GROK_BLOCK_HOSTS):
                    if c.url not in seen:
                        seen.add(c.url)
                        citations.append(Citation.from_url(
                            c.url, title=c.title, snippet=c.snippet,
                            position=len(citations) + 1,
                        ))
            except Exception:
                for m in re.finditer(r'https?://[^\s"\'<>\]\),}]+', body):
                    _add(m.group(0).rstrip("\\"), position=len(citations) + 1)

        # Path 2: Source/citation cards
        try:
            source_links = await page.locator(
                "[class*='source'] a[href^='http'], "
                "[class*='Source'] a[href^='http'], "
                "[class*='citation'] a[href^='http'], "
                "[class*='reference'] a[href^='http'], "
                "[class*='attribution'] a[href^='http']"
            ).all()
            for link in source_links:
                href = await link.get_attribute("href") or ""
                title = await link.inner_text()
                _add(href, title=title.strip(), position=len(citations) + 1)
        except Exception:
            pass

        # Path 3: Inline links in response container
        try:
            response_containers = await page.locator(
                ".response-content-markdown, .markdown-body, "
                ".response-text, [class*='message-content'], "
                ".markdown, div.prose"
            ).all()
            for container in response_containers[-1:]:
                links = await container.locator("a[href^='http']").all()
                for link in links:
                    href = await link.get_attribute("href") or ""
                    title = await link.inner_text()
                    _add(href, title=title.strip(), position=len(citations) + 1)
        except Exception:
            pass

        # Path 4: Regex fallback from answer text
        if not citations:
            urls = extract_urls_from_text(answer)
            for i, u in enumerate(urls):
                _add(u, position=i + 1)

        return citations
