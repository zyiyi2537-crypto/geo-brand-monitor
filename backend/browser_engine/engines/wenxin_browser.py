"""Wenxin (文心一言) browser adapter — automates chat.baidu.com.

chat.baidu.com 是百度 AI 搜索,带 web 引用的版本。匿名也可用,回答里
会列出参考来源。
"""

from __future__ import annotations

import re
import sys
from typing import List

from ..browser import create_stealth_page, human_delay, save_page_session
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


class WenxinBrowserAdapter(EngineAdapter):
    name = "文心一言"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://chat.baidu.com/"

    async def is_available(self) -> bool:
        try:
            page, ctx = await create_stealth_page("wenxin")
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            logged_in = await page.locator("textarea, [contenteditable='true']").count() > 0
            await ctx.close()
            return logged_in
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            page, ctx = await create_stealth_page("wenxin", record_video=self._record_video)
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            await human_delay(2, 3)

            await self._dismiss_popups(page)

            input_el = page.locator("textarea, [contenteditable='true']").first
            try:
                await input_el.wait_for(state="visible", timeout=10000)
            except Exception:
                await ctx.close()
                return EngineResult(engine=self.name, query=query, error="input not visible")

            await input_el.click()
            try:
                await input_el.fill(query)
            except Exception:
                await input_el.type(query)
            await human_delay(0.5, 1.0)

            await page.keyboard.press("Enter")

            # Wait for streaming to finish using stability detection.
            # chat.baidu.com uses `.cosd-markdown-content-typingall` during streaming
            # and removes it when done. Fallback: polling inner_text stability.
            await human_delay(3, 5)
            try:
                # Primary: wait for typing indicator to disappear
                await page.wait_for_function(
                    """() => !document.querySelector('.cosd-markdown-content-typingall')
                           && !document.querySelector('.cosd-markdown-loading')
                           && !document.querySelector('[data-auto-test="stop_response"]')""",
                    timeout=60000,
                )
            except Exception:
                pass

            # Extra settle time for final markdown render
            await human_delay(1.0, 2.0)

            answer = ""
            # chat.baidu.com DOM (2026-04): .cosd-markdown-content inside answer container
            for sel in [
                ".cosd-markdown-content",
                ".cosd-markdown",
                ".ai-markdown",
                "div.conversation-flow-answer-container .markdown-body",
                "div.conversation-flow-answer-container",
                "#answer_text_id",
                ".custom-html.md-stream",
                "[class*='md-stream']",
            ]:
                try:
                    els = await page.locator(sel).all()
                    if els:
                        answer = await els[-1].inner_text()
                        if answer.strip():
                            break
                except Exception:
                    continue

            # citation 折叠在 "参考 N 个网页" chip 里,需点击展开才能抓 a[href]
            await self._expand_references(page)

            citations = await self._extract_citations(page, answer)

            await save_page_session("wenxin", ctx)

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

    async def _expand_references(self, page) -> None:
        """Click "参考 N 个网页" chip to expand the source drawer.

        chat.baidu.com renders reference chips with text matching "参考.*网页".
        Multiple strategies to find and click the chip.
        """
        strategies = [
            # Strategy 1: Hashed class (may change)
            lambda: page.locator('div[class*="titleText"]', has_text=re.compile(r'参考')).first,
            # Strategy 2: Any element with "参考 N 个网页" text
            lambda: page.locator("text=参考").first,
            # Strategy 3: Source/cosource containers
            lambda: page.locator("[class*='source-caption'], [class*='cosc-source-caption']").first,
        ]

        for get_locator in strategies:
            try:
                el = get_locator()
                if not await el.is_visible(timeout=2000):
                    continue

                # Try clicking the element, then its parent
                try:
                    await el.click()
                except Exception:
                    try:
                        await el.locator("xpath=..").click()
                    except Exception:
                        continue

                await human_delay(0.8, 1.5)
                sys.__stdout__.write("[Wenxin-probe] reference chip clicked\n")
                sys.__stdout__.flush()
                return
            except Exception:
                continue

        sys.__stdout__.write("[Wenxin-probe] reference chip not found\n")
        sys.__stdout__.flush()

    async def _dismiss_popups(self, page) -> None:
        for sel in [
            "text=我知道了",
            "text=同意",
            "text=Accept",
            "[aria-label='close']",
            ".close-btn",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await human_delay(0.3, 0.8)
            except Exception:
                continue

    _BAIDU_BLOCK = ("baidu.com", "baidubce.com", "bdimg.com", "bdstatic.com")

    async def _extract_citations(self, page, answer: str) -> List[Citation]:
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

        # ── 1) Extract embedded JSON data: chat.baidu.com stores URLs in
        #    HTML-encoded JSON within the page data: &quot;linkTitle&quot;:&quot;...&quot;
        try:
            embedded = await page.evaluate(r"""() => {
                const html = document.body.innerHTML;
                const out = [];
                const seen = new Set();
                // Match: URL followed by linkTitle
                const re = /(https?:[^"&<>\\]{4,500})&quot;,&quot;linkTitle&quot;:&quot;([^&]*)/g;
                let m;
                while ((m = re.exec(html)) !== null) {
                    let url = m[1]
                        .replace(/&amp;/g, '&')
                        .replace(/\\u002F/g, '/');
                    let title = m[2]
                        .replace(/&amp;/g, '&')
                        .replace(/\\u002F/g, '/');
                    if (!url.startsWith('http')) continue;
                    if (seen.has(url)) continue;
                    seen.add(url);
                    out.push({url, title});
                }
                return out;
            }""") or []
            for item in embedded:
                url = item.get("url", "")
                title = item.get("title", "")
                if not url.startswith("http"):
                    continue
                if any(b in url for b in self._BAIDU_BLOCK):
                    continue
                _add(Citation.from_url(url, title=title))
        except Exception:
            pass

        # ── 2) DOM: cosc-source-a and other link selectors
        try:
            for sel in [
                ".cosc-source-a[href]",
                ".cosc-source a[href]",
                "[class*='source'] a[href]",
                "[class*='reference'] a[href]",
                ".cosd-markdown a[href]",
            ]:
                links = await page.locator(sel).all()
                if links:
                    for link in links:
                        try:
                            href = await link.get_attribute("href")
                            title = await link.inner_text()
                        except Exception:
                            continue
                        if (
                            href
                            and href.startswith("http")
                            and not any(b in href for b in self._BAIDU_BLOCK)
                        ):
                            _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 3) Bare URLs in answer text
        for u in extract_urls_from_text(answer):
            if not any(b in u for b in self._BAIDU_BLOCK):
                _add(Citation.from_url(u))

        # Debug probe
        try:
            sys.__stdout__.write(
                f"[Wenxin-probe] citations={len(citations)}\n"
            )
            sys.__stdout__.flush()
        except Exception:
            pass

        return citations
