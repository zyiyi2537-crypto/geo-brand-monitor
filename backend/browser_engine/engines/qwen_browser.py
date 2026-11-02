"""Qwen (通义千问) browser adapter — automates chat.qwen.ai.

Qwen Web UI 自动判断是否需要联网搜索,搜索时会显示
`qwen-chat-thinking-status-card-title-animate` 动画卡片(文案"正在搜索网络"),
旁边是"跳过"按钮(不要点)。streaming 结束后卡片的 animate class 消失并显示
"已搜索 N 条"静态文案,message 容器里填充实际答案。

无 Stop/停止 按钮,所以等待策略用 "assistant 消息 inner_text 稳定 N 秒"
(engine-agnostic,不依赖 Qwen 特定 DOM 细节)。

Citation 提取:Qwen 的内联引用不是 `<a href>`,而是
`<span class="qwen-markdown-citation">` 包 `.qwen-chat-markdown-tokens-hostname`
显示 hostname(例如 `zh.wikipedia.org`)或中文来源名(例如 `百度`、`四川在线`)。
完整 URL 只在 tooltip/展开的 source drawer 里,tooltip 非 hover 不渲染;
为避免一条条 hover 拖慢抓取,采取 hostname→URL 合成策略,并对常见中文来源
做一层 display-name → domain 映射。
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import List

from ..browser import create_stealth_page, human_delay, save_page_session
from .base import Citation, EngineAdapter, EngineResult, extract_urls_from_text


_QWEN_BLOCK_HOSTS = (
    "qwen.ai", "aliyun.com", "alibabacloud.com", "alicdn.com", "w3.org",
    "googletagmanager.com", "google-analytics.com", "googlesyndication.com",
    "doubleclick.net", "facebook.net", "analytics",
)

# 中文来源显示名 → 实际 domain。Qwen 常把 baidu.com 等渲染成中文品牌名,
# 这里做一层映射,未命中的中文名保留原样当 domain 用(聚合仍能工作)。
_CN_DISPLAY_TO_DOMAIN = {
    "百度": "baidu.com",
    "百度百科": "baike.baidu.com",
    "百度知道": "zhidao.baidu.com",
    "百度文库": "wenku.baidu.com",
    "百家号": "baijiahao.baidu.com",
    "搜狐": "sohu.com",
    "新浪": "sina.com.cn",
    "新浪财经": "finance.sina.com.cn",
    "新浪科技": "tech.sina.com.cn",
    "网易": "163.com",
    "网易新闻": "news.163.com",
    "腾讯": "qq.com",
    "腾讯新闻": "news.qq.com",
    "知乎": "zhihu.com",
    "微博": "weibo.com",
    "今日头条": "toutiao.com",
    "澎湃新闻": "thepaper.cn",
    "界面新闻": "jiemian.com",
    "第一财经": "yicai.com",
    "财联社": "cls.cn",
    "36氪": "36kr.com",
    "虎嗅": "huxiu.com",
    "钛媒体": "tmtpost.com",
    "人民网": "people.com.cn",
    "人民日报": "people.com.cn",
    "新华网": "news.cn",
    "央视网": "cctv.com",
    "中国新闻网": "chinanews.com.cn",
    "环球网": "huanqiu.com",
    "光明网": "gmw.cn",
    "四川在线": "scol.com.cn",
    "南方日报": "nfnews.com",
    "南方周末": "infzm.com",
    "经济观察报": "eeo.com.cn",
    "证券时报": "stcn.com",
    "中国证券报": "cs.com.cn",
    "每日经济新闻": "nbd.com.cn",
    "21世纪经济报道": "21jingji.com",
    "中关村在线": "zol.com.cn",
    "太平洋电脑网": "pconline.com.cn",
    "爱卡汽车": "xcar.com.cn",
    "汽车之家": "autohome.com.cn",
    "懂车帝": "dongchedi.com",
    "易车": "yiche.com",
}


def _hostname_to_citation(raw: str, position: int) -> Citation | None:
    h = (raw or "").strip()
    if not h:
        return None
    # 真实 hostname(包含 "." 或就是 localhost)
    if "." in h and not any(c in h for c in (" ", "\n", "\t")):
        domain = h[4:] if h.startswith("www.") else h
        if any(b in domain for b in _QWEN_BLOCK_HOSTS):
            return None
        return Citation(
            url=f"https://{h}", domain=domain, title=h, position=position
        )
    # 中文展示名 → domain 映射
    mapped = _CN_DISPLAY_TO_DOMAIN.get(h)
    if mapped:
        return Citation(
            url=f"https://{mapped}", domain=mapped, title=h, position=position
        )
    # 未知中文展示名(罕见,未命中映射表):丢弃 — 下游会以 url 重建 Citation,
    # 传空 url 进去会让 domain 也丢失,还不如不要这一条。
    return None


class QwenBrowserAdapter(EngineAdapter):
    name = "通义千问"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    CHAT_URL = "https://chat.qwen.ai/"
    ASSISTANT_SEL = ".qwen-chat-message-assistant"
    # 只匹配答案正文,不包含 thinking status card 的文案
    ANSWER_SEL = ".qwen-chat-message-assistant .response-message-content"
    THINKING_ANIM_SEL = ".qwen-chat-thinking-status-card-title-animate"

    async def is_available(self) -> bool:
        try:
            page, ctx = await create_stealth_page("qwen")
            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=15000)
            logged_in = await page.locator("textarea.message-input-textarea").count() > 0
            await ctx.close()
            return logged_in
        except Exception:
            return False

    async def search(self, query: str) -> EngineResult:
        try:
            page, ctx = await create_stealth_page("qwen", record_video=self._record_video)

            # 网络抓包:Qwen 的 chat API 流里带着完整 source URL 的 JSON。
            # 在 goto 前注册 listener,覆盖整个请求生命周期。
            captured_bodies: List[str] = []
            self._captured_bodies = captured_bodies

            def _on_response(response):
                url_l = response.url.lower()
                if not any(kw in url_l for kw in ("/api/", "chat", "completion", "search")):
                    return
                # 避免把静态资源(图/字体)吞下来
                ctype = (response.headers.get("content-type") or "").lower()
                if ctype and not any(
                    t in ctype for t in ("json", "event-stream", "text/plain", "text/html")
                ):
                    return
                try:
                    asyncio.create_task(self._capture_body(response, captured_bodies))
                except Exception:
                    pass

            page.on("response", _on_response)

            await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            await human_delay(2, 3)

            await self._dismiss_popups(page)

            input_el = page.locator("textarea.message-input-textarea").first
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

            # ── streaming-done 检测 ──
            # 轮询 `.response-message-content` inner_text,连续 stable_secs
            # 未变 & thinking 动画已消失 → 视为生成完成。
            await human_delay(2, 3)
            await self._wait_for_stable_answer(page, max_wait=60, stable_secs=2.0)

            await human_delay(1.0, 2.0)

            answer = await self._extract_answer(page)
            citations = await self._extract_citations(page, answer)

            await save_page_session("qwen", ctx)

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
        for sel in [
            "text=我知道了",
            "text=同意",
            "text=Accept",
            "text=接受全部",
            "[aria-label='close']",
            "[aria-label='Close']",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await human_delay(0.3, 0.8)
            except Exception:
                continue

    async def _wait_for_stable_answer(
        self, page, max_wait: float = 180.0, stable_secs: float = 2.0
    ) -> None:
        """轮询**答案正文**(response-message-content) inner_text,连续 stable_secs 未变即返回。

        关键:必须盯答案正文,不能盯整个 assistant 容器。
        thinking 阶段容器里只有状态卡文案("已经完成思考" 等),
        如果 stability 检查命中状态卡,会在答案开始 stream 之前就 early-return。
        """
        poll_interval = 0.6
        last_text = ""
        stable_since = None
        elapsed = 0.0
        while elapsed < max_wait:
            try:
                ans_els = await page.locator(self.ANSWER_SEL).all()
                if ans_els:
                    cur = await ans_els[-1].inner_text()
                else:
                    cur = ""
            except Exception:
                cur = last_text

            # 必须有实质内容 (>8 字符,避过 "思考中..." 这类占位)
            if cur and len(cur.strip()) > 8 and cur == last_text:
                if stable_since is None:
                    stable_since = elapsed
                elif elapsed - stable_since >= stable_secs:
                    # 再确认 thinking 动画已停
                    try:
                        anim_count = await page.locator(self.THINKING_ANIM_SEL).count()
                    except Exception:
                        anim_count = 0
                    if anim_count == 0:
                        return
                    stable_since = None
            else:
                last_text = cur
                stable_since = None

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

    async def _extract_answer(self, page) -> str:
        """抓最后一条 response-message-content 的 text。

        直接拿答案正文,绕开 thinking status card 的 "已搜索 N 条" / "已经完成思考" 等噪声。
        若答案正文为空(罕见边界),回退到 ASSISTANT_SEL 容器 + 噪声剔除。
        """
        # 首选:直接从答案正文抓
        try:
            ans_els = await page.locator(self.ANSWER_SEL).all()
            if ans_els:
                raw = await ans_els[-1].inner_text()
                if raw and raw.strip():
                    return re.sub(r"\n{3,}", "\n\n", raw).strip()
        except Exception:
            pass

        # 回退:整个 assistant 容器 + 噪声剔除
        try:
            assist_els = await page.locator(self.ASSISTANT_SEL).all()
            if not assist_els:
                return ""
            raw = await assist_els[-1].inner_text()
        except Exception:
            return ""

        cleaned = raw
        for noise in (
            "正在搜索网络",
            "跳过",
            "已深度思考",
            "已搜索网络",
            "已经完成思考",
        ):
            cleaned = cleaned.replace(noise, "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned

    async def _capture_body(self, response, bucket: List[str]) -> None:
        """Read a response body, stash text containing citation-shaped JSON."""
        try:
            text = await response.text()
        except Exception:
            return
        if not text:
            return
        # 只保留看起来带链接信息的 body,避开鉴权/无用响应
        if "http" not in text:
            return
        # 单条 body 最多 400KB,防止 SSE 巨流吞内存
        bucket.append(text[:400_000])

    async def _extract_citations(self, page, answer: str) -> List[Citation]:
        """Additive 多路径提取,所有路径都跑 + 全局 seen_keys 去重。

        Path 优先级(早出现的路径决定 citation 的 position 序号):
          1. 网络抓包 — Qwen chat API 流里的 JSON 通常自带完整 URL(最权威)
          2. Source drawer — 点 "+N" 折叠卡,抓 drawer 里新出现的 `<a href>`
          3. Assistant 容器内原生 `<a href>`(少数变体 UI)
          4. 内联 `.qwen-markdown-citation` hostname → 合成 URL(兜底补集)
          5. 答案正文里的裸 URL
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
            # 重新按插入顺序编位置号
            citations.append(
                Citation(
                    url=cit.url,
                    domain=cit.domain,
                    title=cit.title,
                    snippet=cit.snippet,
                    position=len(citations) + 1,
                )
            )

        # ── 1) Network-capture: 从抓到的 API 响应体里提 URL
        net_urls: List[str] = []
        try:
            for body in getattr(self, "_captured_bodies", []) or []:
                # 优先匹配 JSON 的 url/link/href 字段
                for m in re.finditer(
                    r'"(?:url|link|href|source_url|web_url|redirect_url)"\s*:\s*"'
                    r'(https?://[^"\\\s]+)"',
                    body,
                ):
                    net_urls.append(m.group(1))
                # 再兜底扫所有 JSON-escaped URL token(SSE chunks 有时转义)
                for m in re.finditer(r'https?:\\?/\\?/[^\s"<>\\]{4,500}', body):
                    u = m.group(0).replace("\\/", "/")
                    net_urls.append(u)
        except Exception:
            pass
        # 去重保顺序 + 过滤内网/自家域
        net_urls = list(dict.fromkeys(net_urls))
        for u in net_urls:
            if any(b in u for b in _QWEN_BLOCK_HOSTS):
                continue
            if not u.startswith("http"):
                continue
            _add(Citation.from_url(u))

        # ── 2) DOM: 内联 hostnames(备用映射 + probe 信号)
        try:
            inline_hostnames = await page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll(
                        '.qwen-chat-message-assistant .qwen-markdown-citation '
                        + '.qwen-chat-markdown-tokens-hostname'
                    ).forEach(el => {
                        const t = (el.innerText || el.textContent || '').trim();
                        if (t) out.push(t);
                    });
                    return out;
                }"""
            ) or []
        except Exception:
            inline_hostnames = []

        # ── 3) DOM: 点击 source drawer(多策略点击)
        drawer_links: List[dict] = []
        try:
            drawer_links = await self._open_source_drawer_and_collect(page)
        except Exception as e:
            sys.__stdout__.write(
                f"[Qwen-probe] drawer open failed: {type(e).__name__}: {e}\n"
            )
            sys.__stdout__.flush()

        for link in drawer_links:
            href = link.get("href") or ""
            title = link.get("title") or ""
            if not href.startswith("http"):
                continue
            if any(b in href for b in _QWEN_BLOCK_HOSTS):
                continue
            _add(Citation.from_url(href, title=title))

        # ── 4) Assistant 容器原生 `<a href>`(additive 补集)
        try:
            links = await page.locator(f"{self.ASSISTANT_SEL} a[href^='http']").all()
            for link in links:
                try:
                    href = await link.get_attribute("href")
                    title = await link.inner_text()
                except Exception:
                    continue
                if not href or not href.startswith("http"):
                    continue
                if any(b in href for b in _QWEN_BLOCK_HOSTS):
                    continue
                _add(Citation.from_url(href, title=title))
        except Exception:
            pass

        # ── 5) 内联 hostname → 合成 URL(补 drawer/网络没抓到的)
        for h in inline_hostnames:
            _add(_hostname_to_citation(h, position=0))

        # ── 6) 答案正文裸 URL(最后兜底)
        for u in extract_urls_from_text(answer):
            if any(b in u for b in _QWEN_BLOCK_HOSTS):
                continue
            _add(Citation.from_url(u))

        sys.__stdout__.write(
            f"[Qwen-probe] net_urls={len(net_urls)} "
            f"inline_hostnames={len(inline_hostnames)} "
            f"drawer_links={len(drawer_links)} citations={len(citations)}\n"
        )
        sys.__stdout__.flush()

        return citations

    async def _open_source_drawer_and_collect(self, page) -> List[dict]:
        """Click the "+N" source fold card, read URLs from the drawer, close it.

        Qwen uses React synthetic events, so Playwright's native `locator.click()`
        sometimes "clicks" but the handler doesn't fire. We try a ladder:
          1. locator.click()
          2. locator.click(force=True)
          3. JS `.click()` on the DOM element
          4. JS `dispatchEvent(new MouseEvent('click', {bubbles:true}))`
        First strategy that actually yields new `<a href>` wins.
        """
        # Card 本体 + count 徽章 两个候选元素,按序尝试
        card_sel = (
            f"{self.ASSISTANT_SEL} "
            ".qwen-chat-package-comp-source-list .qwen-chat-search-card"
        )
        badge_sel = f"{self.ASSISTANT_SEL} .qwen-chat-fold-source-count"

        try:
            has_card = await page.locator(card_sel).count() > 0
        except Exception:
            has_card = False
        if not has_card:
            return []

        # Snapshot existing anchors so we can diff
        try:
            pre_hrefs = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                       .map(a => a.href).filter(h => h.startsWith('http'))"""
            ) or []
        except Exception:
            pre_hrefs = []
        pre_set = list(set(pre_hrefs))

        # 先滚到可见
        try:
            await page.locator(card_sel).last.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass

        async def _diff_new_anchors() -> List[dict]:
            try:
                return await page.evaluate(
                    """(preHrefs) => {
                        const pre = new Set(preHrefs);
                        const seen = new Set();
                        const out = [];
                        document.querySelectorAll('a[href]').forEach(a => {
                            const href = a.href;
                            if (!href.startsWith('http')) return;
                            if (pre.has(href)) return;
                            if (seen.has(href)) return;
                            seen.add(href);
                            out.push({
                                href,
                                title: (a.innerText || a.textContent || '').trim().slice(0, 200),
                            });
                        });
                        return out;
                    }""",
                    pre_set,
                ) or []
            except Exception:
                return []

        strategies = [
            ("pw_click_card",    lambda: page.locator(card_sel).last.click(timeout=2000)),
            ("pw_click_badge",   lambda: page.locator(badge_sel).last.click(timeout=2000)),
            ("pw_click_forced",  lambda: page.locator(card_sel).last.click(timeout=2000, force=True)),
            ("js_click",         lambda: page.evaluate(
                f"""() => {{
                    const els = document.querySelectorAll({card_sel!r});
                    if (els.length) els[els.length - 1].click();
                }}"""
            )),
            ("js_dispatch",      lambda: page.evaluate(
                f"""() => {{
                    const els = document.querySelectorAll({card_sel!r});
                    if (!els.length) return;
                    const el = els[els.length - 1];
                    ['mousedown', 'mouseup', 'click'].forEach(type => {{
                        el.dispatchEvent(new MouseEvent(type, {{
                            bubbles: true, cancelable: true, view: window
                        }}));
                    }});
                }}"""
            )),
        ]

        drawer_links: List[dict] = []
        winning_strategy = None
        for name, action in strategies:
            try:
                await action()
            except Exception:
                continue
            # Poll up to 2s after each attempt
            for _ in range(7):
                await asyncio.sleep(0.3)
                drawer_links = await _diff_new_anchors()
                if drawer_links:
                    winning_strategy = name
                    break
            if drawer_links:
                break

        if winning_strategy:
            sys.__stdout__.write(
                f"[Qwen-probe] drawer opened via {winning_strategy} "
                f"(new_links={len(drawer_links)})\n"
            )
        else:
            sys.__stdout__.write(
                "[Qwen-probe] drawer click: all 5 strategies yielded 0 new links\n"
            )
        sys.__stdout__.flush()

        # Close drawer so the next query starts clean
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        return drawer_links
