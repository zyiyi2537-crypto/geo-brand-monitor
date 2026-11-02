"""ChatGPT browser adapter — automates chatgpt.com.

OpenRouter's :online suffix is unreliable for citation extraction. The web UI
with Search mode provides accurate, structured source links.

DOM notes (2026-04, Next.js + React):
  - Input: textarea#prompt-textarea (still works) OR contenteditable#prompt-textarea
  - Submit: button[data-testid="send-button"] / button[aria-label="Send prompt"]
  - Stop: button[data-testid="stop-button"] / button[aria-label="Stop streaming"]
  - Web search toggle: button[aria-label*="Search" i] in the composer
  - Response: div[data-message-author-role="assistant"] contains markdown
  - Citations: source cards at bottom + inline <a href> in response,
               also a "Sources" panel that opens on click
  - Network: SSE/JSON API responses contain structured citation data

Login: redirects to auth.openai.com when no session. We detect this and
return a clear error so callers know to run scripts/chatgpt_login.py.

Cloudflare: chatgpt.com sits behind a Cloudflare challenge. If we land on
the challenge page, we report it explicitly rather than hanging.
"""

from __future__ import annotations

import json
import re
import sys
from typing import List
from urllib.parse import urlparse

from ..browser import create_stealth_page, create_persistent_chrome_context, human_delay, save_page_session
from ..anti_detect import _pick_profile
from ..session_store import load_engine_profile
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text, extract_citations_from_json


_CHATGPT_BLOCK_HOSTS = (
    "chatgpt.com",
    "openai.com",
    "oaistatic.com",
    "oaiusercontent.com",
    "auth0.openai.com",
    "auth.openai.com",
    "cdn.oaistatic.com",
    "cdn.auth0.com",
    "cloudflare.com",
)

_LOGIN_URL_MARKERS = (
    "auth.openai.com",
    "auth0.openai.com",
    "/auth/login",
    "/login?",
)


class ChatGPTBrowserAdapter(EngineAdapter):
    name = "ChatGPT"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://chatgpt.com/"

    async def is_available(self) -> bool:
        try:
            profile = load_engine_profile("chatgpt")
            if not profile:
                return False
            page, ctx = await create_persistent_chrome_context(
                "chatgpt", profile=profile,
                locale="en-US", timezone_id="America/New_York",
            )
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            await human_delay(2, 3)
            current_url = page.url or ""
            if any(m in current_url for m in _LOGIN_URL_MARKERS):
                pw = getattr(page, "_pw_ref", None)
                br = getattr(page, "_headed_browser", None)
                await ctx.close()
                if br:
                    try:
                        await br.close()
                    except Exception:
                        pass
                if pw:
                    await pw.stop()
                return False
            logged_in = await page.locator(
                "#prompt-textarea, textarea, [data-testid='prompt-textarea'], "
                "[contenteditable='true']"
            ).count() > 0
            pw = getattr(page, "_pw_ref", None)
            br = getattr(page, "_headed_browser", None)
            await ctx.close()
            if br:
                try:
                    await br.close()
                except Exception:
                    pass
            if pw:
                await pw.stop()
            return logged_in
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            # Load the profile saved during login so the fingerprint matches
            # the cf_clearance cookie. Without this, CF invalidates the session.
            profile = load_engine_profile("chatgpt")
            if not profile:
                return EngineResult(
                    engine=self.name, query=query,
                    error=(
                        "No saved profile. Run scripts/chatgpt_login.py and "
                        "upload session+profile via PUT /sessions/chatgpt."
                    ),
                )
            page, ctx = await create_persistent_chrome_context(
                "chatgpt", profile=profile,
                locale="en-US", timezone_id="America/New_York",
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
            await human_delay(2, 4)

            # Login redirect check — fail fast with clear error
            current_url = page.url or ""
            if any(m in current_url for m in _LOGIN_URL_MARKERS):
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query,
                    error=(
                        "Not logged in — chatgpt.com redirected to login. "
                        "Run scripts/chatgpt_login.py and upload session via "
                        "PUT /sessions/chatgpt."
                    ),
                )

            # Cloudflare challenge check
            cf_error = await self._check_cloudflare(page)
            if cf_error:
                await ctx.close()
                return EngineResult(engine=self.name, query=query, error=cf_error)

            # Dismiss popups/banners
            await self._dismiss_popups(page)

            # Enable web search mode (gives citations). Best-effort — if the
            # button isn't present, the model still answers but without sources.
            await self._enable_search_mode(page)

            # Type the query
            textarea = await self._find_input(page)
            if textarea is None:
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query,
                    error="input not found — chatgpt.com DOM may have changed",
                )
            await textarea.click()
            await human_delay(0.3, 0.6)
            # contenteditable doesn't accept .fill() reliably — use type() as fallback
            try:
                await textarea.fill(query)
            except Exception:
                await textarea.type(query, delay=20)
            await human_delay(0.5, 1.5)

            # Submit
            try:
                send_btn = page.locator(
                    "[data-testid='send-button'], "
                    "button[aria-label='Send prompt'], "
                    "button[aria-label='Send'], "
                    "button[aria-label='发送']"
                ).first
                if await send_btn.is_visible(timeout=2000):
                    await send_btn.click()
                else:
                    await page.keyboard.press("Enter")
            except Exception:
                await page.keyboard.press("Enter")

            # Wait for response to finish — dual strategy
            await human_delay(5, 8)

            # Strategy 1: wait for stop button to disappear
            try:
                await page.wait_for_function(
                    """() => {
                        const stopBtn = document.querySelector(
                            '[data-testid="stop-button"], '
                            + 'button[aria-label="Stop streaming"], '
                            + 'button[aria-label="Stop generating"], '
                            + 'button[aria-label="Stop"]'
                        );
                        return !stopBtn;
                    }""",
                    timeout=120000,
                )
            except Exception:
                pass

            # Strategy 2: wait for answer text to stabilize
            await self._wait_for_stable_text(page)

            await human_delay(1, 2)

            # Debug probe
            await self._probe_page(page)

            # Extract answer
            answer = ""
            try:
                msg_els = await page.locator(
                    "[data-message-author-role='assistant'] .markdown, "
                    "[data-message-author-role='assistant'], "
                    ".markdown"
                ).all()
                if msg_els:
                    answer = await msg_els[-1].inner_text()
            except Exception:
                pass

            # Extract citations
            citations = await self._extract_citations(page, answer, captured_bodies)

            await save_page_session("chatgpt", ctx)

            video_path = None
            if self._record_video:
                try:
                    from ..video_store import get_video_path
                    video_path = await get_video_path(page)
                except Exception:
                    pass

            pw = getattr(page, "_pw_ref", None)
            br = getattr(page, "_headed_browser", None)
            await ctx.close()
            if br:
                try:
                    await br.close()
                except Exception:
                    pass
            if pw:
                await pw.stop()

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
                // Cloudflare challenge iframe
                for (const f of document.querySelectorAll('iframe')) {
                    const src = f.src || '';
                    if (src.includes('challenges.cloudflare.com')
                        || src.includes('cdn-cgi/challenge-platform')) {
                        const r = f.getBoundingClientRect();
                        if (r.width > 50 && r.height > 50) return 'turnstile';
                    }
                }
                // Cloudflare full-page interstitial
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
        """Locate the chat input. ChatGPT's prompt-textarea may be a textarea
        OR a contenteditable element depending on the rollout."""
        for sel in [
            "#prompt-textarea",
            "[data-testid='prompt-textarea']",
            "textarea[placeholder*='Message' i]",
            "[contenteditable='true']",
            "textarea",
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

    async def _enable_search_mode(self, page) -> None:
        """Click the Search/Web button in the composer if present. Citations
        only appear when web search is on; without it ChatGPT answers from
        the model alone."""
        # Strategy 1: direct aria-label match — only click if not already on
        for sel in [
            "button[aria-label='Search'][aria-pressed='false']",
            "button[aria-label='Search the web'][aria-pressed='false']",
            "button[aria-label*='earch' i][aria-pressed='false']",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    await human_delay(0.3, 0.6)
                    return
            except Exception:
                continue

        # Strategy 2: enumerate composer buttons by text
        try:
            clicked = await page.evaluate("""() => {
                const btns = document.querySelectorAll('button, [role="button"]');
                for (const b of btns) {
                    const label = (b.getAttribute('aria-label') || '').toLowerCase();
                    const txt = (b.innerText || '').trim().toLowerCase();
                    if ((label === 'search' || label === 'search the web'
                         || txt === 'search' || txt === 'web')
                        && b.getAttribute('aria-pressed') !== 'true') {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")
            if clicked:
                await human_delay(0.3, 0.6)
        except Exception:
            pass

    async def _dismiss_popups(self, page) -> None:
        """Dismiss consent banners, upgrade prompts, etc."""
        try:
            for text in [
                "OK", "Accept", "Dismiss", "Got it", "Close", "Stay logged out",
                "Continue", "暂不", "以后再说", "关闭",
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
                "button[data-testid='close-button']",
                "button[data-testid='dismiss-button']",
            ]:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await human_delay(0.3, 0.6)
        except Exception:
            pass

    async def _wait_for_stable_text(self, page, max_wait: int = 30) -> None:
        """Poll answer text until stable for 2+ seconds."""
        try:
            last_text = ""
            stable_count = 0
            for _ in range(max_wait):
                await human_delay(1, 1)
                try:
                    msg_els = await page.locator(
                        "[data-message-author-role='assistant'], .markdown"
                    ).all()
                    if not msg_els:
                        continue
                    current = await msg_els[-1].inner_text()
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
        """Debug probe: dump button state and keyword counts."""
        try:
            probe = await page.evaluate("""() => {
                const buttons = [];
                document.querySelectorAll('button, [role="button"]').forEach(el => {
                    const text = (el.innerText || '').trim();
                    if (text && text.length <= 30) {
                        buttons.push({
                            tag: el.tagName,
                            text: text,
                            testid: el.getAttribute('data-testid') || '',
                            aria: el.getAttribute('aria-label') || '',
                            cls: (typeof el.className === 'string' ? el.className : '').slice(0, 100),
                        });
                    }
                });
                const body_text = (document.body.innerText || '');
                const keywords = {};
                ['Sources', 'References', 'Browse', 'Search', 'source', 'citation',
                 '来源', '参考', '引用', 'Verify you are human'].forEach(kw => {
                    keywords[kw] = (body_text.match(new RegExp(kw, 'gi')) || []).length;
                });
                const url = location.href;
                return { buttons: buttons.slice(0, 30), keywords, url };
            }""")
            sys.__stdout__.write(
                f"[ChatGPT-probe] url={probe['url']} keywords={probe['keywords']}\n"
            )
            for b in probe['buttons']:
                sys.__stdout__.write(
                    f"  btn: text={b['text']!r} testid={b['testid']!r} aria={b['aria']!r}\n"
                )
            sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[ChatGPT-probe] failed: {e}\n")
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
            if not host or any(bh in host for bh in _CHATGPT_BLOCK_HOSTS):
                return
            if url in seen:
                return
            seen.add(url)
            citations.append(Citation.from_url(url, title=title, snippet=snippet, position=position))

        # Path 1: Parse structured citations from captured JSON
        for body in captured_bodies:
            try:
                data = json.loads(body)
                for c in extract_citations_from_json(data, _CHATGPT_BLOCK_HOSTS):
                    if c.url not in seen:
                        seen.add(c.url)
                        citations.append(Citation.from_url(
                            c.url, title=c.title, snippet=c.snippet,
                            position=len(citations) + 1,
                        ))
            except Exception:
                # Fallback: regex extract URLs from raw body
                for m in re.finditer(r'https?://[^\s"\'<>\]\),}]+', body):
                    _add(m.group(0).rstrip("\\"), position=len(citations) + 1)

        # Path 2: Source/reference section links
        try:
            source_links = await page.locator(
                "[class*='source'] a[href^='http'], "
                "[class*='Source'] a[href^='http'], "
                "[class*='reference'] a[href^='http'], "
                "[class*='citation'] a[href^='http']"
            ).all()
            for link in source_links:
                href = await link.get_attribute("href") or ""
                title = await link.inner_text()
                _add(href, title=title.strip(), position=len(citations) + 1)
        except Exception:
            pass

        # Path 3: Inline <a href> in the assistant message
        try:
            inline_links = await page.locator(
                "[data-message-author-role='assistant'] a[href^='http'], "
                ".markdown a[href^='http']"
            ).all()
            for link in inline_links:
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
