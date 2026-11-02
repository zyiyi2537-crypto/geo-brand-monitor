"""qwen 单次查询 —— 独立进程跑(browser-service 进程内 context 与常驻 hot 浏览器冲突,
答案读不出;独立进程的同一流程稳定可出网页答案,实测反复验证)。

被 main.run_qwen_browser 用 subprocess 调用:
  <venv>/python app/qwen_query.py "<query>"
继承 browser-service 的 env(ENGINE_SESSION_POOL_URL / ENGINE_SESSION_SERVICE_TOKEN),
create_stealth_page 据此 check-out 账号;结束时 check-in。最后一行 stdout = JSON 结果。
"""
import asyncio
import json
import sys

sys.path.insert(0, "/opt/browser-service")

from app import engine_selectors  # noqa: E402
from app.browser import create_stealth_page  # noqa: E402
from app.session_store import report_session_outcome  # noqa: E402
from app.engines.qwen_browser import (  # noqa: E402
    _QWEN_READ_JS, _QWEN_BLOCK_HOSTS, QwenBrowserAdapter,
)

# 选择器/API/URL 全从 engine_selectors 配置取(自愈 Phase 1:改版改配置不改代码)
_CFG = engine_selectors.get("qwen")
# 自愈验证用:QWEN_SELECTOR_OVERRIDE(JSON)临时覆盖配置,不落库 —— 验证提议是否真能跑通
import os as _os  # noqa: E402
_ov = (_os.environ.get("QWEN_SELECTOR_OVERRIDE") or "").strip()
if _ov:
    try:
        _CFG = {**_CFG, **{k: v for k, v in json.loads(_ov).items() if v}}
    except Exception:  # noqa: BLE001
        pass
_URL = _CFG.get("url", "https://www.qianwen.com/")
INPUT_SELS = tuple(_CFG.get("input_sels") or [])
SEND_SELS = tuple(_CFG.get("send_sels") or [])
ANSWER_SELS = list(_CFG.get("answer_sels") or [])
_CHAT_API = _CFG.get("chat_api", "chat2.qianwen.com/api/v2/chat")


def _resolve_host_ip() -> str:
    """解析本机(worker)出口 IP —— qwen 不走代理,出口即所在 worker 的 IP。
    ipify 国内不通 → 兜底 ipip.net / ipinfo。"""
    import re as _re
    import urllib.request as _u
    for url in ("https://ipinfo.io/ip", "https://myip.ipip.net", "https://api.ipify.org"):
        try:
            with _u.urlopen(url, timeout=6) as r:
                m = _re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", r.read().decode("utf-8", "replace"))
            if m:
                return m.group(1)
        except Exception:  # noqa: BLE001
            continue
    return ""


def _parse_qwen_citations(body: str) -> list:
    """从 chat2 SSE 流里挖 web_source 引用(url/title)。每个 data: 行是完整 JSON 事件,
    递归找 type==web_source 的 dict。和 deepseek 解析 search_results 同思路。"""
    from urllib.parse import urlparse
    cites, seen = [], set()
    for chunk in body.split("data:"):
        chunk = chunk.strip()
        if not chunk.startswith("{"):
            continue
        try:
            obj = json.loads(chunk)
        except Exception:  # noqa: BLE001
            continue
        stack = [obj]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if x.get("type") == "web_source" and x.get("url", "").startswith("http"):
                    u = x["url"]
                    if u not in seen and not any(b in u for b in _QWEN_BLOCK_HOSTS):
                        seen.add(u)
                        cites.append({"url": u, "domain": urlparse(u).netloc,
                                      "title": x.get("title") or x.get("name") or "",
                                      "snippet": x.get("snippet") or x.get("summary") or "",
                                      "position": len(cites) + 1})
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return cites


async def run(query: str) -> dict:
    out = {"engine": "qwen", "query": query, "answer": "", "citations": [], "error": None}
    adapter = QwenBrowserAdapter()
    try:
        page, ctx = await create_stealth_page("qwen")
    except Exception as e:  # noqa: BLE001
        out["error"] = f"launch: {e}"[:200]
        return out
    chat_responses = []  # 捕获 completion SSE 响应(引用源)

    def _on_resp(resp):
        try:
            if _CHAT_API in resp.url and resp.request.method == "POST":
                chat_responses.append(resp)
        except Exception:  # noqa: BLE001
            pass

    page.on("response", _on_resp)
    try:
        await page.goto(_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)
        target = None
        for sel in INPUT_SELS:
            try:
                if await page.locator(sel).first.is_visible(timeout=2000):
                    target = page.locator(sel).first
                    break
            except Exception:  # noqa: BLE001
                continue
        if target is None:
            report_session_outcome("qwen", result="login_lost")
            out["error"] = "input not found (session likely expired)"
            return out
        await target.click()
        await asyncio.sleep(0.5)
        try:
            await target.fill(query)
        except Exception:  # noqa: BLE001
            await page.keyboard.insert_text(query)
        await asyncio.sleep(1)
        sent = False
        for sel in SEND_SELS:
            try:
                b = page.locator(sel).first
                if await b.is_visible(timeout=1500):
                    await b.click()
                    sent = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not sent:
            await page.keyboard.press("Enter")
        # 先等一段(qwen 提交后有"思考/搜索"停顿期,过早轮询会在停顿处误判"稳定"
        # 而 break,拿到空/状态文本 —— probe 固定 sleep 45s 能出 568 字正因如此)。
        await asyncio.sleep(18)
        # 再轮询到长度稳定:要求答案够长(>60)+ 非状态占位 + 连续 4s 不再变长。
        cands = ANSWER_SELS or list(adapter.ASSISTANT_CANDIDATES)
        last_len, stable_since, el, cur = 0, None, 18.0, ""
        while el < 95:
            try:
                r = await page.evaluate(_QWEN_READ_JS, cands)
                cur = (r or {}).get("text") or ""
            except Exception:  # noqa: BLE001
                cur = ""
            cl = len(cur.strip())
            if cl > 60 and cl <= last_len and not adapter._is_status_only(cur):
                if stable_since is None:
                    stable_since = el
                elif el - stable_since >= 4:
                    break
            else:
                if cl > last_len:
                    last_len = cl
                stable_since = None
            await asyncio.sleep(1.0)
            el += 1.0
        answer = adapter._scrub_status_noise(cur) if cur else ""
        # 引用:从拦截的 completion SSE 流解析 web_source(qwen 联网时引用在 API 流里,
        # DOM 抓不到;同 deepseek 拦后端拿结构化引用)。取最完整的一条响应体。
        cites = []
        best_body = ""
        for r in chat_responses:
            try:
                b = await r.text()
            except Exception:  # noqa: BLE001
                continue
            if len(b) > len(best_body):
                best_body = b
        if best_body:
            try:
                cites = _parse_qwen_citations(best_body)
            except Exception:  # noqa: BLE001
                cites = []
        report_session_outcome("qwen", result="success" if answer else "empty_answer",
                               exit_ip=_resolve_host_ip() or None)
        out["answer"] = answer
        out["citations"] = cites
        out["error"] = None if answer else "empty_answer"
    except Exception as e:  # noqa: BLE001
        report_session_outcome("qwen", result="crash", error_msg=str(e)[:200])
        out["error"] = str(e)[:200]
    finally:
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass
    return out


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "测试"
    res = asyncio.run(run(q))
    print(json.dumps(res, ensure_ascii=False))
