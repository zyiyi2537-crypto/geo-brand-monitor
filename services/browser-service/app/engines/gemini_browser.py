"""Google Gemini browser adapter — automates gemini.google.com.

Gemini's web UI provides rich, web-search-backed answers with structured
source citations. The Playwright adapter handles:
1. Navigating to the Gemini chat interface
2. Detecting redirect to accounts.google.com when no session
3. Dismissing popups and consent dialogs
4. Submitting queries (web search is always-on for Gemini)
5. Extracting answer text and multi-path citations

DOM notes (2026-04, Angular + Material):
  - Input: `.ql-editor[contenteditable='true']` (Quill rich-text editor) is
    the PRIMARY input, NOT a textarea. Older fallback is a textarea with
    aria-label containing "Enter a prompt".
  - Submit: button[aria-label='Send message'] / button[mattooltip='Send']
  - Stop: button[aria-label='Stop response']
  - Response: streaming markdown in `<message-content>` / `.model-response-text`
  - Citations: `<sources-list>` cards / `.source-attributions` with <a href>
  - Network: BatchExecute calls to `/_/BardChatUi/data/...` carry citation JSON

Login: when no Google session exists, gemini.google.com/app redirects to
`accounts.google.com`. We detect this and return a clear error.
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


_GEMINI_BLOCK_HOSTS = (
    "gemini.google.com",
    "google.com",
    "gstatic.com",
    "googleapis.com",
    "google-analytics.com",
    "googletagmanager.com",
    "googlesyndication.com",
    "googleadservices.com",
    "doubleclick.net",
    "recaptcha.net",
    "accounts.google.com",
    "googleusercontent.com",
)

_LOGIN_URL_MARKERS = (
    "accounts.google.com",
    "/signin/",
    "ServiceLogin",
)


class GeminiBrowserAdapter(EngineAdapter):
    name = "Gemini"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://gemini.google.com/app"

    async def is_available(self) -> bool:
        try:
            page, ctx = await create_stealth_page(
                "gemini", locale="en-US", timezone_id="America/New_York"
            )
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            await human_delay(2, 3)
            current_url = page.url or ""
            if any(m in current_url for m in _LOGIN_URL_MARKERS):
                await ctx.close()
                return False
            logged_in = await page.locator(
                ".ql-editor[contenteditable='true'], "
                "rich-textarea [contenteditable='true'], "
                "textarea[aria-label*='prompt' i], "
                "textarea[aria-label*='Enter' i], "
                "textarea, [contenteditable='true']"
            ).count() > 0
            await ctx.close()
            return logged_in
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            profile = _pick_profile()
            page, ctx = await create_stealth_page(
                "gemini", locale="en-US", timezone_id="America/New_York",
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

            # Login redirect check
            current_url = page.url or ""
            if any(m in current_url for m in _LOGIN_URL_MARKERS):
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query,
                    error=(
                        "Not logged in — gemini.google.com redirected to Google sign-in. "
                        "Run scripts/gemini_login.py and upload session via "
                        "PUT /sessions/gemini."
                    ),
                )

            # Dismiss popups (consent, tour overlay, etc.)
            await self._dismiss_popups(page)

            # Start new chat if continuation dialog appears
            try:
                new_chat = page.locator(
                    "text=New chat, text=Start new chat, text=新建对话"
                ).first
                if await new_chat.is_visible(timeout=2000):
                    await new_chat.click()
                    await human_delay(1, 2)
            except Exception:
                pass

            # Find input — prefer Quill .ql-editor (current Gemini), fall back
            # to textarea (older rollouts).
            input_el = await self._find_input(page)
            if input_el is None:
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query,
                    error="input not found — gemini.google.com DOM may have changed",
                )
            await input_el.click()
            await human_delay(0.3, 0.6)
            # contenteditable rejects .fill(); use type() with small delay so the
            # Quill editor's input handlers register the keystrokes.
            try:
                await input_el.fill(query)
            except Exception:
                await input_el.type(query, delay=20)
            await human_delay(0.5, 1.5)

            # Submit — try send button first, fallback to Enter
            submitted = False
            try:
                send_btn = page.locator(
                    "button[aria-label='Send message'], "
                    "button[mattooltip='Send'], "
                    "button[aria-label='Send'], "
                    "mat-icon-button[aria-label='Send'], "
                    "button[aria-label*='send' i]"
                ).first
                if await send_btn.is_visible(timeout=2000):
                    await send_btn.click()
                    submitted = True
            except Exception:
                pass
            if not submitted:
                await page.keyboard.press("Enter")

            # Wait for response to finish
            await human_delay(5, 8)
            await self._wait_for_response(page)

            await human_delay(1, 2)

            # Debug probe
            await self._probe_page(page)

            # Extract answer
            answer = await self._extract_answer(page)

            # Extract citations
            citations = await self._extract_citations(page, answer, captured_bodies)

            await save_page_session("gemini", ctx)

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

    async def _find_input(self, page):
        """Locate Gemini's chat input. Prefer the Quill editor that the
        2026-era Gemini ships; older rollouts had a plain textarea."""
        for sel in [
            ".ql-editor[contenteditable='true']",
            "rich-textarea [contenteditable='true']",
            "textarea[aria-label*='prompt' i]",
            "textarea[aria-label*='Enter' i]",
            ".input-area-container textarea",
            "textarea",
            "[contenteditable='true']",
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
        """Extract the answer text from the latest assistant response."""
        for sel in [
            "message-content",
            ".model-response-text",
            ".message-content",
            ".markdown-container",
            "model-response",
            ".response-container",
        ]:
            try:
                els = await page.locator(sel).all()
                if els:
                    text = await els[-1].inner_text()
                    if text.strip():
                        return text
            except Exception:
                continue

        # Fallback: last large text block in the chat
        try:
            responses = await page.locator(
                "[class*='response'], [class*='message'], .markdown"
            ).all()
            for el in reversed(responses):
                text = await el.inner_text()
                if len(text.strip()) > 50:
                    return text
        except Exception:
            pass
        return ""

    async def _dismiss_popups(self, page) -> None:
        """Dismiss consent banners, upgrade prompts, etc."""
        try:
            for text in [
                "Accept all", "I agree", "Got it", "Dismiss", "Close",
                "No thanks", "Not now", "Maybe later", "Skip",
                "Continue",
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
                "button.close", "[aria-label='Close dialog']",
            ]:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await human_delay(0.3, 0.6)
        except Exception:
            pass

    async def _wait_for_response(self, page, timeout: int = 120) -> None:
        """Wait for Gemini response to finish — stop button + stability."""
        # Strategy 1: wait for stop/cancel button to disappear
        try:
            await page.wait_for_function(
                """() => {
                    const stopBtns = document.querySelectorAll(
                        'button[aria-label="Stop response"], '
                        + 'button[aria-label="Stop"], '
                        + 'button[aria-label="Cancel"], '
                        + '[class*="stop-button"]'
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
                        "message-content, .model-response-text, "
                        ".message-content, [class*='response'], .markdown"
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
                 '来源', '参考', '引用', 'Learn more', 'Show drafts'].forEach(kw => {
                    keywords[kw] = (body_text.match(new RegExp(kw, 'gi')) || []).length;
                });
                const links = document.querySelectorAll('a[href^="http"]');
                const linkCount = links.length;
                const url = location.href;
                return { buttons: buttons.slice(0, 30), keywords, linkCount, url };
            }""")
            sys.__stdout__.write(
                f"[Gemini-probe] url={probe['url']} keywords={probe['keywords']} links={probe['linkCount']}\n"
            )
            for b in probe['buttons']:
                sys.__stdout__.write(
                    f"  btn: {b['tag']} text={b['text']!r} aria={b['aria']!r}\n"
                )
            sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[Gemini-probe] failed: {e}\n")
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
            if not host or any(bh in host for bh in _GEMINI_BLOCK_HOSTS):
                return
            if url in seen:
                return
            seen.add(url)
            citations.append(Citation.from_url(url, title=title, snippet=snippet, position=position))

        # Path 1: Parse structured citations from captured JSON
        for body in captured_bodies:
            try:
                data = json.loads(body)
                for c in extract_citations_from_json(data, _GEMINI_BLOCK_HOSTS):
                    if c.url not in seen:
                        seen.add(c.url)
                        citations.append(Citation.from_url(
                            c.url, title=c.title, snippet=c.snippet,
                            position=len(citations) + 1,
                        ))
            except Exception:
                for m in re.finditer(r'https?://[^\s"\'<>\]\),}]+', body):
                    _add(m.group(0).rstrip("\\"), position=len(citations) + 1)

        # Path 2: Sources/source-attributions cards
        try:
            source_links = await page.locator(
                "sources-list a[href^='http'], "
                ".source-attributions a[href^='http'], "
                ".source-attribution a[href^='http'], "
                "[class*='source'] a[href^='http'], "
                "[class*='Source'] a[href^='http'], "
                "[class*='citation'] a[href^='http'], "
                "[class*='reference'] a[href^='http']"
            ).all()
            for link in source_links:
                href = await link.get_attribute("href") or ""
                title = await link.inner_text()
                _add(href, title=title.strip(), position=len(citations) + 1)
        except Exception:
            pass

        # Path 3: Inline links in the response container
        try:
            response_containers = await page.locator(
                "message-content, .model-response-text, "
                ".message-content, [class*='response'], .markdown"
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
