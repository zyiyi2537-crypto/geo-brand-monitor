"""Thin DuckDuckGo wrapper.

Uses the `ddgs` package (formerly `duckduckgo-search`). Region defaults to
`wt-wt` (no region bias) so a single query gets both Chinese and English
results in one shot — the analyzer is bilingual.

远程代理模式:vm02 这种国内机房 IP 直连 DDG 全部 backend 都超时/被禁。
若设了 env DDG_REMOTE_URL(指向 ddg-proxy 服务),改走 HTTP 调用代理,
代理在出口可达 DDG 的服务器上(如 AWS EC2)运行。返回格式不变。
"""
from __future__ import annotations

import os
import sys
import time

import requests

try:
    from ddgs import DDGS  # ddgs >= 9.x
except ImportError:  # pragma: no cover — older package name
    from duckduckgo_search import DDGS  # type: ignore


# 默认 backend="auto" 会把 yandex/yahoo/grokipedia/mojeek/wikipedia 全试一遍,
# 国内网络下 yandex 几乎必超时、grokipedia 时不时挂.把范围收敛到稳定 + 国内
# 可达(走代理)的几家,大幅降低单查询耗时.可用 DDGS_BACKENDS env 覆盖.
# Note: ddgs 库已移除 bing backend,实测可用列表 = brave/duckduckgo/grokipedia/
# mojeek/wikipedia/yahoo/yandex.yahoo 在 site:xueqiu.com 这类中文 site 限定 query
# 上能拿到结果,补它当 brave 限流时的兜底.
_DEFAULT_BACKENDS = "duckduckgo,brave,yahoo,mojeek"
# 单引擎调用超时(秒).ddgs 默认 10s — 偶尔超时累计起来 monitor 几十个 query
# 会被 backend 5 分钟 TIMEOUT_MONITOR 截断,所以拉短.
_DEFAULT_TIMEOUT = 8


def _ddgs_proxy() -> str | None:
    """搜索引擎在国内多数需要代理.读 HTTP(S)_PROXY env."""
    return (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        or None
    )


def _remote_search(remote_url: str, query: str, max_results: int,
                   region: str, timelimit: str | None) -> list[dict]:
    """走 ddg-proxy 远程调用 — 国内机房 fallback 到能访问 DDG 的出口节点."""
    token = (os.environ.get("DDG_REMOTE_TOKEN") or "").strip()
    headers = {"X-DDG-Token": token} if token else {}
    params: dict[str, str | int] = {
        "query": query,
        "max_results": max_results,
        "region": region,
    }
    if timelimit:
        params["timelimit"] = timelimit
    try:
        r = requests.get(remote_url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [ddg-remote] request failed: {e}", file=sys.stderr)
        return []
    try:
        data = r.json()
    except ValueError:
        print(f"  [ddg-remote] invalid JSON, len={len(r.text)}", file=sys.stderr)
        return []
    if data.get("status") == "error":
        print(f"  [ddg-remote] proxy error: {data.get('error')}", file=sys.stderr)
        return []
    return list(data.get("results") or [])


def ddg_search(query: str, max_results: int = 10,
               region: str = "wt-wt", safesearch: str = "off",
               timelimit: str | None = None) -> list[dict]:
    """Returns a list of {title, href, body} dicts.

    timelimit: 'd' (past day), 'w' (past week), 'm' (past month), 'y' (past year),
               or None (no limit).

    若 env DDG_REMOTE_URL 已设(如国内机房环境),改走远程 ddg-proxy 而非
    直连 DDG。token 通过 DDG_REMOTE_TOKEN env 提供。
    """
    remote_url = (os.environ.get("DDG_REMOTE_URL") or "").strip()
    if remote_url:
        return _remote_search(remote_url, query, max_results, region, timelimit)

    backends = os.environ.get("DDGS_BACKENDS") or _DEFAULT_BACKENDS
    try:
        timeout = int(os.environ.get("DDGS_TIMEOUT_S") or _DEFAULT_TIMEOUT)
    except ValueError:
        timeout = _DEFAULT_TIMEOUT
    proxy = _ddgs_proxy()
    # 不同 ddgs 版本签名略有差,用 try/except 兜一下旧版.
    try:
        d = DDGS(proxy=proxy, timeout=timeout)
    except TypeError:
        d = DDGS()
    with d:
        try:
            results = list(d.text(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=max_results,
                backend=backends,
            ))
        except TypeError:
            # 旧版 ddgs 不支持 backend 参数 — 退回 auto.
            results = list(d.text(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=max_results,
            ))
    return results


def throttle(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
