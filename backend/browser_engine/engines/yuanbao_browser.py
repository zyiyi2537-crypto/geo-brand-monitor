"""Yuanbao (腾讯元宝) browser adapter — automates yuanbao.tencent.com.

Yuanbao is Tencent's AI chat product (Hunyuan). The web UI supports "联网搜索"
(web search) which returns answers with structured citation cards and ref lists.

DOM notes (2026-04, Next.js + TDesign):
  - Input: Quill-based contenteditable div inside `.agent-dialogue__content--common__input-box`
  - "联网搜索" toggle: button/div with text "联网搜索", icon class `icon-yb-ai-search`
  - Response: AI bubble `.agent-chat__bubble--ai` > `.agent-chat__bubble__content`
  - Markdown: `.hyc-common-markdown` wraps the rendered answer
  - Citations:
    - Ref cards: `.hyc-common-markdown__ref_card` with title/link/foot
    - Ref list: `.hyc-common-markdown__ref-list__item` with source names
    - Ref drawer: `.hyc-common-markdown__ref-drawer` side panel
  - API: SSE streaming via `/api/chat`, citation data in response chunks

Requires: a valid Yuanbao session (run scripts/yuanbao_login.py first).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import List

from ..browser import create_stealth_page, human_delay, save_page_session
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


_YUANBAO_BLOCK_HOSTS = (
    "yuanbao.tencent.com",
    "tencent.com",
    "qq.com",
    "weixin.qq.com",
    "cloud.tencent.com",
    "tb.cn",
    "gtm.cn",
    "googletagmanager.com",
    "myqcloud.com",
    "wx.qlogo.cn",
    "hunyuan.tencent.com",
    "hy-openapi-public",
    "hy-openapi-pulbic",
)


class YuanbaoBrowserAdapter(EngineAdapter):
    name = "元宝"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://yuanbao.tencent.com/chat?searchType=network"

    # Selectors
    AI_BUBBLE_SEL = ".agent-chat__bubble--ai"
    MARKDOWN_SEL = ".hyc-common-markdown"
    REF_CARD_SEL = ".hyc-common-markdown__ref_card"
    REF_LIST_ITEM_SEL = ".hyc-common-markdown__ref-list__item"
    REF_LIST_TRIGGER_SEL = ".hyc-common-markdown__ref-list__trigger"

    async def is_available(self) -> bool:
        try:
            page, ctx = await create_stealth_page("yuanbao")
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            await human_delay(2, 3)
            logged_in = await page.locator(
                "div[contenteditable='true'], textarea"
            ).count() > 0
            await ctx.close()
            return logged_in
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            page, ctx = await create_stealth_page("yuanbao", record_video=self._record_video)

            # Network capture: intercept chat API responses for citation URLs
            captured_bodies: List[str] = []
            self._captured_bodies = captured_bodies

            def _on_response(response):
                url_l = response.url.lower()
                if not any(kw in url_l for kw in ("/api/chat", "/api/conv", "completion", "search")):
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
            await human_delay(2, 4)

            # Force internet search via sessionStorage (Yuanbao reads this on page load)
            try:
                await page.evaluate(
                    'sessionStorage.setItem("YB_ASK_AI_SEARCH_TYPE_NETWORK", "1")'
                )
            except Exception:
                pass

            # Dismiss popups
            await self._dismiss_popups(page)

            # Start a new conversation to avoid context pollution
            await self._start_new_chat(page)

            # Enable "联网搜索" (web search) toggle
            await self._enable_web_search(page)

            # Find and fill the input
            input_el = await self._find_input(page)
            if input_el is None:
                await ctx.close()
                return EngineResult(
                    engine=self.name, query=query, error="input not found"
                )

            # Check for login wall — if input says "请登录后输入内容", abort
            try:
                placeholder = await input_el.get_attribute("data-placeholder") or ""
                if "登录" in placeholder:
                    await ctx.close()
                    return EngineResult(
                        engine=self.name, query=query,
                        error=f"login required (placeholder: {placeholder})"
                    )
            except Exception:
                pass

            await input_el.click()
            try:
                await input_el.fill(query)
            except Exception:
                await input_el.type(query, delay=80)
            await human_delay(0.5, 1.0)

            # Submit with Enter
            await page.keyboard.press("Enter")

            # Wait for response to complete
            await human_delay(3, 5)
            await self._wait_for_stable_answer(page, max_wait=60, stable_secs=2.5)
            await human_delay(1.0, 2.0)

            # Debug probe
            await self._probe_page(page)

            # Extract answer + citations
            answer = await self._extract_answer(page)
            citations = await self._extract_citations(page, answer)

            await save_page_session("yuanbao", ctx)

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

    # ── Popup dismissal ────────────────────────────────────────

    async def _dismiss_popups(self, page) -> None:
        for sel in [
            "text=我知道了",
            "text=同意",
            "text=Accept",
            "text=接受全部",
            "text=不再提示",
            "[aria-label='close']",
            "[aria-label='Close']",
            "[class*='close'] >> visible=true",
            ".t-dialog__close",
            ".t-dialog__position [class*='close']",
            ".t-dialog__modal-close",
            "button:has-text('暂不登录')",
            "button:has-text('稍后再说')",
            "text=暂不登录",
            "text=稍后再说",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    await human_delay(0.3, 0.6)
            except Exception:
                continue

    # ── Start new chat ─────────────────────────────────────────

    async def _start_new_chat(self, page) -> None:
        try:
            btn = page.locator('[data-desc="new-chat"]').first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                await human_delay(1, 2)
                return
        except Exception:
            pass
        # Fallback: text-based
        try:
            btn = page.locator("text=发起新对话").first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await human_delay(1, 2)
        except Exception:
            pass

    # ── Enable web search toggle ───────────────────────────────

    async def _enable_web_search(self, page) -> None:
        """Enable "联网搜索" (web search) toggle on the Yuanbao chat page.

        The clickable element is `div.yb-internet-search-btn` with
        `dt-button-id="internet_search"`. When active, it gets class `index_v2_active__mMizI`.
        """
        strategies = [
            # Strategy 1: The main clickable button
            lambda: page.locator('[dt-button-id="internet_search"]').first,
            # Strategy 2: Class-based selector
            lambda: page.locator('.yb-internet-search-btn').first,
            # Strategy 3: Text-based with parent traversal
            lambda: page.locator("text=联网搜索").first.locator("xpath=../.."),
            # Strategy 4: Just click the text
            lambda: page.locator("text=联网搜索").first,
        ]

        for get_locator in strategies:
            try:
                el = get_locator()
                if not await el.is_visible(timeout=2000):
                    continue

                # Check if already active (class contains "active" or "checked")
                cls = await el.evaluate("el => (el.className || '').toString()")
                if "active" in cls.lower() or "checked" in cls.lower():
                    sys.__stdout__.write("[Yuanbao-web-search] already ON\n")
                    sys.__stdout__.flush()
                    return

                await el.click()
                await human_delay(0.5, 1.0)

                after_cls = await el.evaluate("el => (el.className || '').toString()")
                sys.__stdout__.write(
                    f"[Yuanbao-web-search] clicked. before={cls!r} after={after_cls!r}\n"
                )
                sys.__stdout__.flush()

                # Verify activation
                if "active" in after_cls.lower() or "checked" in after_cls.lower():
                    return
            except Exception:
                continue

        sys.__stdout__.write("[Yuanbao-web-search] toggle not found, proceeding without it\n")
        sys.__stdout__.flush()

    # ── Input detection ────────────────────────────────────────

    async def _find_input(self, page):
        for sel in [
            "div[contenteditable='true']",
            ".ql-editor",
            "textarea",
            ".agent-dialogue__content--common__input-box [contenteditable='true']",
        ]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    # ── Response waiting ───────────────────────────────────────

    async def _wait_for_stable_answer(
        self, page, max_wait: float = 120.0, stable_secs: float = 2.5
    ) -> None:
        poll_interval = 0.8
        last_text = ""
        stable_since = None
        elapsed = 0.0

        while elapsed < max_wait:
            try:
                cur = await self._get_last_ai_text(page)
            except Exception:
                cur = last_text

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

    async def _get_last_ai_text(self, page) -> str:
        for sel in [
            f"{self.AI_BUBBLE_SEL} {self.MARKDOWN_SEL}",
            self.MARKDOWN_SEL,
            f"{self.AI_BUBBLE_SEL} .agent-chat__bubble__content",
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

    _CITATION_URL_KEYS = frozenset({
        "url", "link", "href", "source_url", "web_url",
        "redirect_url", "reference_url", "sourceUrl", "webUrl",
    })
    _CITATION_TITLE_KEYS = frozenset({
        "title", "name", "source", "site_name", "siteName",
        "sourceName", "hostName", "domain",
    })
    _CITATION_SNIPPET_KEYS = frozenset({
        "snippet", "abstract", "summary", "description", "content",
    })

    def _extract_citations_from_json(
        self, obj, out: List[dict], _depth: int = 0
    ) -> None:
        """Recursively extract citation-like objects from parsed SSE JSON."""
        if _depth > 8 or not obj:
            return
        if isinstance(obj, dict):
            url = ""
            for k in self._CITATION_URL_KEYS:
                v = obj.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    url = v
                    break
            if url:
                title = ""
                for k in self._CITATION_TITLE_KEYS:
                    v = obj.get(k)
                    if isinstance(v, str) and len(v) > 1:
                        title = v
                        break
                snippet = ""
                for k in self._CITATION_SNIPPET_KEYS:
                    v = obj.get(k)
                    if isinstance(v, str) and len(v) > 5:
                        snippet = v
                        break
                domain = obj.get("domain") or obj.get("host") or ""
                out.append({"url": url, "title": title, "snippet": snippet, "domain": domain})
            for v in obj.values():
                self._extract_citations_from_json(v, out, _depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._extract_citations_from_json(item, out, _depth + 1)

    async def _capture_body(self, response, bucket: List[str]) -> None:
        try:
            text = await response.text()
        except Exception:
            return
        if not text:
            return
        bucket.append(text[:400_000])

    # ── Answer extraction ──────────────────────────────────────

    async def _extract_answer(self, page) -> str:
        for sel in [
            f"{self.AI_BUBBLE_SEL} {self.MARKDOWN_SEL}",
            self.MARKDOWN_SEL,
            f"{self.AI_BUBBLE_SEL} .agent-chat__bubble__content",
        ]:
            try:
                els = await page.locator(sel).all()
                if els:
                    raw = await els[-1].inner_text()
                    if raw and raw.strip():
                        return re.sub(r"\n{3,}", "\n\n", raw).strip()
            except Exception:
                continue
        return ""

    # ── Citation extraction (multi-path) ───────────────────────

    async def _extract_citations(self, page, answer: str) -> List[Citation]:
        citations: List[Citation] = []
        seen_keys: set[str] = set()

        def _add(cit: Citation | None) -> None:
            if cit is None:
                return
            key = cit.url or cit.domain
            if not key:
                return
            if key in seen_keys:
                # Upgrade: replace existing citation if new one carries a title
                if cit.title:
                    for i, ex in enumerate(citations):
                        if (ex.url or ex.domain) == key and not ex.title:
                            citations[i] = Citation(
                                url=cit.url,
                                domain=cit.domain,
                                title=cit.title,
                                snippet=cit.snippet,
                                position=ex.position,
                            )
                            return
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
        # Structured citations from SSE JSON lines
        net_citations: List[dict] = []
        try:
            for body in getattr(self, "_captured_bodies", []) or []:
                # Parse SSE data lines as JSON
                for line in body.split("\n"):
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload in ("[DONE]", "[done]"):
                        continue
                    try:
                        obj = json.loads(payload)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    # Walk the JSON tree for citation-like objects
                    self._extract_citations_from_json(obj, net_citations)

                # Fallback: regex for structured JSON fields
                for m in re.finditer(
                    r'"(?:url|link|href|source_url|web_url|redirect_url|reference_url)"\s*:\s*"'
                    r'(https?://[^"\\\s]+)"',
                    body,
                ):
                    net_urls.append(m.group(1))
                # SSE data lines with URL
                for m in re.finditer(r'https?:\\?/\\?/[^\s"<>\\]{4,500}', body):
                    u = m.group(0).replace("\\/", "/")
                    net_urls.append(u)
        except Exception:
            pass

        # Add structured citations from SSE (with title)
        for cit_data in net_citations:
            url = cit_data.get("url", "")
            if not url.startswith("http"):
                continue
            if any(b in url for b in _YUANBAO_BLOCK_HOSTS):
                continue
            _add(Citation(
                url=url,
                domain=cit_data.get("domain", ""),
                title=cit_data.get("title", ""),
                snippet=cit_data.get("snippet", ""),
                position=0,
            ))

        # Add bare URLs as fallback
        net_urls = list(dict.fromkeys(net_urls))
        for u in net_urls:
            if any(b in u for b in _YUANBAO_BLOCK_HOSTS):
                continue
            if not u.startswith("http"):
                continue
            _add(Citation.from_url(u))

        # ── 2) Expand ref list trigger (click to reveal hidden sources)
        await self._expand_ref_list(page)

        # ── 3) Ref cards: structured citation cards with title/link/foot
        try:
            ref_cards = await page.evaluate("""() => {
                const out = [];
                const seen = new Set();
                document.querySelectorAll('.hyc-common-markdown__ref_card').forEach(card => {
                    const link = card.querySelector('a[href^="http"]');
                    const titleEl = card.querySelector('.hyc-common-markdown__ref_card-title');
                    const footEl = card.querySelector('.hyc-common-markdown__ref_card-foot__source_txt');
                    const href = link ? link.href : '';
                    if (!href || !href.startsWith('http') || seen.has(href)) return;
                    seen.add(href);
                    out.push({
                        href: href,
                        title: (titleEl ? titleEl.innerText || titleEl.textContent : '').trim().slice(0, 200),
                        domain: (footEl ? footEl.innerText || footEl.textContent : '').trim(),
                    });
                });
                return out;
            }""") or []
            for card in ref_cards:
                href = card.get("href", "")
                title = card.get("title", "")
                if not href.startswith("http"):
                    continue
                if any(b in href for b in _YUANBAO_BLOCK_HOSTS):
                    continue
                _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 4) Ref list items: source name entries (may contain <a href>)
        try:
            ref_items = await page.evaluate("""() => {
                const out = [];
                const seen = new Set();
                document.querySelectorAll('.hyc-common-markdown__ref-list__item').forEach(item => {
                    const link = item.querySelector('a[href^="http"]');
                    const nameEl = item.querySelector('.hyc-common-markdown__ref-list__item__name');
                    if (link) {
                        const href = link.href;
                        if (!seen.has(href)) {
                            seen.add(href);
                            out.push({
                                href: href,
                                title: (nameEl ? nameEl.innerText || nameEl.textContent : '').trim(),
                            });
                        }
                    } else if (nameEl) {
                        const name = (nameEl.innerText || '').trim();
                        if (name) out.push({ name: name });
                    }
                });
                return out;
            }""") or []
            for item in ref_items:
                href = item.get("href", "")
                title = item.get("title", "") or item.get("name", "")
                if href and href.startswith("http"):
                    if not any(b in href for b in _YUANBAO_BLOCK_HOSTS):
                        _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 5) Ref drawer: side panel links
        try:
            drawer_links = await page.evaluate("""() => {
                const out = [];
                const seen = new Set();
                document.querySelectorAll('.hyc-common-markdown__ref-drawer a[href^="http"]').forEach(a => {
                    if (seen.has(a.href)) return;
                    seen.add(a.href);
                    out.push({
                        href: a.href,
                        title: (a.innerText || a.textContent || '').trim().slice(0, 200),
                    });
                });
                return out;
            }""") or []
            for link in drawer_links:
                href = link.get("href", "")
                title = link.get("title", "")
                if not href.startswith("http"):
                    continue
                if any(b in href for b in _YUANBAO_BLOCK_HOSTS):
                    continue
                _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 6) All <a href> in the last AI bubble
        try:
            bubbles = await page.locator(self.AI_BUBBLE_SEL).all()
            if bubbles:
                last = bubbles[-1]
                links = await last.locator("a[href^='http']").all()
                for link in links:
                    try:
                        href = await link.get_attribute("href")
                        title = await link.inner_text()
                    except Exception:
                        continue
                    if not href or not href.startswith("http"):
                        continue
                    if any(b in href for b in _YUANBAO_BLOCK_HOSTS):
                        continue
                    _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 7) Bare URLs in answer text
        for u in extract_urls_from_text(answer):
            if any(b in u for b in _YUANBAO_BLOCK_HOSTS):
                continue
            _add(Citation.from_url(u))

        sys.__stdout__.write(
            f"[Yuanbao-probe] net_urls={len(net_urls)} citations={len(citations)}\n"
        )
        sys.__stdout__.flush()

        return citations

    # ── Expand ref list ────────────────────────────────────────

    async def _expand_ref_list(self, page) -> None:
        """Click the ref list trigger to expand hidden sources."""
        try:
            trigger = page.locator(self.REF_LIST_TRIGGER_SEL).last
            if await trigger.is_visible(timeout=2000):
                await trigger.click()
                await human_delay(0.5, 1.0)
        except Exception:
            pass

    # ── Debug probe ────────────────────────────────────────────

    async def _probe_page(self, page) -> None:
        try:
            probe = await page.evaluate("""() => {
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
                const body_text = document.body.innerText || '';
                const keywords = {};
                ['联网搜索', '参考来源', '参考资料', '来源', '引用',
                 '搜索', 'Search', 'Source', 'Reference', 'citation'
                ].forEach(kw => {
                    keywords[kw] = (body_text.match(new RegExp(kw, 'gi')) || []).length;
                });
                const httpLinks = document.querySelectorAll('a[href^="http"]').length;
                const refCards = document.querySelectorAll('.hyc-common-markdown__ref_card').length;
                const refItems = document.querySelectorAll('.hyc-common-markdown__ref-list__item').length;
                const aiBubbles = document.querySelectorAll('.agent-chat__bubble--ai').length;
                return { buttons: buttons.slice(0, 40), keywords, httpLinks, refCards, refItems, aiBubbles };
            }""")

            sys.__stdout__.write(
                f"[Yuanbao-probe] keywords={probe['keywords']} "
                f"httpLinks={probe['httpLinks']} refCards={probe['refCards']} "
                f"refItems={probe['refItems']} aiBubbles={probe['aiBubbles']}\n"
            )
            sys.__stdout__.write("[Yuanbao-probe] buttons:\n")
            for b in probe["buttons"]:
                sys.__stdout__.write(f"  {b}\n")
            sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[Yuanbao-probe] failed: {type(e).__name__}: {e}\n")
            sys.__stdout__.flush()

        # Dump body HTML for first-run analysis
        try:
            import os
            dump_path = "/tmp/yuanbao_q1_body.html"
            if not os.path.exists(dump_path):
                body_html = await page.evaluate("() => document.body.innerHTML")
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(body_html)
                sys.__stdout__.write(
                    f"[Yuanbao-probe] dumped body HTML ({len(body_html)} bytes) -> {dump_path}\n"
                )
                sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[Yuanbao-probe] dump failed: {type(e).__name__}: {e}\n")
            sys.__stdout__.flush()
