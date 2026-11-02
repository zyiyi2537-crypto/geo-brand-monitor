"""Microsoft Copilot browser adapter — automates copilot.microsoft.com.

Copilot (Bing Chat) is Microsoft's AI assistant powered by GPT-4 + Bing search.
The Playwright adapter handles:
1. Navigating to the Copilot chat interface
2. Dismissing consent dialogs and CAPTCHA detection
3. Submitting queries (anonymous or authenticated)
4. Extracting answer text and multi-path citations

DOM notes (2026-04, React):
  - Input: textarea or input with placeholder "Ask me anything"
  - Submit: Enter key or send/arrow button
  - Response: streaming markdown in chat bubble
  - Citations: numbered reference cards with source links, superscript numbers
  - Network: Bing API responses contain structured citation data

Special: Copilot works WITHOUT login (anonymous mode with limits).
Full features require a Microsoft account session.
CAPTCHA (FunCaptcha) may appear — detected and returned as error.
"""

from __future__ import annotations

import json
import re
import sys
from typing import List
from urllib.parse import urlparse

from ..browser import create_stealth_page, human_delay, save_page_session
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text, extract_citations_from_json


_COPILOT_BLOCK_HOSTS = (
    "microsoft.com",
    "bing.com",
    "msn.com",
    "live.com",
    "skype.com",
    "azure.com",
    "cloudapp.net",
    "bingapis.com",
    "microsoftstore.com",
    "office.com",
    "onenote.com",
    "sharepoint.com",
    "outlook.com",
    "azureedge.net",
    "mmg-fashion.microsoft.com",
    "trouter.skype.com",
)


class CopilotBrowserAdapter(EngineAdapter):
    name = "Copilot"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://copilot.microsoft.com/"

    async def is_available(self) -> bool:
        try:
            page, ctx = await create_stealth_page(
                "copilot", locale="en-US", timezone_id="America/New_York"
            )
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            await human_delay(2, 3)
            # Copilot works without login — just check if input is visible
            has_input = await page.locator(
                "textarea, input[type='text'], "
                "[contenteditable='true'], "
                "textarea[placeholder*='Ask' i]"
            ).count() > 0
            await ctx.close()
            return has_input
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            page, ctx = await create_stealth_page(
                "copilot", locale="en-US", timezone_id="America/New_York",
                record_video=self._record_video,
            )

            # Network capture: intercept API responses for structured citations
            captured_bodies: List[str] = []

            def _on_response(response):
                try:
                    ct = (response.headers.get("content-type") or "").lower()
                    if "json" not in ct and "text" not in ct:
                        return
                    body = response.text()
                    if len(body) > 500:
                        captured_bodies.append(body[:100000])
                except Exception:
                    pass

            page.on("response", _on_response)

            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            await human_delay(3, 5)

            # Dismiss popups and consent dialogs
            await self._dismiss_popups(page)

            # Check for CAPTCHA
            captcha_error = await self._check_captcha(page)
            if captcha_error:
                await save_page_session("copilot", ctx)
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query, error=captcha_error
                )

            # Type query
            textarea = page.locator(
                "textarea[placeholder*='Ask' i], "
                "textarea, "
                "input[type='text'], "
                "[contenteditable='true']"
            ).first
            await textarea.click()
            await human_delay(0.3, 0.6)
            await textarea.fill(query)
            await human_delay(0.5, 1.5)

            # Submit
            try:
                send_btn = page.locator(
                    "button[aria-label='Send'], "
                    "button[aria-label*='send' i], "
                    "button[aria-label='Submit'], "
                    "[class*='send-button'], "
                    "button[type='submit']"
                ).first
                if await send_btn.is_visible(timeout=2000):
                    await send_btn.click()
                else:
                    await page.keyboard.press("Enter")
            except Exception:
                await page.keyboard.press("Enter")

            # Wait for response
            await human_delay(5, 8)

            # Check CAPTCHA again after submit
            captcha_error = await self._check_captcha(page)
            if captcha_error:
                await save_page_session("copilot", ctx)
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query, error=captcha_error
                )

            await self._wait_for_response(page)
            await human_delay(1, 2)

            # Debug probe
            await self._probe_page(page)

            # Extract answer
            answer = ""
            for sel in [
                ".markdown",
                "[class*='response']",
                "[class*='message-content']",
                "[class*='answer']",
                "div.prose",
            ]:
                try:
                    els = await page.locator(sel).all()
                    if els:
                        text = await els[-1].inner_text()
                        if len(text.strip()) > 20:
                            answer = text
                            break
                except Exception:
                    continue

            # Extract citations
            citations = await self._extract_citations(page, answer, captured_bodies)

            await save_page_session("copilot", ctx)

            # Capture video path before closing context
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

    async def _dismiss_popups(self, page) -> None:
        """Dismiss consent dialogs, cookie banners, etc."""
        try:
            for text in [
                "Accept", "Accept all", "I agree", "Got it", "Dismiss",
                "Close", "No thanks", "Not now", "Continue", "Skip",
                "Start chatting",
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
                "[class*='dismiss']", "[class*='accept']",
            ]:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await human_delay(0.3, 0.6)
        except Exception:
            pass

    async def _check_captcha(self, page) -> str | None:
        """Detect CAPTCHA challenges. Returns error string if found."""
        try:
            captcha_selectors = [
                "[class*='captcha']",
                "[id*='captcha']",
                "iframe[src*='captcha']",
                "iframe[src*='challenge']",
                "[class*='challenge']",
                "#captcha",
            ]
            for sel in captcha_selectors:
                if await page.locator(sel).count() > 0:
                    return "CAPTCHA detected — please complete verification in a headed browser"
        except Exception:
            pass
        return None

    async def _wait_for_response(self, page, timeout: int = 120) -> None:
        """Wait for Copilot response completion."""
        # Strategy 1: stop/cancel button disappears
        try:
            await page.wait_for_function(
                """() => {
                    const stopBtns = document.querySelectorAll(
                        'button[aria-label="Stop"], button[aria-label="Cancel"], '
                        + '[class*="stop"], [class*="cancel"]'
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
                        ".markdown, [class*='response'], "
                        "[class*='message-content'], div.prose"
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
                 'Learn more', '来源', '参考'].forEach(kw => {
                    keywords[kw] = (body_text.match(new RegExp(kw, 'gi')) || []).length;
                });
                const links = document.querySelectorAll('a[href^="http"]');
                return { buttons: buttons.slice(0, 30), keywords, linkCount: links.length };
            }""")
            sys.__stdout__.write(
                f"[Copilot-probe] keywords={probe['keywords']} links={probe['linkCount']}\n"
            )
            for b in probe['buttons']:
                sys.__stdout__.write(
                    f"  btn: {b['tag']} text={b['text']!r} aria={b['aria']!r}\n"
                )
            sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[Copilot-probe] failed: {e}\n")
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
            if not host or any(bh in host for bh in _COPILOT_BLOCK_HOSTS):
                return
            if url in seen:
                return
            seen.add(url)
            citations.append(Citation.from_url(url, title=title, snippet=snippet, position=position))

        # Path 1: Parse structured citations from captured JSON
        for body in captured_bodies:
            try:
                data = json.loads(body)
                for c in extract_citations_from_json(data, _COPILOT_BLOCK_HOSTS):
                    if c.url not in seen:
                        seen.add(c.url)
                        citations.append(Citation.from_url(
                            c.url, title=c.title, snippet=c.snippet,
                            position=len(citations) + 1,
                        ))
            except Exception:
                for m in re.finditer(r'https?://[^\s"\'<>\]\),}]+', body):
                    _add(m.group(0).rstrip("\\"), position=len(citations) + 1)

        # Path 2: Reference/source cards (Copilot's numbered citation cards)
        try:
            source_links = await page.locator(
                "[class*='source'] a[href^='http'], "
                "[class*='Source'] a[href^='http'], "
                "[class*='citation'] a[href^='http'], "
                "[class*='reference'] a[href^='http'], "
                "[class*='ref-card'] a[href^='http'], "
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
                ".markdown, [class*='response'], "
                "[class*='message-content'], div.prose"
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
