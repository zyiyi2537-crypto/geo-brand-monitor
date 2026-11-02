"""自愈结构探针(browser-agent Phase 2)—— 独立子进程跑(同 qwen_query 的原因:
进程内 create_stealth_page 与常驻 hot 浏览器冲突)。

对某引擎:开页 → 发 canary → 抓页面结构(可交互元素 + 候选答案容器 + completion 类
网络 API)→ 输出紧凑 JSON 供 LLM 提议选择器。不改任何状态、纯只读探测。

用法: <venv>/python app/heal_probe.py <engine> [url]
"""
import asyncio
import json
import sys

sys.path.insert(0, "/opt/browser-service")
from app import engine_selectors  # noqa: E402
from app.browser import create_stealth_page  # noqa: E402

STRUCT_JS = r"""
() => {
  const out = {interactive: [], answer_candidates: []};
  const seen = new Set();
  // 可交互:button / contenteditable / textarea / role=button,带 text+aria
  document.querySelectorAll("button,[role='button'],[contenteditable='true'],textarea,input")
    .forEach(e => {
      const r = e.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      const txt = (e.innerText || '').trim().slice(0, 24);
      const aria = (e.getAttribute('aria-label') || '').slice(0, 24);
      const cls = (typeof e.className === 'string' ? e.className : '').slice(0, 50);
      const k = e.tagName + txt + aria + cls;
      if (seen.has(k)) return; seen.add(k);
      out.interactive.push({tag: e.tagName.toLowerCase(), text: txt, aria,
        cls, editable: e.getAttribute('contenteditable') === 'true',
        role: e.getAttribute('role') || ''});
    });
  // 候选答案容器:innerText 较长且不含大块子 div(叶子级长文本)
  const longs = [];
  document.querySelectorAll('div,article,section').forEach(e => {
    const t = (e.innerText || '').trim();
    if (t.length < 120) return;
    const cls = (typeof e.className === 'string' ? e.className : '');
    const data = Array.from(e.attributes||[]).filter(a=>a.name.startsWith('data-')).map(a=>a.name).join(',');
    longs.push({cls: cls.slice(0,60), data: data.slice(0,60), len: t.length, preview: t.slice(0,60)});
  });
  out.answer_candidates = longs.sort((a,b)=>b.len-a.len).slice(0, 12);
  return out;
}
"""


async def main():
    engine = sys.argv[1] if len(sys.argv) > 1 else "qwen"
    cfg = engine_selectors.get(engine)
    url = sys.argv[2] if len(sys.argv) > 2 else cfg.get("url", "")
    out = {"engine": engine, "url": url, "interactive": [],
           "answer_candidates": [], "apis": [], "error": None}
    if not url:
        out["error"] = "no url for engine"
        print(json.dumps(out, ensure_ascii=False)); return
    page, ctx = await create_stealth_page(engine)
    apis = []

    def on_resp(resp):
        try:
            if resp.request.method == "POST":
                u = resp.url
                ct = resp.headers.get("content-type", "")
                if "stream" in ct or "json" in ct:
                    apis.append((u, ct, resp))
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)
        # 找输入并发 canary(用配置的 input/send;没有就通用)
        target = None
        for sel in (cfg.get("input_sels") or
                    ["div[contenteditable='true']", "textarea"]):
            try:
                if await page.locator(sel).first.is_visible(timeout=1500):
                    target = page.locator(sel).first; break
            except Exception:
                continue
        if target is not None:
            await target.click(); await asyncio.sleep(0.4)
            try:
                await target.fill("2026年最新国产手机推荐")
            except Exception:
                await page.keyboard.insert_text("2026年最新国产手机推荐")
            await asyncio.sleep(0.8)
            sent = False
            for sel in (cfg.get("send_sels") or ["button[aria-label*='发送']"]):
                try:
                    b = page.locator(sel).first
                    if await b.is_visible(timeout=1200):
                        await b.click(); sent = True; break
                except Exception:
                    continue
            if not sent:
                await page.keyboard.press("Enter")
            await asyncio.sleep(40)
        struct = await page.evaluate(STRUCT_JS)
        out["interactive"] = struct.get("interactive", [])
        out["answer_candidates"] = struct.get("answer_candidates", [])
        # 网络 API:取含答案/引用迹象的(body 关键字),压缩
        for u, ct, resp in apis:
            kw = []
            try:
                body = await resp.text()
            except Exception:
                body = ""
            low = body.lower()
            for k in ("web_source", "search_result", "\"url\"", "snippet", "messages", "\"content\""):
                if k in low:
                    kw.append(k)
            if kw or "stream" in ct:
                out["apis"].append({"url": u[:120], "ctype": ct, "len": len(body),
                                    "keywords": kw})
        out["apis"] = sorted(out["apis"], key=lambda x: -x["len"])[:8]
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    finally:
        try:
            await ctx.close()
        except Exception:
            pass
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
