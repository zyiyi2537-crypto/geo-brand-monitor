"""NewsNow 热榜聚合器适配 — 调用自托管 newsnow JSON API 拉 42 站热榜.

定位:
- 适合"广撒网发现热点" — 微博热搜 / 知乎热榜 / 抖音 / 贴吧 / V2EX / 今日头条 等
  这些站点不在 sentinel 现有 15 个财经爬虫的覆盖范围内
- 不适合按品牌做深度监控(只是热榜快照,本地用 keyword 过滤标题)
- 数据极薄:只有 title + url,无时间戳 / 无正文 / 无阅读量
- 必须自托管 newsnow(busiyi.world demo 站套了 Cloudflare 反爬)

返回格式与其他 crawler 一致:[{source, post_id, symbol, ...}]
content / publish_time / 互动指标全为 None — newsnow 接口不返这些.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from typing import Iterator, Optional

import requests

_DEFAULT_BASE_URL = os.environ.get("NEWSNOW_BASE_URL", "http://localhost:4444")
_UA = "sentinel-service/1.0 (newsnow-hub adapter)"


class NewsnowHubClient:
    """NewsNow 适配器.

    base_url: 自托管 newsnow 实例,如 http://newsnow:4444(docker-compose 同网络)
              或 NEWSNOW_BASE_URL env 兜底.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": _UA,
            "Accept": "application/json",
        })

    def fetch_source(self, source_id: str) -> list[dict]:
        """拉单个 source 的当前热榜.

        source_id: newsnow 内部 id,如 weibo / zhihu / v2ex / ithome / hupu / toutiao / ...
                   完整列表见 https://github.com/ourongxing/newsnow/tree/main/server/sources
        返回 newsnow 原始 item 列表.
        """
        url = f"{self.base_url}/api/s"
        params = {"id": source_id}
        try:
            r = self.session.get(url, params=params, timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [newsnow] fetch source={source_id} failed: {e}", file=sys.stderr)
            return []

        try:
            data = r.json()
        except ValueError:
            print(f"  [newsnow] non-JSON response for source={source_id}", file=sys.stderr)
            return []

        # newsnow 返回结构:{ status, id, items: [{id, title, url, mobileUrl, extra?}, ...] }
        items = data.get("items") or []
        return items if isinstance(items, list) else []

    def fetch_sources(self, source_ids: list[str], keywords: list[str],
                      symbol: str) -> Iterator[dict]:
        """按 source 列表轮询 + 本地 keyword 过滤(title 子串,大小写不敏感).

        keywords 空 list = 不过滤,全量入库(适合"我就要看 V2EX 完整热榜");
        keywords 非空 = 仅命中标题入库(适合"盯品牌在微博热搜出现").
        """
        kw_lower = [k.lower() for k in keywords if k and k.strip()]
        for src in source_ids:
            src = (src or "").strip()
            if not src:
                continue
            items = self.fetch_source(src)
            for item in items:
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                if kw_lower and not _title_matches(title, kw_lower):
                    continue
                rec = _parse_newsnow_item(item, source_id=src, symbol=symbol)
                if rec:
                    yield rec
            time.sleep(0.3)  # 站间小停顿,虽然走自托管 newsnow 容器其实没必要


def _title_matches(title: str, keywords_lower: list[str]) -> bool:
    t = title.lower()
    return any(k in t for k in keywords_lower)


def _parse_newsnow_item(item: dict, *, source_id: str, symbol: str) -> Optional[dict]:
    """newsnow item → 统一 post 格式."""
    title = (item.get("title") or "").strip()
    url = (item.get("url") or item.get("mobileUrl") or "").strip()
    if not title or not url:
        return None

    # newsnow 自己有 id 字段;为防 source 间冲突,post_id = id + url-hash
    raw_id = str(item.get("id") or "")
    pid = raw_id or hashlib.sha1(url.encode()).hexdigest()[:16]

    extra = item.get("extra") or {}
    # extra.info 偶尔含 hotness 数值(微博/知乎),不是稳定字段,先不存

    return {
        "source": f"newsnow:{source_id}",
        "post_id": pid,
        "symbol": symbol,
        "author": None,           # newsnow 不返作者
        "title": title,
        "content": None,          # 标题级监控,无正文
        "publish_time": None,     # newsnow 不返时间戳
        "view_count": None,
        "reply_count": None,
        "like_count": None,
        "share_count": None,
        "url": url,
        # extra 里偶尔有 hotness/icon 标记,放 raw 备查(upsert_post 会丢弃未知字段)
    }
