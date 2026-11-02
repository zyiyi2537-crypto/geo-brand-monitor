"""Read a whole current-answer source list; article identity is judged by AI.

The browser owns extraction only. Preserve numbered entries (including duplicate
URLs), accumulate virtualized rows while scrolling, and record completeness.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from .base import Citation


SOURCE_SNAPSHOT_JS = r"""({engine, assistant_sel, action}) => {
    const text = e => (e?.innerText || e?.textContent || '').trim();
    const last = (root, sel) => [...root.querySelectorAll(sel)].at(-1);
    const visible = e => !!(e && e.getBoundingClientRect().width && e.getBoundingClientRect().height);
    const refPattern = /(?:参考\s*(\d+)\s*(?:篇|个|条)\s*(?:资料|来源|网页)|搜索到\s*(\d+)\s*个网页|搜索全网\s*(\d+)\s*篇资料)/;
    const leafHeaders = root => [...root.querySelectorAll('div,span,button')].filter(e =>
        text(e).length < 90 && refPattern.test(text(e)) &&
        ![...e.children].some(c => refPattern.test(text(c))));
    let scope = null, header = null, panel = null, cards = [], rows = [];
    let expected = null, authoritative = false, structured = false;
    const items = (root, sel) => root ? [...root.querySelectorAll(sel)] : [];
    const numbered = a => /^\d+[.．]\s/.test(text(a));
    const number = e => {
        const s = text(e?.querySelector('.ds-markdown-cite, [class*="_index_"]'));
        const n = s.match(/^\d+/) || text(e).match(/^\d+[.．]/);
        return n ? Number(n[0].replace(/[.．]/g,'')) : 0;
    };
    const add = (e, url, title, position=0, snippet='') => rows.push({
        url:url || '', title:(title || '').replace(/^\d+[.．]\s*/, ''),
        position, snippet, id: position ? String(position) : ''
    });

    if (engine === 'qwen') {
        scope = last(document, assistant_sel || '[data-chat-answers-wrap]');
        panel = scope?.querySelector('[data-card_name="bar_workflow"]');
        header = panel && leafHeaders(panel)[0];
        if (panel && action === 'expand') {
            const collapsed = [...panel.querySelectorAll('div')].find(e =>
                String(e.className).includes('grid-rows-[0fr]'));
            if (collapsed && header) header.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        }
        cards = items(panel, 'a[href^="http"]');
    } else if (engine === 'doubao') {
        const list = document.querySelector('[class*="message-list-"]');
        scope = items(list, '.v_list_row').filter(e =>
            text(e).length > 10 && !e.querySelector('[class*="send-msg"], [data-send]')).at(-1);
        header = scope && leafHeaders(scope).at(-1);
        // The source panel is the smallest ancestor of its own heading with numbered links.
        for(let e=header?.parentElement, d=0; e && d<7; e=e.parentElement,d++) {
            if (scope && e!==scope && !scope.contains(e)) break;
            const links = items(e,'a[href^="http"]').filter(numbered);
            if(links.length) { panel=e;cards=links;break; }
        }
        if (!panel && header && action==='expand') header.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    } else if (engine === 'wenxin') {
        scope = last(document, '.conversation-flow-answer-container');
        header = scope && leafHeaders(scope).find(e => /参考/.test(text(e)));
        // Sources and their heading must belong to the latest answer.
        for(let e=header?.parentElement,d=0;e&&d<14;e=e.parentElement,d++) {
            if (!scope || (e!==scope && !scope.contains(e))) break;
            const refs=items(e,'li[data-long-press-ext-info], [class*="reference-item"]');
            if(refs.length) {panel=e;cards=refs;break;}
            if (e===document.body) break;
        }
        if (!panel && header && action==='expand') header.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        if (panel && action==='expand' && !cards.some(visible) && header)
            header.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    } else if (engine === 'deepseek') {
        scope = last(document, '.ds-markdown.ds-assistant-message-main-content')?.closest('.ds-message');
        header = scope && leafHeaders(scope).at(-1);
        if(header) {
            cards = items(document,'.search-view-card__title').map(e=>e.closest('a[href]')).filter(Boolean);
            panel = cards[0]?.parentElement || null;
            // The drawer lives outside the answer. Always select the latest answer's
            // heading first so an already-open drawer from an earlier turn cannot leak.
            // If the click toggles this drawer closed, the next pass opens it again.
            if(action==='expand' || !panel) header.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        }
    } else if (engine === 'yuanbao') {
        scope = last(document,'.agent-chat__bubble--ai');
        const triggers=items(scope,'.hyc-common-markdown__ref-list__trigger, .hyc-common-markdown__ref_card');
        // These are the exact documents backing the current answer's source cards.
        // A merged reference icon may only display ONE doc although docList holds ALL.
        for(const trigger of triggers) {
            const key=Object.keys(trigger).find(k=>k.startsWith('__reactFiber'));
            let f=key && trigger[key];
            for(let d=0;f&&d<10;f=f.return,d++) {
                const docs=f.memoizedProps?.docList;
                if(!Array.isArray(docs) || !docs.length) continue;
                expected=Math.max(expected || 0,docs.length);
                for(let i=0;i<docs.length;i++) {
                    const doc=docs[i] || {};
                    add(null,doc.web_url || doc.url || '',doc.title || doc.name || '',
                        Number(doc.index ?? doc.idx ?? i+1),doc.quote || doc.snippet || '');
                }
                structured=true;authoritative=true;panel=scope;break;
            }
            if(structured) break; // One full docList; avoid duplicating the same list per inline icon.
        }
        if(!structured) {
            panel=scope;
            cards=items(scope,'.hyc-common-markdown__ref_card, .hyc-common-markdown__ref-list__item');
        }
    }

    if(header) {
        const m=text(header).match(refPattern);
        if(m) expected=Number(m[1] ?? m[2] ?? m[3]);
    }
    // Only expansion controls inside the current source panel. Never click answer follow-ups.
    let more=false;
    if(panel && engine!=='yuanbao') {
        const expanders=items(panel,'button,span,div').filter(e =>
            /^(?:查看全部|展开全部|显示全部|加载更多|查看更多|展开更多)$/.test(text(e)) &&
            ![...e.children].some(c=>text(c)===text(e)));
        more=expanders.some(visible);
        if(action==='expand' || action==='scroll') {
            for(const e of expanders) if(visible(e)) e.dispatchEvent(new MouseEvent('click',{bubbles:true}));
        }
    }
    if(!structured) {
        for(let i=0;i<cards.length;i++) {
            const e=cards[i];
            let url=e.href || e.querySelector('a[href^="http"]')?.href || '';
            let title=text(e.querySelector('.search-view-card__title, [class*="_text_"], .hyc-common-markdown__ref_card-title')) || text(e);
            let pos=number(e);
            // Position in a virtualized DOM window is not the source's identity.
            if(engine==='qwen') {
                const idx=e.getAttribute('data-index');
                pos=idx!==null ? Number(idx)+1 : Number(e.getAttribute('aria-posinset') || 0);
            }
            if(engine==='wenxin') {
                try {
                    const data=JSON.parse(e.getAttribute('data-long-press-ext-info') || '{}');
                    url=data.link || url;title=data.linkTitle || title;
                } catch {}
            }
            add(e,url,title,pos,text(e.querySelector('.search-view-card__snippet')));
        }
    }
    // Scroll only the source panel and its scrollable ancestors, never the history sidebar.
    const scrollers=new Set();
    if(panel && !structured) {
        for(const e of [panel,...panel.querySelectorAll('*')]) {
            if(e.scrollHeight>e.clientHeight+3 && e.clientHeight>0 && /auto|scroll/.test(getComputedStyle(e).overflowY)) scrollers.add(e);
        }
        for(let e=panel.parentElement;e && e!==document.body;e=e.parentElement) {
            if(e.scrollHeight>e.clientHeight+3 && e.clientHeight>0 && /auto|scroll/.test(getComputedStyle(e).overflowY)) {scrollers.add(e);break;}
        }
    }
    const scrollState=[...scrollers].map(e=>({top:e.scrollTop,height:e.clientHeight,total:e.scrollHeight}));
    const at_bottom=scrollState.every(s=>s.top+s.height>=s.total-3);
    if(action==='reset') for(const e of scrollers) e.scrollTop=0;
    if(action==='scroll') for(const e of scrollers) e.scrollTop=Math.min(e.scrollTop+Math.max(100,e.clientHeight*.75),e.scrollHeight);
    return {rows,expected,panel_found:!!panel,authoritative,structured,at_bottom,more,
        scroll_state:scrollState,header:text(header),source_url:location.href};
}"""


async def collect_all_references(page, engine: str, answer: str = "", assistant_sel: str | None = None,
                                 *, timeout: float = 25) -> tuple[list[Citation], dict]:
    """Expand, sweep to the bottom, and accumulate every source without a top-N cap.

    Timeout is a failure of completeness, never proof of non-citation. A supplied
    count must match the entry count exactly; missing card URLs stay incomplete.
    """
    args = {"engine": engine, "assistant_sel": assistant_sel}
    entries: dict[str, dict] = {}
    expected = None
    last_signature = None
    stable_bottom = 0
    stable_since = None
    snapshot: dict = {}
    failure = ""
    complete = False
    sweeps = 0
    deadline = time.monotonic() + timeout
    async def snapshot_for(action: str) -> dict:
        # Patchright's default isolated world cannot see React's source docList.
        kwargs = {"isolated_context": False} if "isolated_context" in inspect.signature(page.evaluate).parameters else {}
        return await page.evaluate(SOURCE_SNAPSHOT_JS, {**args, "action": action}, **kwargs)
    try:
        await snapshot_for("expand")
        await asyncio.sleep(.4)
        await snapshot_for("reset")
        await asyncio.sleep(.2)
        while time.monotonic() < deadline:
            snapshot = await snapshot_for("scroll") or {}
            sweeps += 1
            if isinstance(snapshot.get("expected"), int):
                expected = snapshot["expected"]
            occurrences: dict[str, int] = {}
            for row in snapshot.get("rows") or []:
                base = row.get("id") or f"{row.get('url')}\n{row.get('title')}"
                occurrences[base] = occurrences.get(base, 0) + 1
                key = base if row.get("id") else f"{base}\n{occurrences[base]}"
                old = entries.get(key)
                if old is None or row.get("url") or not old.get("url"):
                    entries[key] = row
            signature = (len(entries), repr(snapshot.get("scroll_state")), snapshot.get("more"))
            if snapshot.get("at_bottom") and not snapshot.get("more") and signature == last_signature:
                stable_bottom += 1
                if stable_since is None:
                    stable_since = time.monotonic()
            else:
                stable_bottom = 0
                stable_since = None
            last_signature = signature
            usable = all(str(r.get("url") or "").startswith(("http://", "https://")) for r in entries.values())
            count_matches = expected is None or len(entries) == expected
            if snapshot.get("panel_found") and usable and count_matches and stable_bottom >= 2:
                # Unknown-count empty panels cannot prove zero references.
                complete = bool(entries) or expected == 0
                break
            # A structured source document array is exhaustive without DOM scrolling.
            if snapshot.get("authoritative") and usable and count_matches:
                complete = True
                break
            # Unavailable UI: avoid spending the full budget on a nonexistent panel.
            if not snapshot.get("panel_found") and sweeps >= 4:
                failure = "未找到当前回答的完整引用列表"
                break
            # Give lazy requests time to finish, even when the current DOM is at bottom.
            if stable_bottom >= 3 and stable_since is not None and time.monotonic() - stable_since >= 5:
                failure = "引用列表已到底，但来源数量或网址不完整"
                break
            await asyncio.sleep(.35)
    except Exception as exc:
        failure = f"读取引用列表失败：{type(exc).__name__}"
    ordered = sorted(entries.values(), key=lambda r: r.get("position") or 10**9)
    citations = [Citation.from_url(r["url"], title=r.get("title") or "", snippet=r.get("snippet") or "",
                                   position=r.get("position") or i)
                 for i, r in enumerate(ordered, 1)
                 if str(r.get("url") or "").startswith(("http://", "https://"))]
    metadata = {
        "complete": complete, "expected_count": expected, "captured_count": len(citations),
        "observed_count": len(entries), "missing_url_count": len(entries) - len(citations),
        "reason": "全部来源已读取" if complete else failure or "读取全部来源超时",
        "method": "current_answer_source_list", "scroll_passes": sweeps,
    }
    return citations, metadata
