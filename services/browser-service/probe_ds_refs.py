"""One-shot DeepSeek reference-panel DOM probe.

Mirrors the production query path (create_headed_page + _prepare_page +
_query_with_page) but overrides _extract_citations to FIRST:
  1. enumerate link-dense containers (baseline, panel still collapsed)
  2. click the "已搜索/已阅读 N 个网页" reference bar
  3. wait, re-enumerate, dump expanded body HTML

Does NOT call save_page_session — leaves the live deepseek.json untouched.

Run on vm03:
  cd /opt/browser-service && DISPLAY=:99 ./venv/bin/python probe_ds_refs.py
"""
from __future__ import annotations

import asyncio
import os
import sys

# Load .env into os.environ BEFORE importing app modules so session_store sees
# POOL_URL/POOL_TOKEN and checks out a HEALTHY pooled account (not the stale
# local deepseek.json). Parse leniently; secrets never printed.
_envf = "/opt/browser-service/.env"
if os.path.exists(_envf):
    for line in open(_envf, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")

from app.browser import create_stealth_page
from app.engines.deepseek_browser import DeepSeekBrowserAdapter
from app.session_store import _pool_enabled

print(f"[PROBE] pool_enabled={_pool_enabled()}", file=sys.__stdout__, flush=True)

QUERY = "2025年中国新能源汽车销量排名前十的品牌有哪些?"

ENUM_JS = r"""() => {
  const isExt = (h) => h && /^https?:/.test(h) && !h.includes('deepseek.com');
  // link-dense containers
  const out = [];
  document.querySelectorAll('*').forEach(el => {
    const links = [...el.querySelectorAll('a[href]')].filter(a => isExt(a.getAttribute('href')));
    // count only elements whose DIRECT subtree adds links (avoid huge ancestors dominating)
    if (links.length >= 3) {
      out.push({
        tag: el.tagName,
        cls: (typeof el.className === 'string' ? el.className : '').slice(0,140),
        n: links.length,
        depth: (() => { let d=0,p=el; while(p){d++;p=p.parentElement;} return d; })(),
        sample: links.slice(0,3).map(a => ({
          href: a.getAttribute('href'),
          txt: (a.innerText||'').trim().slice(0,60),
        })),
      });
    }
  });
  // keep the deepest (most specific) dense containers
  out.sort((a,b) => (b.n - a.n) || (b.depth - a.depth));
  const allExt = [...document.querySelectorAll('a[href]')]
    .map(a => a.getAttribute('href')).filter(isExt);
  return { dense: out.slice(0, 25), totalExt: allExt.length, uniqExt: new Set(allExt).size };
}"""

# candidate reference-bar triggers (text-based; class is hashed)
BAR_RE = r"(已(搜索|阅读|参考)|搜索了|参考资料|引用来源|查看来源).{0,8}\d+|（\d+）"


async def probe_extract(self, page, answer):  # bound below
    p = sys.__stdout__
    def log(*a): p.write(" ".join(str(x) for x in a) + "\n"); p.flush()

    # 1) baseline (panel collapsed)
    base = await page.evaluate(ENUM_JS)
    log(f"[PROBE] baseline totalExt={base['totalExt']} uniqExt={base['uniqExt']} denseContainers={len(base['dense'])}")
    for d in base["dense"][:8]:
        log(f"  [base] <{d['tag']} class={d['cls']!r}> n={d['n']} depth={d['depth']}")
        for s in d["sample"]:
            log(f"         - {s['txt']!r} {s['href']}")

    # 2) try to click the reference/searched bar
    clicked = None
    try:
        cands = await page.evaluate(r"""() => {
            const re = new RegExp(""" + f'"{BAR_RE}"' + r""");
            const hits = [];
            document.querySelectorAll('div,span,button,[role=button],a').forEach((el,i) => {
                const t = (el.innerText||'').trim();
                if (t && t.length <= 40 && re.test(t)) {
                    el.setAttribute('data-probe-bar', String(hits.length));
                    hits.push({i: hits.length, tag: el.tagName, txt: t.slice(0,40),
                               cls: (typeof el.className==='string'?el.className:'').slice(0,120)});
                }
            });
            return hits;
        }""")
        log(f"[PROBE] candidate ref-bars: {len(cands)}")
        for c in cands[:10]:
            log(f"   bar#{c['i']} <{c['tag']} class={c['cls']!r}> {c['txt']!r}")
        if cands:
            # click the shallowest/likeliest = first
            loc = page.locator("[data-probe-bar='0']").first
            await loc.scroll_into_view_if_needed(timeout=3000)
            await loc.click(timeout=5000)
            clicked = cands[0]["txt"]
            log(f"[PROBE] clicked ref-bar: {clicked!r}")
            await asyncio.sleep(3.0)
    except Exception as e:
        log(f"[PROBE] ref-bar click failed: {type(e).__name__}: {e}")

    # 3) re-enumerate after expansion
    after = await page.evaluate(ENUM_JS)
    log(f"[PROBE] AFTER totalExt={after['totalExt']} uniqExt={after['uniqExt']} denseContainers={len(after['dense'])}")
    for d in after["dense"][:12]:
        log(f"  [after] <{d['tag']} class={d['cls']!r}> n={d['n']} depth={d['depth']}")
        for s in d["sample"]:
            log(f"          - {s['txt']!r} {s['href']}")

    # 4) dump expanded body
    try:
        html = await page.evaluate("() => document.body.innerHTML")
        with open("/tmp/ds_probe_expanded.html", "w", encoding="utf-8") as f:
            f.write(html)
        log(f"[PROBE] dumped expanded body ({len(html)} bytes) -> /tmp/ds_probe_expanded.html")
    except Exception as e:
        log(f"[PROBE] dump failed: {e}")

    # original extraction for comparison
    return await DeepSeekBrowserAdapter._extract_citations(self, page, answer)


async def main():
    adapter = DeepSeekBrowserAdapter()
    # monkeypatch the probe in
    adapter._extract_citations = probe_extract.__get__(adapter, DeepSeekBrowserAdapter)

    page = ctx = None
    try:
        page, ctx = await create_stealth_page("deepseek")
        await adapter._prepare_page(page, ctx)

        # ── DIAGNOSTIC: what toggle/search controls exist right now? ──
        try:
            ctrls = await page.evaluate(r"""() => {
                const out = [];
                document.querySelectorAll('div,button,span,[role=button],[role=switch],label').forEach(el => {
                    const t = (el.innerText||'').trim();
                    if (t && t.length <= 16 && /搜索|联网|网页|深度|思考|search|web/i.test(t)) {
                        out.push({tag: el.tagName, txt: t,
                                  cls: (typeof el.className==='string'?el.className:'').slice(0,120),
                                  aria_pressed: el.getAttribute('aria-pressed'),
                                  aria_checked: el.getAttribute('aria-checked'),
                                  data_active: el.getAttribute('data-active')});
                    }
                });
                // de-dup by txt+cls
                const seen=new Set(), uniq=[];
                for(const o of out){const k=o.txt+'|'+o.cls; if(!seen.has(k)){seen.add(k);uniq.push(o);}}
                return uniq.slice(0,30);
            }""")
            sys.__stdout__.write(f"[DIAG] search-related controls ({len(ctrls)}):\n")
            for c in ctrls:
                sys.__stdout__.write(f"   <{c['tag']} class={c['cls']!r}> {c['txt']!r} pressed={c['aria_pressed']} checked={c['aria_checked']} active={c['data_active']}\n")
            sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[DIAG] control enum failed: {e}\n"); sys.__stdout__.flush()

        # ── DIAGNOSTIC 2: input element + login wall + full toolbar after settle ──
        await asyncio.sleep(4)
        diag2 = await page.evaluate(r"""() => {
            const inp = {
                textarea: document.querySelectorAll('textarea').length,
                contenteditable: document.querySelectorAll('[contenteditable=true],[contenteditable=""]').length,
                input_text: document.querySelectorAll('input[type=text],input:not([type])').length,
            };
            const ce = [...document.querySelectorAll('[contenteditable]')].slice(0,5).map(el => ({
                tag: el.tagName, cls:(typeof el.className==='string'?el.className:'').slice(0,120),
                ph: el.getAttribute('data-placeholder')||el.getAttribute('placeholder')||'',
            }));
            const txt = (document.body.innerText||'');
            const wall = {};
            ['登录','Sign in','Log in','验证','人机','滑块','繁忙','请稍后','重新登录'].forEach(k=>{ if(txt.includes(k)) wall[k]=true; });
            const btns = [];
            document.querySelectorAll('button,[role=button],div[tabindex],span').forEach(el=>{
                const t=(el.innerText||'').trim();
                if(t && t.length<=14){ btns.push({tag:el.tagName, t, cls:(typeof el.className==='string'?el.className:'').slice(0,90)}); }
            });
            const seen=new Set(), ub=[];
            for(const b of btns){const k=b.t+'|'+b.cls; if(!seen.has(k)){seen.add(k);ub.push(b);}}
            return {inp, ce, wall, btns: ub.slice(0,40), bodyLen: txt.length};
        }""")
        sys.__stdout__.write(f"[DIAG2] inputs={diag2['inp']} bodyLen={diag2['bodyLen']} wall={diag2['wall']}\n")
        sys.__stdout__.write(f"[DIAG2] contenteditable elems: {diag2['ce']}\n")
        sys.__stdout__.write(f"[DIAG2] short buttons ({len(diag2['btns'])}):\n")
        for b in diag2['btns']:
            sys.__stdout__.write(f"   <{b['tag']} class={b['cls']!r}> {b['t']!r}\n")
        sys.__stdout__.flush()
        try:
            html = await page.evaluate("() => document.body.innerHTML")
            with open("/tmp/ds_probe_loaded.html","w",encoding="utf-8") as f: f.write(html)
            sys.__stdout__.write(f"[DIAG2] dumped loaded body ({len(html)} bytes) -> /tmp/ds_probe_loaded.html\n"); sys.__stdout__.flush()
        except Exception as e:
            sys.__stdout__.write(f"[DIAG2] dump failed: {e}\n"); sys.__stdout__.flush()

        res = await adapter._query_with_page(page, ctx, QUERY)
        sys.__stdout__.write(f"[PROBE] res.error={res.error!r}\n"); sys.__stdout__.flush()
        sys.__stdout__.write(f"\n[PROBE] FINAL prod-extract citations={len(res.citations)} ans_len={len(res.answer or '')}\n")
        for c in res.citations[:30]:
            sys.__stdout__.write(f"   cit: {c.domain} {c.url}\n")
        sys.__stdout__.flush()
        # deliberately NOT saving session
    finally:
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
