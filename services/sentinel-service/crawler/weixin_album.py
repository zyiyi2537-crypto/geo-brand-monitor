"""微信公众号合集(Album)爬虫 — 按 album URL 全量枚举历史文章.

数据源:`mp.weixin.qq.com/mp/appmsgalbum?action=getalbum`(公开接口,无 cookie).
输入:合集 URL,如 `https://mp.weixin.qq.com/mp/appmsgalbum?__biz=Mzxxx&action=getalbum&album_id=xxxxx&scene=21`

定位:
- 适合"周级别盯防几个高价值竞品官号 / KOL / 监管口径号"
- 不适合按关键词全网搜(getalbum 接口本身不收 query)
- 不返阅读量 / 在看 / 点赞(接口限制,所有微信路径通病)

返回格式与其他 crawler 一致:[{source, post_id, symbol, author, title, content, ...}]
content 默认为 None;如 hydrate_body=True 则额外抓 mp.weixin 正文 HTML 解析填入.
"""
from __future__ import annotations

import random
import re
import sys
import time
from datetime import datetime
from typing import Iterator, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.49(0x18003133) NetType/WIFI Language/zh_CN"
)


class WeixinAlbumClient:
    """微信合集爬虫.

    无 cookie,直接 hit getalbum 接口.每 1-3s 随机间隔避免限流.
    单合集 500+ 文章约需 ~50s 拉完 index;hydrate_body=True 还要加 ~2s/篇.
    """

    def __init__(self, hydrate_body: bool = False):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://mp.weixin.qq.com/",
        })
        self.hydrate_body = hydrate_body

    def fetch_album(self, album_url: str, max_articles: Optional[int] = None) -> Iterator[dict]:
        """拉一个合集的全部文章.

        album_url: 合集 URL,要求包含 __biz 和 album_id 参数.
        max_articles: 上限保护(None=全量;500+ 大号建议设上限避免单次跑太久).
        """
        biz, album_id = _extract_album_params(album_url)
        if not biz or not album_id:
            print(f"  [weixin_album] invalid album url (missing __biz/album_id): {album_url}",
                  file=sys.stderr)
            return

        begin_msgid: Optional[str] = None
        begin_itemidx: Optional[str] = None
        fetched = 0

        while True:
            try:
                items, continue_flag, last_msgid, last_itemidx = self._fetch_page(
                    biz=biz, album_id=album_id,
                    begin_msgid=begin_msgid, begin_itemidx=begin_itemidx,
                )
            except requests.RequestException as e:
                print(f"  [weixin_album] request failed (biz={biz[:10]}...): {e}",
                      file=sys.stderr)
                return

            if not items:
                return

            for item in items:
                rec = _parse_album_item(item, biz=biz, album_id=album_id)
                if not rec:
                    continue
                if self.hydrate_body and rec.get("url"):
                    body = self._fetch_body(rec["url"])
                    if body:
                        rec["content"] = body
                    time.sleep(random.uniform(1.0, 2.0))  # 正文抓取限速
                yield rec
                fetched += 1
                if max_articles and fetched >= max_articles:
                    return

            if not continue_flag or not last_msgid:
                return
            begin_msgid = last_msgid
            begin_itemidx = last_itemidx
            time.sleep(random.uniform(1.0, 3.0))  # 翻页限速

    def fetch_albums(self, album_urls: list[str],
                     max_articles_per_album: Optional[int] = None) -> Iterator[dict]:
        """多合集批量拉取(顺序,避免并发触发风控)."""
        for url in album_urls:
            url = (url or "").strip()
            if not url:
                continue
            yield from self.fetch_album(url, max_articles=max_articles_per_album)

    def _fetch_page(self, *, biz: str, album_id: str,
                    begin_msgid: Optional[str], begin_itemidx: Optional[str]
                    ) -> tuple[list[dict], bool, Optional[str], Optional[str]]:
        """单页请求.返回 (items, continue_flag, last_msgid, last_itemidx)."""
        url = "https://mp.weixin.qq.com/mp/appmsgalbum"
        params = {
            "__biz": biz,
            "action": "getalbum",
            "album_id": album_id,
            "count": "20",
            "f": "json",
        }
        if begin_msgid:
            params["begin_msgid"] = begin_msgid
            params["begin_itemidx"] = begin_itemidx or "1"

        r = self.session.get(url, params=params, timeout=15)
        r.raise_for_status()

        try:
            data = r.json()
        except ValueError:
            # 风控时可能返 HTML 验证码页
            print(f"  [weixin_album] non-JSON response (possibly captcha) for album {album_id}",
                  file=sys.stderr)
            return [], False, None, None

        resp = data.get("getalbum_resp") or {}
        items = resp.get("article_list") or []
        # continue_flag 在腾讯响应里是 "0"/"1" 字符串
        cont = str(resp.get("continue_flag") or "0") == "1"
        last_msgid = None
        last_itemidx = None
        if items:
            last = items[-1]
            last_msgid = str(last.get("msgid") or "") or None
            last_itemidx = str(last.get("itemidx") or "") or None
        return items, cont, last_msgid, last_itemidx

    def _fetch_body(self, article_url: str) -> Optional[str]:
        """抓 mp.weixin 文章正文.

        微信现在有两种 article page 格式,正文位置不同:
        - 单图文(AI 日报等大多数号):#js_content 有 5000+ 字完整正文,
          meta description 只有 50-100 字摘要
        - 多图文 swiper(简单医行等多 idx 文章):#js_content 是空 placeholder
          靠 JS 渲染,meta description 反而有完整 500-1500 字编者按

        策略:三个候选(meta / js_content / rich_media_content)都试,**取最长的**.
        都空返 None.
        """
        try:
            r = self.session.get(article_url, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [weixin_album] body fetch failed: {e}", file=sys.stderr)
            return None

        soup = BeautifulSoup(r.text, "lxml")
        candidates: list[str] = []

        # 候选 1:meta description(SPA 多图文场景的主源)
        meta = soup.select_one('meta[name="description"]')
        if meta:
            desc = (meta.get("content") or "").strip()
            # 微信把换行编成字面 escape 序列(`\x0a` / `\n` 四字符),不是真实 byte.
            # LLM 拿到字面量会把 sentiment 误判,先复原.
            desc = (desc
                    .replace("\\x0a", "\n")
                    .replace("\\n", "\n")
                    .replace("\\t", " "))
            if desc:
                candidates.append(desc)

        # 候选 2:#js_content(单图文 SSR 格式的主源,常 5000+ 字)
        content_div = soup.select_one("#js_content")
        if content_div:
            text = content_div.get_text(separator="\n", strip=True)
            if text:
                candidates.append(text)

        # 候选 3:.rich_media_content(替代老 selector,通常跟 #js_content 同源)
        rm = soup.select_one(".rich_media_content")
        if rm:
            text = rm.get_text(separator="\n", strip=True)
            if text:
                candidates.append(text)

        if not candidates:
            return None
        # 取最长的 — 单图文场景 js_content 远长于 meta;多图文场景反过来
        best = max(candidates, key=len)
        return best[:5000]


def _extract_album_params(album_url: str) -> tuple[Optional[str], Optional[str]]:
    """从 album URL 提取 __biz 和 album_id."""
    try:
        qs = parse_qs(urlparse(album_url).query)
        biz = (qs.get("__biz") or [None])[0]
        album_id = (qs.get("album_id") or [None])[0]
        return biz, album_id
    except (ValueError, AttributeError):
        return None, None


def _parse_album_item(item: dict, *, biz: str, album_id: str) -> Optional[dict]:
    """getalbum 返回的单项 → 统一 post 格式."""
    msgid = str(item.get("msgid") or "")
    itemidx = str(item.get("itemidx") or "1")
    if not msgid:
        return None

    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    if not url and msgid:
        # 兜底拼装(罕见,接口一般会返完整 url)
        url = (f"https://mp.weixin.qq.com/s?__biz={biz}&mid={msgid}"
               f"&idx={itemidx}&album_id={album_id}")

    create_time = item.get("create_time") or item.get("update_time")
    publish_time = None
    if create_time:
        try:
            publish_time = datetime.fromtimestamp(int(create_time)).isoformat()
        except (ValueError, TypeError, OSError):
            pass

    # post_id 用 msgid:itemidx,因为一个 msgid 可能含多条(微信"多图文消息")
    pid = f"{msgid}:{itemidx}" if itemidx and itemidx != "1" else msgid

    return {
        "source": "weixin_album",
        "post_id": pid,
        "symbol": album_id,        # 用 album_id 作 symbol,便于按合集查询
        "author": _clean_author(item.get("nickname") or item.get("author")),
        "title": title,
        "content": None,            # 默认 None;hydrate_body=True 时由 caller 填
        "publish_time": publish_time,
        "view_count": None,         # 接口不返
        "reply_count": None,
        "like_count": None,
        "share_count": None,
        "url": url,
    }


def _clean_author(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None
