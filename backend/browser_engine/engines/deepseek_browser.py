"""DeepSeek browser adapter — automates chat.deepseek.com.

DeepSeek's API has no web search, but the web UI does via the "智能搜索"
(Smart Search) toggle. This adapter uses Playwright to:
1. Dismiss cookie consent banner
2. Enable "智能搜索" for each query
3. Submit query, wait for answer
4. Extract answer text + citation links

Requires: a valid DeepSeek session (run scripts/deepseek_login.py first).
"""

from __future__ import annotations

import asyncio
import re
from typing import List

from ..browser import create_stealth_page, human_delay, save_page_session
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


class DeepSeekBrowserAdapter(EngineAdapter):
    name = "DeepSeek"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://chat.deepseek.com/"

    async def is_available(self) -> bool:
        try:
            page, ctx = await create_stealth_page("deepseek")
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            logged_in = await page.locator("textarea").count() > 0
            await ctx.close()
            return logged_in
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            page, ctx = await create_stealth_page("deepseek", record_video=self._record_video)
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            await human_delay(2, 3)

            # Dismiss cookie consent banner if present
            await self._dismiss_cookie_banner(page)

            # Click "开启新对话" to start a fresh chat (avoids context pollution)
            try:
                new_chat_btn = page.locator("text=开启新对话").first
                if await new_chat_btn.is_visible(timeout=2000):
                    await new_chat_btn.click()
                    await human_delay(1, 2)
            except Exception:
                pass

            # Enable "智能搜索" (Smart Search) for web results
            await self._enable_smart_search(page)

            # Type query into the textarea
            textarea = page.locator("textarea").first
            await textarea.click()
            await textarea.fill(query)
            await human_delay(0.5, 1.0)

            # Submit
            await page.keyboard.press("Enter")

            # Wait for response to complete via content-stability polling.
            # Old approach (Stop-button text detection) broke when DeepSeek
            # switched to SVG-icon buttons without text content.
            await asyncio.sleep(3)
            last_len = 0
            stable_count = 0
            for _ in range(120):
                await asyncio.sleep(1)
                try:
                    answer_els = await page.locator(".ds-markdown").all()
                    if answer_els:
                        cur_text = await answer_els[-1].inner_text()
                        cur_len = len(cur_text)
                        if cur_len > 0 and cur_len == last_len:
                            stable_count += 1
                            if stable_count >= 5:
                                break
                        else:
                            last_len = cur_len
                            stable_count = 0
                except Exception:
                    pass

            # Extract answer text — try multiple selectors
            answer = ""
            for sel in [".ds-markdown", ".markdown"]:
                answer_els = await page.locator(sel).all()
                if answer_els:
                    answer = await answer_els[-1].inner_text()
                    if answer.strip():
                        break

            # Extract citations
            citations = await self._extract_citations(page, answer)

            await save_page_session("deepseek", ctx)

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

    async def _dismiss_cookie_banner(self, page) -> None:
        """Dismiss the cookie consent popup if visible."""
        try:
            for text in ["接受全部", "Accept All", "Accept"]:
                btn = page.locator(f"text={text}").first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await human_delay(0.5, 1)
                    return
        except Exception:
            pass

    async def _enable_smart_search(self, page) -> None:
        """Ensure '智能搜索' (Smart Search) toggle is ON.

        DS 新版按钮结构:<div class="... ds-toggle-button ...">...<span>智能搜索</span>...</div>
        点击事件绑在外层 toggle div,内层 span 不一定触发。定位外层 div 再点。
        """
        import sys
        try:
            btn = page.locator('div.ds-toggle-button', has_text='智能搜索').first
            if not await btn.is_visible(timeout=3000):
                sys.__stdout__.write("[DS-smart-search] toggle not visible\n")
                sys.__stdout__.flush()
                return

            before_cls = await btn.evaluate("el => el.className || ''")
            # 激活态典型 token:active / selected / on / checked / primary
            already_on = any(tok in before_cls.lower() for tok in ('active', 'selected', '--on', 'checked', 'primary'))
            if already_on:
                sys.__stdout__.write(f"[DS-smart-search] already ON: cls={before_cls!r}\n")
                sys.__stdout__.flush()
                return

            await btn.click()
            await human_delay(0.5, 1.0)
            after_cls = await btn.evaluate("el => el.className || ''")
            sys.__stdout__.write(
                f"[DS-smart-search] clicked. before={before_cls!r} after={after_cls!r}\n"
            )
            sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[DS-smart-search] failed: {type(e).__name__}: {e}\n")
            sys.__stdout__.flush()

    async def _extract_citations(self, page, answer: str) -> List[Citation]:
        """Extract citation links from the DeepSeek response."""
        import sys
        citations = []

        # ── 临时探测:关注"智能搜索"按钮当前状态 + dump body HTML ──
        try:
            probe = await page.evaluate("""() => {
                // 所有短文本按钮,看搜索 toggle 现在叫什么
                const buttons = [];
                document.querySelectorAll('button, [role="button"], div[tabindex]').forEach(el => {
                    const text = (el.innerText || '').trim();
                    if (text && text.length <= 20) {
                        buttons.push({
                            tag: el.tagName,
                            text: text,
                            cls: (typeof el.className === 'string' ? el.className : '').slice(0, 100),
                            aria_pressed: el.getAttribute('aria-pressed'),
                            data_active: el.getAttribute('data-active'),
                        });
                    }
                });
                // 关键词出现次数(判断搜索是否真正执行了)
                const body_text = (document.body.innerText || '');
                const keywords = {};
                ['智能搜索', '联网搜索', '深度思考', '已搜索', '来源', '参考资料', '引用', 'Search', 'Source', 'Reference'].forEach(kw => {
                    keywords[kw] = (body_text.match(new RegExp(kw, 'gi')) || []).length;
                });
                // iframe / shadow root 检测
                const iframes = document.querySelectorAll('iframe').length;
                let shadowRoots = 0;
                document.querySelectorAll('*').forEach(el => { if (el.shadowRoot) shadowRoots++; });
                return { buttons: buttons.slice(0, 30), keywords, iframes, shadowRoots };
            }""")
            sys.__stdout__.write(f"[DS-probe] iframes={probe['iframes']} shadowRoots={probe['shadowRoots']}\n")
            sys.__stdout__.write(f"[DS-probe] keywords={probe['keywords']}\n")
            sys.__stdout__.write(f"[DS-probe] buttons (first 30):\n")
            for b in probe['buttons']:
                sys.__stdout__.write(f"  {b}\n")
            sys.__stdout__.flush()
        except Exception as _e:
            sys.__stdout__.write(f"[DS-probe] probe failed: {type(_e).__name__}: {_e}\n")
            sys.__stdout__.flush()

        # 只在第一次抓不到 citation 时 dump body HTML 给离线分析
        try:
            import os
            dump_path = "/tmp/deepseek_q1_body.html"
            if not os.path.exists(dump_path):
                body_html = await page.evaluate("() => document.body.innerHTML")
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(body_html)
                sys.__stdout__.write(f"[DS-probe] dumped body HTML ({len(body_html)} bytes) -> {dump_path}\n")
                sys.__stdout__.flush()
        except Exception as _e:
            sys.__stdout__.write(f"[DS-probe] dump failed: {type(_e).__name__}: {_e}\n")
            sys.__stdout__.flush()

        # Try to find citation links in the answer area (updated selectors)
        try:
            for sel in [".ds-markdown a[href]", ".markdown a[href]"]:
                links = await page.locator(sel).all()
                if links:
                    seen = set()
                    for i, link in enumerate(links):
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                        if (
                            href
                            and href.startswith("http")
                            and "deepseek.com" not in href
                            and href not in seen
                        ):
                            seen.add(href)
                            citations.append(
                                Citation.from_url(href, title=title, position=i + 1)
                            )
                    if citations:
                        break
        except Exception:
            pass

        # Also try to find source reference cards/panels
        try:
            source_cards = await page.locator("[class*=search-result] a[href], [class*=source] a[href], [class*=citation] a[href]").all()
            seen = {c.url for c in citations}
            for i, card in enumerate(source_cards):
                href = await card.get_attribute("href")
                title = await card.inner_text()
                if href and href.startswith("http") and href not in seen:
                    seen.add(href)
                    citations.append(
                        Citation.from_url(href, title=title, position=len(citations) + 1)
                    )
        except Exception:
            pass

        # Fallback: extract URLs from answer text
        if not citations:
            urls = extract_urls_from_text(answer)
            citations = [Citation.from_url(u, position=i + 1) for i, u in enumerate(urls)]

        return citations
