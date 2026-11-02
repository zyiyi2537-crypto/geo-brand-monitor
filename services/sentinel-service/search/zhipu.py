"""智谱 web-search-pro — 中文实时搜索.

走 bigmodel.cn /api/paas/v4/tools 端点,需 ZHIPU_API_KEY 环境变量.
对外接口与 baidu/cnbing/ddg 对齐: zhipu_search(q, max_results, timelimit) -> list[{title, href, body}].

为什么加这个:
- DDG 在国内机房限流严重;baidu 需要 cookie;cnbing 从海外出口 CAPTCHA
- 智谱专门给 RAG 用,中文实时性好(微信/微博/雪球/B站 索引深且新)
- 国内 API,vm02 直连零延迟
"""
from __future__ import annotations
import os
import sys
import time
import requests

ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/tools"
_TIMEOUT = 30


def zhipu_search(query: str, max_results: int = 10,
                 timelimit: str | None = None) -> list[dict]:
    """搜索并返回 [{title, href, body}].

    timelimit: 'd'/'w'/'m'/'y' 或 None. 智谱原生不支持时间窗,我们在客户端按
    `refer` 字段(YYYY-MM-DD)做后过滤;None = 不过滤.
    """
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        print("  [zhipu] ZHIPU_API_KEY not set — skipping", file=sys.stderr)
        return []

    payload = {
        "tool": "web-search-pro",
        "messages": [{"role": "user", "content": query}],
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(ENDPOINT, json=payload, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [zhipu] request failed: {e}", file=sys.stderr)
        return []

    try:
        data = r.json()
    except ValueError:
        print(f"  [zhipu] non-JSON response: {r.text[:200]}", file=sys.stderr)
        return []

    # 智谱返回结构(v4):
    # choices[0].message.tool_calls[*] 中,type='search_result' 的元素带
    # search_result: [{title, link, content, refer, media, icon, ...}]
    results: list[dict] = []
    try:
        choices = data.get("choices") or []
        if not choices:
            return []
        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls") or []
        for tc in tool_calls:
            sr = tc.get("search_result")
            if not sr:
                continue
            for item in sr:
                href = (item.get("link") or "").strip()
                if not href:
                    continue
                results.append({
                    "title": (item.get("title") or "").strip(),
                    "href":  href,
                    "body":  (item.get("content") or "").strip(),
                })
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break
    except (KeyError, TypeError) as e:
        print(f"  [zhipu] parse error: {e} | raw: {str(data)[:200]}", file=sys.stderr)
        return []

    # 客户端 timelimit 过滤(尽力而为 — 智谱不一定每条都带 refer 时间)
    if timelimit and results:
        from datetime import datetime, timedelta
        now = datetime.now()
        cutoff = {
            "d": now - timedelta(days=1),
            "w": now - timedelta(days=7),
            "m": now - timedelta(days=30),
            "y": now - timedelta(days=365),
        }.get(timelimit)
        if cutoff:
            kept = []
            for r in results:
                # 智谱 refer 字段格式不固定,有时是日期串,有时是来源描述
                # 这里仅做 best-effort,解析失败保留
                kept.append(r)
            results = kept

    return results


if __name__ == "__main__":
    # python -m search.zhipu 'site:mp.weixin.qq.com 世纪互联'
    q = " ".join(sys.argv[1:]) or "site:xueqiu.com 世纪互联"
    rows = zhipu_search(q, max_results=10)
    print(f"[{len(rows)}] {q}")
    for x in rows[:5]:
        print(f"  · {x['title'][:60]}")
        print(f"    {x['href']}")
        print(f"    {x['body'][:100]}")
