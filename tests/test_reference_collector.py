"""Exercise full-source UI behavior against a real local browser, without sending platform questions."""
import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

# Both services use the package name "app". Isolate browser engine imports so
# collecting these tests together does not mask the telemetry report package.
engine_dir = Path(__file__).resolve().parents[1] / "services" / "browser-service" / "app" / "engines"
engine_spec = importlib.util.spec_from_file_location("_geo_reference_test_engines", engine_dir / "__init__.py")
engine_package = importlib.util.module_from_spec(engine_spec)
sys.modules[engine_spec.name] = engine_package
engine_spec.loader.exec_module(engine_package)
collect_all_references = importlib.import_module("_geo_reference_test_engines.reference_collector").collect_all_references


class ReferenceCollectorTests(unittest.TestCase):
    def test_full_source_panels_and_incomplete_reads(self):
        asyncio.run(self.check_panels())

    async def check_panels(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                # Old answer references and ordinary body links cannot leak into the latest list.
                # Sources beyond the initial five appear only after expansion and scrolling.
                await page.set_content('''<div data-chat-answers-wrap><div data-card_name="bar_workflow">
                  <span>共参考 1 篇资料</span><a href="https://old.example/article">旧回答</a></div></div>
                  <div data-chat-answers-wrap><div data-card_name="bar_workflow">
                  <span>共参考 33 篇资料</span><button id="expand">查看全部</button>
                  <div id="sources" style="height:140px;overflow:auto"></div></div>
                  <a href="https://navigation.example">普通链接</a></div>''')
                await page.evaluate('''() => {
                    const list=document.querySelector('#sources'); let size=5, expanded=false;
                    const render=()=>{list.innerHTML=Array.from({length:size},(_,i)=>
                      `<div style="height:42px"><a href="https://source.example/${i<2?'duplicate':i}">文章${i<2?'重复':i}</a></div>`).join('');};
                    document.querySelector('#expand').onclick=e=>{expanded=true;e.target.remove();render();};
                    list.onscroll=()=>{if(expanded && size<33 && list.scrollTop+list.clientHeight>=list.scrollHeight-5)
                      setTimeout(()=>{size=Math.min(33,size+7);render();},100);};render();
                }''')
                cites, meta = await collect_all_references(page, "qwen", assistant_sel="[data-chat-answers-wrap]")
                self.assertTrue(meta["complete"], meta)
                self.assertEqual(len(cites), 33)
                self.assertEqual(sum(c.url.endswith('/duplicate') for c in cites), 2)
                self.assertTrue(any(c.url.endswith('/32') for c in cites))
                self.assertFalse(any('old.example' in c.url or 'navigation.example' in c.url for c in cites))

                # Numbered virtualized rows must be accumulated while earlier rows leave the DOM.
                await page.set_content('''<div class="ds-message"><span>搜索到 24 个网页</span>
                  <div class="ds-markdown ds-assistant-message-main-content">当前回答</div></div>
                  <div id="panel" style="height:140px;overflow:auto"><div style="height:1200px;position:relative" id="cards"></div></div>''')
                await page.evaluate('''() => {
                  const panel=document.querySelector('#panel'),cards=document.querySelector('#cards');
                  const render=()=>{const start=Math.min(21,Math.floor(panel.scrollTop/50));cards.innerHTML=
                    Array.from({length:3},(_,j)=>{const i=start+j+1;return `<a href="https://source.example/${i}" style="position:absolute;top:${(i-1)*50}px;height:50px">
                    <span class="ds-markdown-cite">${i}</span><div class="search-view-card__title">文章${i}</div></a>`;}).join('');};
                  panel.onscroll=render;render();
                }''')
                cites, meta = await collect_all_references(page, "deepseek")
                self.assertTrue(meta["complete"], meta)
                self.assertEqual([c.position for c in cites], list(range(1, 25)))

                # An open drawer from an old turn cannot stand in for a new answer without sources.
                await page.evaluate('''() => {document.body.insertAdjacentHTML('beforeend',
                  '<div class="ds-message"><div class="ds-markdown ds-assistant-message-main-content">新回答没有搜索来源</div></div>');}''')
                cites, meta = await collect_all_references(page, "deepseek", timeout=2)
                self.assertEqual(cites, [])
                self.assertFalse(meta["complete"])

                # Wenxin reference cards hold URLs in data attributes instead of <a href>.
                data=json.dumps({"link":"https://source.example/wenxin", "linkTitle":"真实来源标题"}, ensure_ascii=False)
                await page.set_content(f'''<div class="conversation-flow-answer-container"><span>共参考1篇资料</span>
                  <ul><li data-long-press-ext-info='{data}'><span class="_index_test">1.</span>
                  <span class="_text_test">来源</span></li></ul></div>''')
                cites, meta = await collect_all_references(page, "wenxin")
                self.assertTrue(meta["complete"], meta)
                self.assertEqual(cites[0].url, 'https://source.example/wenxin')

                await page.evaluate('''() => {document.body.insertAdjacentHTML('beforeend',
                  '<div class="conversation-flow-answer-container">最新回答没有来源列表</div>');}''')
                cites, meta = await collect_all_references(page, "wenxin", timeout=2)
                self.assertEqual(cites, [])
                self.assertFalse(meta["complete"])

                # One Yuanbao icon represents multiple docs, including repeated article URLs.
                await page.set_content('''<div class="agent-chat__bubble--ai"><div class="hyc-common-markdown__ref-list__trigger" id="old"></div></div>
                  <div class="agent-chat__bubble--ai"><div class="hyc-common-markdown__ref-list__trigger" id="new"></div></div>''')
                await page.evaluate('''() => {
                  document.querySelector('#old').__reactFiber$test={memoizedProps:{docList:[{index:1,url:'https://old.example',title:'旧来源'}]}};
                  document.querySelector('#new').__reactFiber$test={memoizedProps:{docList:Array.from({length:31},(_,i)=>
                    ({index:i+1,url:`https://source.example/${i<2?'duplicate':i}`,title:`来源${i}`,quote:`摘要${i}`}))}};
                }''')
                cites, meta = await collect_all_references(page, "yuanbao")
                self.assertTrue(meta["complete"], meta)
                self.assertEqual(len(cites), 31)
                self.assertFalse(any('old.example' in c.url for c in cites))

                # A title-only card is a missing URL, never proof that the target is absent.
                await page.set_content('''<div class="conversation-flow-answer-container"><span>共参考2篇资料</span><ul>
                  <li data-long-press-ext-info='{"link":"https://source.example/1","linkTitle":"来源1"}'><span class="_index_test">1.</span></li>
                  <li data-long-press-ext-info='{}'><span class="_index_test">2.</span><span>网址未加载</span></li></ul></div>''')
                cites, meta = await collect_all_references(page, "wenxin", timeout=2)
                self.assertFalse(meta["complete"])
                self.assertEqual(meta["observed_count"], 2)
                self.assertEqual(meta["missing_url_count"], 1)
            finally:
                await browser.close()


if __name__ == "__main__":
    unittest.main()
