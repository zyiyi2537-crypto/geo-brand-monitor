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
import random
import re
import sys
from typing import List

from ..browser import (
    create_stealth_page,
    create_headed_page,
    human_delay,
    human_click,
    simulate_browsing,
    save_page_session,
)
from ..anti_detect import _pick_profile
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


async def _close_headed(ctx, browser=None, pw=None) -> None:
    """Close headed browser context, browser, and playwright instance.

    CloakBrowser 路径下 browser / pw 都是 None,只 close ctx;patchright
    fallback 路径下要按顺序 close ctx → browser → pw.stop()。
    """
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


# CP1252(Windows-1252)在 0x80-0x9F 区把若干字节映射到了 latin-1 不在的字符
# (em-dash、引号、欧元符号等)。元宝 SSE JSON 是按 CP1252 把 UTF-8 字节解出来再
# \\uXXXX 转义的 —— 单纯 encode('latin-1') round-trip 不回去,因为这些字符在
# latin-1 里不存在。手工表把它们映射回原字节,其余 < U+0100 走 latin-1 一一对应。
_CP1252_HIGH = {
    0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84, 0x2026: 0x85,
    0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88, 0x2030: 0x89, 0x0160: 0x8A,
    0x2039: 0x8B, 0x0152: 0x8C, 0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92,
    0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
    0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B, 0x0153: 0x9C,
    0x017E: 0x9E, 0x0178: 0x9F,
}


def _fix_mojibake(s: str) -> str:
    """还原 'UTF-8 字节被按 CP1252 解码' 类 mojibake('世'→'ä¸–')。

    元宝 SSE JSON 把 UTF-8 字节按 CP1252/Latin-1 当 codepoint 用 \\uXXXX 转义。
    修复:把每个字符映射回原字节,再 decode('utf-8')。
    仅在 s 含典型 mojibake 引导字符且能干净往返时才改;否则原样返回。
    """
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
                # 出现真 Unicode 字符(非 CP1252 mapping) —— 不像 mojibake,放弃修
                return s
        return bs.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return s


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

    # NOTE(D3 2026-05-18):yuanbao 早就有 _start_new_chat 在本类下方 line 280 附近,
    # 用 `[data-desc="new-chat"]` + `text=发起新对话` 双 fallback,已 production
    # 验证.D3 期间一度误加了一个 best-guess 重复版本(用 "新对话" 文本),被下面
    # 那个真版本 override 了,后来发现后删除.D4 EngineSession 用的就是下面那个.

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
            input_el = page.locator("div[contenteditable='true'], textarea").first
            try:
                await input_el.wait_for(state="visible", timeout=8000)
                logged_in = True
            except Exception:
                logged_in = False
            if logged_in:
                placeholder = (await input_el.get_attribute("data-placeholder")
                               or await input_el.get_attribute("placeholder") or "")
                logged_in = "登录" not in placeholder
            await ctx.close()
            return logged_in
        except Exception:
            return False

    async def verify_session(self) -> dict:
        from ..session_verifier import verify_account_session
        return await verify_account_session(self, "yuanbao", probe_new_chat=True)

    # 2026-05-26:迁到 CloakBrowser(github.com/CloakHQ/CloakBrowser)。
    # CloakBrowser 在编译层 patch chromium(49+ 源码级 patch),比 playwright
    # 的 runtime CDP patch 干净,navigator/webgl/permissions 都没有自动化痕迹。
    # _create_hot_page → EngineSession.init() 第一次调一次,长生 ctx 复用。
    async def _create_hot_page(self):
        """元宝专用:Xvfb + headed + cloakbrowser。"""
        import os
        if os.name != "nt" and not os.environ.get("DISPLAY"):
            from ..xvfb import start_xvfb
            start_xvfb()
        profile = _pick_profile(platform_filter="Win32" if os.name == "nt" else "Linux x86_64")
        page, ctx = await create_headed_page(
            "yuanbao",
            profile=profile,
            record_video=self._record_video,
        )
        return page, ctx

    async def _close_hot_page(self, page, ctx) -> None:
        """元宝专用:cloakbrowser 的 ctx + patchright fallback 的 browser/pw 都 close."""
        headed_browser = getattr(page, "_headed_browser", None)
        headed_pw = getattr(page, "_pw_ref", None)
        await _close_headed(ctx, headed_browser, headed_pw)

    # D4d(2026-05-18):hot browser protocol — _prepare_page + _query_with_page
    # 共享 search() 的 helpers,search() 本身**不动**,one-shot 零回归.
    async def _prepare_page(self, page, ctx) -> None:
        """Hot init:网络抓包 listener + goto + sessionStorage 强制联网搜索 + 弹窗."""
        self._captured_bodies = []

        def _on_response(response):
            url_l = response.url.lower()
            if not any(kw in url_l for kw in ("/api/chat", "/api/conv", "completion", "search")):
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
        await human_delay(2, 4)
        try:
            await page.evaluate(
                'sessionStorage.setItem("YB_ASK_AI_SEARCH_TYPE_NETWORK", "1")'
            )
        except Exception:
            pass
        await self._dismiss_popups(page)

    async def _query_with_page(self, page, ctx, query: str) -> EngineResult:
        """Hot query:reset → warm-up → input → submit → wait → extract.

        2026-05-26:配合 CloakBrowser 用满它的鼠标轨迹模拟 — _start_new_chat 之后
        simulate_browsing 暖身 + human_click 聚焦输入框 + 逐字 keyboard.type 抖动延时,
        让时序信号也像真人(光改指纹不改时序,腾讯还能识别)。
        """
        self._captured_bodies = []  # 清上一轮
        await self._start_new_chat(page)
        await self._enable_web_search(page)

        # 暖身:让鼠标在页面上随机游走 + 微 scroll,跟"真人发问前先看一眼页面"一致。
        try:
            await simulate_browsing(page, duration=random.uniform(2.0, 4.0))
        except Exception as e:
            sys.__stdout__.write(f"[Yuanbao-hot] simulate warning: {e}\n")
            sys.__stdout__.flush()

        input_el = await self._find_input(page)
        if input_el is None:
            return EngineResult(engine=self.name, query=query, error="input not found")
        try:
            # placeholder 兼容两种 attr — yuanbao 站点 2026-05 起改用 `placeholder` 而非 `data-placeholder`,
            # 旧代码只读 data-placeholder 会让登录失效的会话静默继续,最终返回空 answer 没 error。
            placeholder = (
                await input_el.get_attribute("data-placeholder")
                or await input_el.get_attribute("placeholder")
                or ""
            )
            if "登录" in placeholder:
                return EngineResult(
                    engine=self.name, query=query,
                    error=f"login required (placeholder: {placeholder})"
                )
        except Exception:
            pass

        # 人类样式点击 — 鼠标先飘到输入框中心,再 click。
        try:
            box = await input_el.bounding_box()
            if box:
                await human_click(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            else:
                await input_el.click()
        except Exception:
            await input_el.click()
        await human_delay(0.8, 1.6)

        # 逐字 keyboard.type 抖动 60-180ms — 真人中文输入法节奏,
        # fill() 一次性灌全文是最强 bot signature。
        for ch in query:
            await page.keyboard.type(ch, delay=random.randint(60, 180))
        await human_delay(0.5, 1.2)
        await page.keyboard.press("Enter")
        await human_delay(3, 5)
        await self._wait_for_stable_answer(page, max_wait=60, stable_secs=2.5)
        await human_delay(1.0, 2.0)

        answer = await self._extract_answer(page)
        citations = await self._extract_citations(page, answer)
        return EngineResult(engine=self.name, query=query, answer=answer, citations=citations,
            citation_collection=getattr(page, "_geo_citation_collection", {}), source_url=page.url)

    async def search(self, query: str) -> EngineResult:
        import os
        # 2026-05-26:one-shot 也走 CloakBrowser,跟 hot 路径完全一致,debug 看到的
        # 行为就是 production 跑的行为。Xvfb 在生产环境上常驻;本地没 DISPLAY 时
        # 自动起一个。
        if os.name != "nt" and not os.environ.get("DISPLAY"):
            from ..xvfb import start_xvfb
            start_xvfb()
        profile = _pick_profile(platform_filter="Win32" if os.name == "nt" else "Linux x86_64")
        ctx = None
        page = None
        headed_browser = None
        headed_pw = None
        try:
            page, ctx = await create_headed_page(
                "yuanbao",
                profile=profile,
                record_video=self._record_video,
            )
            headed_browser = getattr(page, "_headed_browser", None)
            headed_pw = getattr(page, "_pw_ref", None)

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

            # 暖身 — CloakBrowser 自带指纹/CDP 干净,但 timing chain 还是要做到位。
            try:
                await simulate_browsing(page, duration=random.uniform(2.0, 4.0))
            except Exception as e:
                sys.__stdout__.write(f"[Yuanbao-search] simulate warning: {e}\n")
                sys.__stdout__.flush()

            # Find and fill the input
            input_el = await self._find_input(page)
            if input_el is None:
                await _close_headed(ctx, headed_browser, headed_pw)
                return EngineResult(
                    engine=self.name, query=query, error="input not found"
                )

            # Check for login wall — if input says "请登录后输入内容", abort
            try:
                placeholder = await input_el.get_attribute("data-placeholder") or ""
                if "登录" in placeholder:
                    await _close_headed(ctx, headed_browser, headed_pw)
                    return EngineResult(
                        engine=self.name, query=query,
                        error=f"login required (placeholder: {placeholder})"
                    )
            except Exception:
                pass

            # 人类样式点击 + 逐字输入(同 _query_with_page 那段)
            try:
                box = await input_el.bounding_box()
                if box:
                    await human_click(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                else:
                    await input_el.click()
            except Exception:
                await input_el.click()
            await human_delay(0.8, 1.6)
            for ch in query:
                await page.keyboard.type(ch, delay=random.randint(60, 180))
            await human_delay(0.5, 1.2)

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

            await _close_headed(ctx, headed_browser, headed_pw)

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
            # CloakBrowser 异常时也要把 ctx/browser/pw 都收掉,避免 Xvfb 上残留进程。
            if ctx is not None:
                try:
                    await _close_headed(ctx, headed_browser, headed_pw)
                except Exception:
                    pass
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
        candidates = (
            '[aria-label="新建对话"]',
            '.yb-new-chat-entry__item',
            '.yb-new-chat-entry',
            '[data-desc="new-chat"]',
            "text=新建对话", "text=发起新对话", "text=新对话",
        )
        for selector in candidates:
            try:
                btn = page.locator(selector).first
                if not await btn.is_visible(timeout=800):
                    continue
                await btn.click(timeout=3000)
                await page.wait_for_function(r"""() => {
                    const visible = el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
                    const input = [...document.querySelectorAll('textarea, [contenteditable="true"]')]
                        .some(el => visible(el) && !el.disabled && !el.readOnly
                            && !/登录/.test([el.getAttribute('placeholder'),el.getAttribute('data-placeholder')].join(' ')));
                    const messages = [...document.querySelectorAll('.agent-chat__bubble--ai, .agent-chat__bubble--human, .agent-chat__bubble--user')].filter(visible);
                    return input && messages.length === 0;
                }""", timeout=5000)
                await human_delay(0.3, 0.6)
                return
            except Exception:
                continue
        raise RuntimeError(
            "yuanbao new-chat reset failed — refusing to send query into stale session"
        )

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
        # 元宝 SSE 接口的 Content-Type 不带 charset=utf-8,Playwright 的
        # response.text() 会退到 Latin-1 解码,造成汉字 mojibake("世"→"ä¸–")。
        # 抓 raw bytes 自己按 UTF-8 解,errors='replace' 防极少数非 UTF-8 帧抛错。
        try:
            data = await response.body()
        except Exception:
            return
        if not data:
            return
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
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
        """Read every source entry of this answer before AI verification."""
        from .reference_collector import collect_all_references
        citations, metadata = await collect_all_references(page, "yuanbao", answer)
        page._geo_citation_collection = metadata
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
