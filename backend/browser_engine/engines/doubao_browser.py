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
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


def _is_xvfb_display() -> bool:
    """Check if current DISPLAY was set by our Xvfb module."""
    import os
    display = os.environ.get("DISPLAY", "")
    return display.startswith(":") and display.lstrip(":").isdigit()


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
        try:
            page, ctx = await create_stealth_page("doubao")
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            await human_delay(2, 3)
            logged_in = await page.locator(
                "textarea.semi-input-textarea, textarea[placeholder='发消息...'], "
                "textarea[placeholder]"
            ).count() > 0
            await ctx.close()
            return logged_in
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            page, ctx = await create_stealth_page("doubao", record_video=self._record_video)
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

            # Brief natural interaction — light mouse movement only
            await simulate_browsing(page, duration=random.uniform(1.5, 2.5))

            # Dismiss popups (cookie consent, upgrade prompts, etc.)
            await self._dismiss_popups(page)

            # Enable web search mode (深入研究 or 超能模式)
            await self._enable_web_search(page)

            # Find and fill the input
            input_el = await self._find_input(page)
            if input_el is None:
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query, error="input not found"
                )

            # Click input with human-like mouse movement
            box = await input_el.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await human_click(page, cx, cy)
            else:
                await input_el.click()
            await human_delay(0.3, 0.5)

            # Fill input — try fill() first (faster, less detectable than per-char typing)
            try:
                await input_el.fill(query)
            except Exception:
                for ch in query:
                    await page.keyboard.type(ch, delay=random.randint(40, 180))
            await human_delay(0.5, 1.5)

            # Submit — press Enter with natural timing
            await asyncio.sleep(random.uniform(0.3, 0.8))
            await page.keyboard.press("Enter")
            await human_delay(1, 2)

            try:
                send_btn = page.locator("[data-testid='send-button'], button[aria-label='发送'], button[aria-label='Send']").first
                if await send_btn.is_visible(timeout=1000):
                    await send_btn.click()
            except Exception:
                pass

            # Check for CAPTCHA after submit
            await human_delay(3, 5)
            if await self._check_captcha(page):
                import os
                # Save screenshot for diagnosis
                screenshot_dir = "/tmp/doubao_captcha"
                os.makedirs(screenshot_dir, exist_ok=True)
                try:
                    ts = int(asyncio.get_event_loop().time())
                    await page.screenshot(path=f"{screenshot_dir}/captcha_{ts}.png")
                    sys.__stdout__.write(f"[Doubao] CAPTCHA screenshot saved to {screenshot_dir}/captcha_{ts}.png\n")
                except Exception:
                    pass

                # Auto-start Xvfb if no display available
                if not os.environ.get("DISPLAY"):
                    from ..xvfb import start_xvfb
                    if start_xvfb():
                        sys.__stdout__.write("[Doubao] Xvfb virtual display started for CAPTCHA handling\n")
                    else:
                        sys.__stdout__.write("[Doubao] Xvfb not available — cannot auto-handle CAPTCHA\n")
                    sys.__stdout__.flush()

                # Explicit opt-out
                headed_disabled = os.environ.get("DOUBAO_HEADED") == "0"

                # Headed mode: launch visible browser for CAPTCHA handling
                if not headed_disabled and os.environ.get("DISPLAY"):
                    sys.__stdout__.write(
                        "[Doubao] CAPTCHA detected — launching headed browser "
                        "(auto via Xvfb or manual via DISPLAY)...\n"
                    )
                    sys.__stdout__.flush()

                    await save_page_session("doubao", ctx)
                    await ctx.close()

                    page, ctx = await create_headed_page("doubao")
                    headed_browser = getattr(page, '_headed_browser', None)
                    headed_pw = getattr(page, '_pw_ref', None)

                    page.on("response", _on_response)

                    await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
                    await human_delay(3, 5)

                    # With Xvfb: CAPTCHA may auto-resolve or need the wait loop
                    # With real DISPLAY: user can complete manually
                    is_xvfb = _is_xvfb_display()
                    wait_timeout = 60 if is_xvfb else 180

                    if is_xvfb:
                        sys.__stdout__.write(
                            f"[Doubao] Xvfb mode — waiting up to {wait_timeout}s "
                            "for CAPTCHA to auto-resolve...\n"
                        )
                    else:
                        sys.__stdout__.write(
                            "[Doubao] Browser window opened. Complete the CAPTCHA manually.\n"
                            f"         Waiting up to {wait_timeout} seconds...\n"
                        )
                    sys.__stdout__.flush()

                    captcha_cleared = await self._wait_for_captcha_clear(page, timeout=wait_timeout)

                    if not captcha_cleared:
                        await _close_headed(ctx, headed_browser, headed_pw)
                        return EngineResult(
                            engine=self.name, query=query,
                            error="CAPTCHA: verification timed out. "
                                  "Try: (1) run scripts/doubao_login.py on desktop, "
                                  "(2) refresh session cookies from a real browser.",
                        )

                    sys.__stdout__.write("[Doubao] CAPTCHA cleared! Retrying query...\n")
                    sys.__stdout__.flush()

                    await human_delay(3, 5)
                    await self._dismiss_popups(page)
                    await self._enable_web_search(page)

                    input_el = await self._find_input(page)
                    if input_el is None:
                        await _close_headed(ctx, headed_browser, headed_pw)
                        return EngineResult(
                            engine=self.name, query=query, error="input not found after CAPTCHA"
                        )

                    await input_el.click()
                    await human_delay(0.3, 0.5)
                    await input_el.type(query, delay=50)
                    await human_delay(0.5, 1.0)
                    await page.keyboard.press("Enter")
                    await human_delay(1, 2)
                else:
                    await save_page_session("doubao", ctx)
                    await ctx.close()
                    return EngineResult(
                        engine=self.name, query=query,
                        error="CAPTCHA: ByteDance detected headless automation. "
                              "Doubao uses advanced anti-bot that blocks headless Playwright. "
                              "Options: (1) install Xvfb for auto virtual-display retry, "
                              "(2) set DISPLAY and run scripts/doubao_login.py on desktop, "
                              "(3) refresh session cookies from a real browser.",
                    )

            # Wait for response — longer timeout after CAPTCHA recovery
            max_wait = 120 if headed_browser else 90
            await self._wait_for_stable_answer(page, max_wait=max_wait, stable_secs=3.0)
            await human_delay(1.0, 2.0)

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

            return EngineResult(
                engine=self.name,
                query=query,
                answer=answer,
                citations=citations,
                video_path=video_path,
            )
        except Exception as e:
            return EngineResult(engine=self.name, query=query, error=str(e))

    # ── Popup dismissal ────────────────────────────────────────

    async def _check_captcha(self, page) -> bool:
        """Check if ByteDance CAPTCHA is present/active. Returns True if blocked."""
        try:
            has_captcha = await page.evaluate("""() => {
                // Check captcha_container element
                const el = document.getElementById('captcha_container');
                if (el) {
                    const style = getComputedStyle(el);
                    if (style.display !== 'none' && style.visibility !== 'hidden'
                        && el.innerHTML.length > 0) return true;
                }
                // Check for verify iframe (ByteDance CAPTCHA loads in iframe)
                const iframes = document.querySelectorAll('iframe');
                for (const iframe of iframes) {
                    const src = iframe.src || '';
                    if (src.includes('captcha') || src.includes('verifycenter')
                        || src.includes('verify.zijieapi.com')) {
                        return true;
                    }
                }
                return false;
            }""")
            return has_captcha
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

    # ── Enable web search toggle ───────────────────────────────

    async def _enable_web_search(self, page) -> None:
        """Switch to a skill mode that provides web-search citations.

        2026-04 UI: the old "联网搜索" / "AI 搜索" buttons are gone.
        Current skill bar: 快速, 超能模式, PPT 生成, 图像生成, 帮我写作, 更多.
        "深入研究" (deep research) is behind 更多 → provides web-cited answers.
        """
        # Strategy 1: Click "更多" → "深入研究" (deep research with web citations)
        # The "更多" button is near the textarea in the action bar.
        # Use specific selector to avoid matching wrong elements (e.g. sidebar items).
        try:
            # Use exact text match to avoid matching parent containers
            more_btn = page.locator(
                "button:text-is('更多'), "
                "div:text-is('更多'):near(textarea)"
            ).first
            if await more_btn.is_visible(timeout=3000):
                await more_btn.click()
                await human_delay(0.8, 1.2)

                deep_research = page.locator(
                    "button:has-text('深入研究'), "
                    "[class*='rounded-6']:has-text('深入研究'), "
                    "[class*='cursor-pointer']:has-text('深入研究')"
                ).first
                if await deep_research.is_visible(timeout=3000):
                    await deep_research.click()
                    await human_delay(0.5, 1.0)
                    sys.__stdout__.write("[Doubao-web-search] clicked 更多 → 深入研究\n")
                    sys.__stdout__.flush()
                    return

                sys.__stdout__.write("[Doubao-web-search] 更多 opened but 深入研究 not found\n")
                sys.__stdout__.flush()
                await page.keyboard.press("Escape")
                await human_delay(0.3, 0.5)
        except Exception as e:
            sys.__stdout__.write(f"[Doubao-web-search] 更多 strategy failed: {e}\n")
            sys.__stdout__.flush()

        # Strategy 2: Direct "超能模式" button (enhanced mode with web search)
        try:
            btn = page.locator(
                "button:text-is('超能模式'), "
                "div:text-is('超能模式'):near(textarea)"
            ).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await human_delay(0.5, 1.0)
                sys.__stdout__.write("[Doubao-web-search] clicked 超能模式\n")
                sys.__stdout__.flush()
                return
        except Exception:
            pass

        # Strategy 3: Legacy "联网搜索" / "AI 搜索" (older UI or A/B test)
        for text in ["联网搜索", "AI 搜索"]:
            try:
                el = page.locator(f"button:has-text('{text}')").first
                if await el.is_visible(timeout=1000):
                    await el.click()
                    await human_delay(0.5, 1.0)
                    sys.__stdout__.write(f"[Doubao-web-search] clicked {text}\n")
                    sys.__stdout__.flush()
                    return
            except Exception:
                continue

        sys.__stdout__.write("[Doubao-web-search] proceeding in default chat mode\n")
        sys.__stdout__.flush()

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
        """Get the text content of the last assistant message bubble."""
        for sel in [
            # Doubao message bubbles — receive side
            "[data-foundation-type='receive-message']",
            "[class*='receive-msg']",
            # 2026-04: Doubao uses foundation-type markers
            "[class*='markdown-body']",
            "[class*='markdown']",
            "[class*='rich-text']",
            "[class*='msg-content']",
            "[class*='message-content']",
            "[class*='chat-item']",
        ]:
            try:
                els = await page.locator(sel).all()
                if els:
                    text = await els[-1].inner_text()
                    if text and text.strip():
                        return text
            except Exception:
                continue

        # Fallback: JS probe for any non-user message with substantial text
        try:
            text = await page.evaluate("""() => {
                const rows = document.querySelectorAll('.v_list_row');
                for (let i = rows.length - 1; i >= 0; i--) {
                    const sendBubble = rows[i].querySelector('[class*="send-msg"]');
                    if (sendBubble) continue; // skip user messages
                    const content = rows[i].innerText || '';
                    if (content.trim().length > 10) return content;
                }
                return '';
            }""")
            if text and text.strip():
                return text
        except Exception:
            pass

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

    # ── Answer extraction ──────────────────────────────────────

    async def _extract_answer(self, page) -> str:
        """Extract the answer text from the last assistant message."""
        # Primary: Doubao response selectors
        for sel in [
            "[data-foundation-type='receive-message']",
            "[class*='receive-msg']",
            "[class*='markdown']",
            "[class*='rich-text']",
        ]:
            try:
                els = await page.locator(sel).all()
                if els:
                    raw = await els[-1].inner_text()
                    if raw and raw.strip():
                        return re.sub(r"\n{3,}", "\n\n", raw).strip()
            except Exception:
                continue

        # Fallback: JS-based extraction from v_list_rows
        try:
            raw = await page.evaluate("""() => {
                const rows = document.querySelectorAll('.v_list_row');
                const results = [];
                for (const row of rows) {
                    if (row.querySelector('[class*="send-msg"]')) continue;
                    const text = (row.innerText || '').trim();
                    if (text.length > 10) results.push(text);
                }
                return results.length ? results[results.length - 1] : '';
            }""")
            if raw and raw.strip():
                cleaned = raw
                for noise in ("参考来源", "参考资料", "来源：", "以上信息来源于"):
                    cleaned = cleaned.replace(noise, "")
                return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        except Exception:
            pass

        return ""

    # ── Citation extraction (multi-path) ───────────────────────

    async def _extract_citations(self, page, answer: str) -> List[Citation]:
        """Additive multi-path extraction with global dedup.

        Priority:
          1. Network capture — API response bodies with structured URLs
          2. Reference section — "参考来源"/"参考资料" area with <a href>
          3. Inline superscript links — [1][2] style references
          4. Assistant container <a href> links
          5. Bare URLs in answer text
        """
        citations: List[Citation] = []
        seen_keys: set[str] = set()

        def _add(cit: Citation | None) -> None:
            if cit is None:
                return
            key = cit.url or cit.domain
            if not key or key in seen_keys:
                return
            seen_keys.add(key)
            citations.append(
                Citation(
                    url=cit.url,
                    domain=cit.domain,
                    title=cit.title,
                    snippet=cit.snippet,
                    position=len(citations) + 1,
                )
            )

        # ── 1) Network-capture: extract URLs from intercepted API responses
        net_urls: List[str] = []
        try:
            for body in getattr(self, "_captured_bodies", []) or []:
                # JSON fields with URLs
                for m in re.finditer(
                    r'"(?:url|link|href|source_url|web_url|redirect_url|reference_url)"\s*:\s*"'
                    r'(https?://[^"\\\s]+)"',
                    body,
                ):
                    net_urls.append(m.group(1))
                # Fallback: any URL in JSON/SSE
                for m in re.finditer(r'https?:\\?/\\?/[^\s"<>\\]{4,500}', body):
                    u = m.group(0).replace("\\/", "/")
                    net_urls.append(u)
        except Exception:
            pass

        net_urls = list(dict.fromkeys(net_urls))
        for u in net_urls:
            if any(b in u for b in _DOUBAO_BLOCK_HOSTS):
                continue
            if not u.startswith("http"):
                continue
            _add(Citation.from_url(u))

        # ── 2) Reference section: "参考来源" / "参考资料" area
        try:
            ref_links = await page.evaluate("""() => {
                const out = [];
                // Look for reference/source sections
                const headings = document.querySelectorAll(
                    'h1, h2, h3, h4, h5, div, p, span'
                );
                let refSection = null;
                for (const h of headings) {
                    const t = (h.innerText || '').trim();
                    if (/参考(来源|资料|文献)|References?|Sources?/.test(t)) {
                        // Walk up to find the parent container
                        refSection = h.closest(
                            '[class*="message"], [class*="answer"], [class*="markdown"], section, div'
                        );
                        break;
                    }
                }
                // If found, extract links from that section
                const container = refSection || document;
                container.querySelectorAll('a[href^="http"]').forEach(a => {
                    out.push({
                        href: a.href,
                        title: (a.innerText || a.textContent || '').trim().slice(0, 200),
                    });
                });
                return out;
            }""") or []
            for link in ref_links:
                href = link.get("href", "")
                title = link.get("title", "")
                if not href.startswith("http"):
                    continue
                if any(b in href for b in _DOUBAO_BLOCK_HOSTS):
                    continue
                _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 3) Source cards: Doubao shows source cards with links
        try:
            source_links = await page.evaluate("""() => {
                const out = [];
                const seen = new Set();
                // Source cards typically have specific class patterns
                document.querySelectorAll(
                    '[class*="source"] a[href^="http"], ' +
                    '[class*="reference"] a[href^="http"], ' +
                    '[class*="citation"] a[href^="http"], ' +
                    '[class*="search-result"] a[href^="http"]'
                ).forEach(a => {
                    if (seen.has(a.href)) return;
                    seen.add(a.href);
                    out.push({
                        href: a.href,
                        title: (a.innerText || a.textContent || '').trim().slice(0, 200),
                    });
                });
                return out;
            }""") or []
            for link in source_links:
                href = link.get("href", "")
                title = link.get("title", "")
                if not href.startswith("http"):
                    continue
                if any(b in href for b in _DOUBAO_BLOCK_HOSTS):
                    continue
                _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 4) All <a href> in the last assistant message area
        try:
            # Find the last assistant message container
            for container_sel in [
                "[class*='assistant']",
                "[class*='message'][class*='bot']",
                "[class*='message'][class*='ai']",
            ]:
                containers = await page.locator(container_sel).all()
                if not containers:
                    continue
                last = containers[-1]
                links = await last.locator("a[href^='http']").all()
                for link in links:
                    try:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                    except Exception:
                        continue
                    if not href or not href.startswith("http"):
                        continue
                    if any(b in href for b in _DOUBAO_BLOCK_HOSTS):
                        continue
                    _add(Citation.from_url(href, title=title))
                break
        except Exception:
            pass

        # ── 5) All page <a href> (fallback, excluding navigation)
        try:
            all_links = await page.locator("a[href^='http']").all()
            for link in all_links:
                try:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()
                except Exception:
                    continue
                if not href or not href.startswith("http"):
                    continue
                if any(b in href for b in _DOUBAO_BLOCK_HOSTS):
                    continue
                # Skip navigation/logo links (short or generic text)
                if title and len(title.strip()) <= 2:
                    continue
                _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 6) Bare URLs in answer text (last resort)
        for u in extract_urls_from_text(answer):
            if any(b in u for b in _DOUBAO_BLOCK_HOSTS):
                continue
            _add(Citation.from_url(u))

        sys.__stdout__.write(
            f"[Doubao-probe] net_urls={len(net_urls)} citations={len(citations)}\n"
        )
        sys.__stdout__.flush()

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
