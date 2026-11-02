"""Qwen (通义千问) browser adapter — automates www.qianwen.com.

2026-05-18 迁移自 chat.qwen.ai → www.qianwen.com:
- chat.qwen.ai 是阿里出海版,可用邮箱登录
- www.qianwen.com 是千问国内主站,手机号登录,跟用户的扩展插件域名一致

迁移策略:DOM selector 选 "通用 + fallback 链",不写死 tongyi 特定 class —
React Ant Design 类型的 chat 应用通用模式:
  - 输入框:textarea / contenteditable,带 chat-related placeholder
  - 提交:Enter(Shift+Enter 换行)
  - 完成信号:连续 N 秒文本无变化 AND 没有可见的 "停止/Stop" 按钮
  - 答案容器:最后一条 user message 后面的 message bubble

日后稳定下来再针对 tongyi 抓特定 selector 减少 false-positive。
首次 probe 失败时,搜 `[Qwen-probe]` 日志,会打出 stage / count / selector 命中信息.
"""

from __future__ import annotations

import asyncio
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


_QWEN_BLOCK_HOSTS = (
    # 自家域,citation 不收
    "qwen.ai", "qianwen.com", "tongyi.aliyun.com", "aliyun.com",
    "alibabacloud.com", "alicdn.com", "alipay.com", "taobao.com", "tmall.com",
    # 通用埋点/CDN
    "w3.org", "googletagmanager.com", "google-analytics.com",
    "googlesyndication.com", "doubleclick.net", "facebook.net", "analytics",
)

# 即时读取答案容器 innerText(不等元素稳定);candidates 按序取第一个有文本的最后一条。
# locator.inner_text() 在流式重渲染元素上会因稳定性等待超时,故改用 evaluate。
_QWEN_READ_JS = r"""
(sels) => {
  for (const sel of sels) {
    const els = document.querySelectorAll(sel);
    if (els.length) {
      const t = els[els.length - 1].innerText || '';
      if (t.trim()) return { sel, text: t };
    }
  }
  return { sel: null, text: '' };
}
"""

# 中文来源显示名 → 实际 domain(沿用,跟具体引擎无关)
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
}


def _log(msg: str) -> None:
    sys.__stdout__.write(f"[Qwen-probe] {msg}\n")
    sys.__stdout__.flush()


class QwenBrowserAdapter(EngineAdapter):
    name = "通义千问"
    _record_video = False

    def __init__(self):
        import os
        self._record_video = os.environ.get("GEO_RECORD_VIDEO", "").strip() in ("1", "true")

    # www.qianwen.com 入口 — 登录后自动进 chat 页,不写死后缀,让站点自己 redirect。
    CHAT_URL = "https://www.qianwen.com/"

    # 输入框 selector 候选链(按命中优先级)。
    # 现代 React chat 应用要么是 textarea,要么是 contenteditable div。
    INPUT_CANDIDATES = (
        "textarea[placeholder*='提问']",
        "textarea[placeholder*='输入']",
        "textarea[placeholder*='对话']",
        "textarea[placeholder*='Message']",
        "div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true']",
        "textarea",
    )

    # 答案容器候选链 — 抓"最后一条 assistant message"。
    # www.qianwen.com 实测真实 DOM(2026-05-18):
    #   .chat-answers-card-wrap (data-chat-answers-wrap=...) 是单条答案的稳定外壳,
    #   只含 assistant 答案,不含 user 提问。 .answer-common-card 是同条更窄的内层。
    ASSISTANT_CANDIDATES = (
        "[data-chat-answers-wrap]",
        ".chat-answers-card-wrap",
        ".answer-common-card",
        # 通用 fallback(若日后改版,大概率还能撞上一个)
        "[data-message-role='assistant']",
        "[data-role='assistant']",
        "[class*='assistant-message']",
    )

    # 流式中"停止生成"按钮 — 它在,说明还没生成完。
    STOP_BUTTON_CANDIDATES = (
        "button:has-text('停止')",
        "button:has-text('Stop')",
        "[aria-label*='停止']",
        "[aria-label*='Stop']",
        "button[class*='stop']",
    )

    async def is_available(self) -> bool:
        return (await self.verify_session())["status"] == "ok"

    async def verify_session(self) -> dict:
        from ..session_verifier import verify_account_session
        return await verify_account_session(self, "qwen", probe_new_chat=True)

    # 2026-05-26:迁到 CloakBrowser(github.com/CloakHQ/CloakBrowser)。
    # 阿里 chat 端跟其它中文厂一样有指纹/CDP 检测,统一栈方便日后排障。
    async def _create_hot_page(self):
        """通义专用:Xvfb + headed + cloakbrowser。"""
        import os
        if os.name != "nt" and not os.environ.get("DISPLAY"):
            from ..xvfb import start_xvfb
            start_xvfb()
        profile = _pick_profile(platform_filter="Win32" if os.name == "nt" else "Linux x86_64")
        page, ctx = await create_headed_page(
            "qwen",
            profile=profile,
            record_video=self._record_video,
        )
        return page, ctx

    async def _close_hot_page(self, page, ctx) -> None:
        """通义专用:cloakbrowser 的 ctx + patchright fallback 的 browser/pw 都 close."""
        headed_browser = getattr(page, "_headed_browser", None)
        headed_pw = getattr(page, "_pw_ref", None)
        await _close_headed(ctx, headed_browser, headed_pw)

    # D4d(2026-05-18):hot browser protocol —— EngineSession 用 _prepare_page +
    # _query_with_page 复用 page,跟 search() 共享 helper.
    async def _prepare_page(self, page, ctx) -> None:
        """Hot init:goto + 弹窗 + 校验 input 可见(否则视为登录失效).

        故意不挂 network capture(qianwen 的 chat API 含 nav/analytics URL
        会污染 citation,详见 v2 fix).
        """
        await page.goto(self.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
        await human_delay(2, 3)
        _log(f"prepare_page landed at {page.url}")
        await self._dismiss_popups(page)
        input_el = await self._find_input(page, timeout=12000)
        if input_el is None:
            raise RuntimeError("input not visible after prepare — session likely expired")

    async def _query_with_page(self, page, ctx, query: str) -> EngineResult:
        """Hot query:reset → warm-up → input → submit → wait → extract.

        2026-05-26:CloakBrowser 路径加 simulate_browsing 暖身 + human_click 聚焦 +
        逐字 keyboard.type(60-180ms 抖动)— 阿里风控看时序,fill / insert_text
        一次性灌全文都是 bot signature。
        """
        await self._start_new_chat(page)

        try:
            await simulate_browsing(page, duration=random.uniform(2.0, 4.0))
        except Exception as e:
            _log(f"simulate warning: {e}")

        # _find_input 每次重做(reset 后 DOM 可能短暂消失)
        input_el = await self._find_input(page, timeout=8000)
        if input_el is None:
            return EngineResult(engine=self.name, query=query, error="input not visible (tongyi DOM)")
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
        # 校验输入是否真进了 contenteditable —— qwen 新版下逐字 type 常不进 →
        # 提交空内容 → 不出答案(实测 last_len=0 真因)。没进就 fill() 兜底。
        try:
            typed = (await input_el.inner_text(timeout=2000)).strip()
        except Exception:  # noqa: BLE001
            typed = ""
        if not typed or query[:6] not in typed:
            try:
                await input_el.fill(query)
                _log("input via fill() fallback — char-type 未进")
            except Exception:  # noqa: BLE001
                try:
                    await page.keyboard.insert_text(query)
                except Exception:  # noqa: BLE001
                    pass
        await human_delay(0.5, 1.2)
        # 提交:新版 www.qianwen.com 的 contenteditable 下 Enter 不再提交(只换行),
        # 必须点"发送消息"按钮(aria-label 含"发送")。点不到再回落 Enter。
        submitted = False
        for sel in ("button[aria-label*='发送']", "button[aria-label*='Send']",
                    "button[class*='send']"):
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    submitted = True
                    _log(f"submit via button: {sel}")
                    break
            except Exception:
                continue
        if not submitted:
            await page.keyboard.press("Enter")
            _log("submit via Enter (no send button)")

        await human_delay(2, 3)
        assistant_sel = await self._wait_for_stable_answer(
            page, max_wait=180, stable_secs=2.5
        )
        await human_delay(1.0, 2.0)

        answer = await self._extract_answer(page, assistant_sel)
        citations = await self._extract_citations(page, answer, assistant_sel)
        _log(f"hot query: ans_len={len(answer)} cite={len(citations)} sel={assistant_sel!r}")
        return EngineResult(engine=self.name, query=query, answer=answer, citations=citations,
            citation_collection=getattr(page, "_geo_citation_collection", {}), source_url=page.url)

    async def search(self, query: str) -> EngineResult:
        """One-shot:launch → _prepare_page → _query_with_page → save + close.

        共用 hot 协议方法,行为零回归.
        2026-05-26:one-shot 也走 CloakBrowser,跟 hot 路径完全一致。
        """
        import os
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
                "qwen",
                profile=profile,
                record_video=self._record_video,
            )
            headed_browser = getattr(page, "_headed_browser", None)
            headed_pw = getattr(page, "_pw_ref", None)

            await self._prepare_page(page, ctx)
            result = await self._query_with_page(page, ctx, query)

            await save_page_session("qwen", ctx)

            if self._record_video:
                try:
                    from ..video_store import get_video_path
                    result.video_path = await get_video_path(page)
                except Exception:
                    pass

            await _close_headed(ctx, headed_browser, headed_pw)
            return result
        except Exception as e:
            _log(f"search crashed: {type(e).__name__}: {e}")
            if ctx is not None:
                try:
                    await _close_headed(ctx, headed_browser, headed_pw)
                except Exception:
                    pass
            return EngineResult(engine=self.name, query=query, error=str(e))

    async def _find_input(self, page, timeout: float = 10000):
        """逐个 selector 试,返回第一个可见的 input/contenteditable。"""
        # poll 一段时间 — 页面 hydrate 慢
        deadline = timeout
        elapsed = 0
        step = 500
        last_counts: dict[str, int] = {}
        while elapsed < deadline:
            for sel in self.INPUT_CANDIDATES:
                try:
                    loc = page.locator(sel).first
                    cnt = await page.locator(sel).count()
                    last_counts[sel] = cnt
                    if cnt > 0 and await loc.is_visible():
                        _log(f"input hit: {sel} (visible)")
                        return loc
                except Exception:
                    continue
            await asyncio.sleep(step / 1000)
            elapsed += step
        _log(f"input not found after {timeout}ms; counts={last_counts}")
        return None

    # D3(2026-05-18):hot browser 模式下,每次 query 前调一下重置 chat 上下文,
    # 防止上一条 query 的对话被当成 context 影响下一条答案。
    # 当前 search() 还是 one-shot 模式,这个方法暂未被调用,留给 D4 的 EngineSession.
    async def _start_new_chat(self, page) -> None:
        """Click "新建对话" sidebar button to reset conversation.

        www.qianwen.com 实测(2026-05-18 DOM probe):侧栏顶 `<button>` 文本 = "新建对话"
        (注意是"新**建**对话",不是"新对话")。`<button>` 标签罕见所以最稳;text-is
        匹配兜底("新对话" 也保留 in case 改版又改回去).
        """
        candidates = [
            "button:has-text('新建对话')",
            "button:has-text('新对话')",
            "[class*='sideBar']:has-text('新建对话')",
            "text=新建对话",
            "text=新对话",
        ]
        for sel in candidates:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await human_delay(0.5, 1.0)
                    _log(f"new-chat clicked via {sel!r}")
                    return
            except Exception:
                continue
        _log("new-chat button NOT found — needs DOM probe to fix selector")
        # raise 让 EngineSession 归 error,runner 不抽竞品,避免旧会话上下文污染数据
        raise RuntimeError(
            "qwen new-chat button not found — refusing to send query into stale session"
        )

    async def _dismiss_popups(self, page) -> None:
        for sel in [
            "text=我知道了",
            "text=同意",
            "text=Accept",
            "text=接受全部",
            "text=不再提示",
            "[aria-label='close']",
            "[aria-label='Close']",
            ".ant-modal-close",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    await human_delay(0.3, 0.6)
            except Exception:
                continue

    _STATUS_PHRASES = (
        "正在读取来源",
        "正在搜索",
        "正在思考",
        "正在生成",
        "思考中",
        "搜索中",
        "读取中",
        "Searching",
        "Reading sources",
        "Thinking",
    )

    def _is_status_only(self, text: str) -> bool:
        if not text:
            return True
        stripped = text.strip()
        if len(stripped) < 30 and any(p in stripped for p in self._STATUS_PHRASES):
            return True
        return False

    async def _wait_for_stable_answer(
        self, page, max_wait: float = 180.0, stable_secs: float = 2.5
    ) -> str | None:
        """轮询找到的 assistant selector,等其 inner_text 稳定 + 无停止按钮。

        返回胜出的 selector(后续 _extract_answer / _extract_citations 复用),
        或 None(超时)。
        """
        poll_interval = 0.6
        last_text = ""
        last_len = 0
        stable_since = None
        elapsed = 0.0
        winning_sel: str | None = None

        while elapsed < max_wait:
            # 用 page.evaluate 直接读 innerText:locator.inner_text() 在流式不断重渲染的
            # 元素上会因"等待元素稳定"而超时 → cur 永远空(实测 last_len=0 真因)。
            # evaluate 是即时快照,不等稳定,和能跑通的 probe 一致。
            cur = ""
            sel_hit = None
            try:
                r = await page.evaluate(_QWEN_READ_JS, list(self.ASSISTANT_CANDIDATES))
                cur = (r or {}).get("text") or ""
                sel_hit = (r or {}).get("sel")
            except Exception:  # noqa: BLE001
                cur = ""
                sel_hit = None

            # 检查 "停止生成" 按钮是否还在
            stop_visible = False
            for sb in self.STOP_BUTTON_CANDIDATES:
                try:
                    if await page.locator(sb).first.is_visible(timeout=200):
                        stop_visible = True
                        break
                except Exception:
                    continue

            # 稳定判定改为"长度不再增长"(qwen 新版答案尾部挂动态元素,精确文本比对
            # 永不相等 → 卡满 max_wait)。文本停止变长 + 非状态占位 + 无停止按钮 = 生成完成。
            cur_len = len(cur.strip())
            if (
                cur
                and cur_len > 8
                and cur_len <= last_len
                and not self._is_status_only(cur)
                and not stop_visible
            ):
                if stable_since is None:
                    stable_since = elapsed
                elif elapsed - stable_since >= stable_secs:
                    winning_sel = sel_hit or winning_sel
                    _log(f"stable@{elapsed:.1f}s len={cur_len} sel={winning_sel!r}")
                    return winning_sel
            else:
                if cur_len > last_len:
                    last_len = cur_len
                    winning_sel = sel_hit or winning_sel
                last_text = cur
                stable_since = None

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        _log(f"wait timeout @ {max_wait}s, last_len={len(last_text)} stop_visible={stop_visible}")
        return winning_sel  # 即便超时也返回找到的 selector,extract 还能抢救

    async def _extract_answer(self, page, assistant_sel: str | None) -> str:
        # 同样用 page.evaluate 即时读取(locator.inner_text 在流式元素上会超时)
        sels = [assistant_sel] if assistant_sel else []
        sels.extend(s for s in self.ASSISTANT_CANDIDATES if s != assistant_sel)
        sels = [s for s in sels if s]
        try:
            r = await page.evaluate(_QWEN_READ_JS, sels)
            raw = (r or {}).get("text") or ""
            if raw.strip():
                cleaned = self._scrub_status_noise(raw)
                if cleaned.strip():
                    return cleaned
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _scrub_status_noise(self, raw: str) -> str:
        if not raw:
            return ""
        cleaned = raw
        for noise in (
            "正在搜索网络", "正在读取来源", "正在思考", "正在生成", "正在搜索",
            "跳过", "已深度思考", "已搜索网络", "已经完成思考",
        ):
            cleaned = cleaned.replace(noise, "")
        cleaned = re.sub(r"\.{3,}", "", cleaned)
        cleaned = re.sub(r"…+", "", cleaned)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    async def _extract_citations(self, page, answer: str, assistant_sel: str | None) -> List[Citation]:
        """Read every source entry of this answer before AI verification."""
        from .reference_collector import collect_all_references
        citations, metadata = await collect_all_references(page, "qwen", answer, assistant_sel)
        page._geo_citation_collection = metadata
        return citations
