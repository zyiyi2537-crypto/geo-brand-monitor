"""雪球直采适配器 —— 经独立 scrapling-venv 子进程(StealthyFetcher 过 WAF)。

雪球有 JS WAF,纯请求过不去,必须真浏览器。Scrapling 浏览器栈与 fastapi 服务的
anyio 版本冲突,故隔离在 `/opt/geo/scrapling-venv`,本适配器通过 subprocess 调用
`xueqiu_fetch.py`(在那个 venv 里跑),拿回 JSON。WAF 过后搜索页公开,**无需 cookie**。

`SCRAPLING_PYTHON` 环境变量可覆盖 scrapling venv 的 python 路径。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_SCRAPLING_PY = os.environ.get("SCRAPLING_PYTHON", "/opt/geo/scrapling-venv/bin/python")
_FETCH = os.path.join(os.path.dirname(__file__), "xueqiu_fetch.py")


def xueqiu_search(query: str, max_results: int = 20,
                  timelimit: str | None = None) -> list[dict]:
    """返回 [{title,href,body,publish_time,author}]。子进程/解析失败 → []。"""
    if not os.path.exists(_SCRAPLING_PY):
        print(f"  [xueqiu] scrapling venv 不存在: {_SCRAPLING_PY}", file=sys.stderr)
        return []
    try:
        p = subprocess.run([_SCRAPLING_PY, _FETCH, query, str(max_results)],
                           capture_output=True, text=True, timeout=150)
    except Exception as e:
        print(f"  [xueqiu] subprocess error: {e}", file=sys.stderr)
        return []
    if p.returncode != 0:
        print(f"  [xueqiu] exit {p.returncode}: {p.stderr[-200:]}", file=sys.stderr)
        return []
    line = (p.stdout or "").strip().splitlines()
    if not line:
        return []
    try:
        data = json.loads(line[-1])           # 末行是 JSON(忽略可能的日志行)
    except Exception as e:
        print(f"  [xueqiu] bad json: {e}", file=sys.stderr)
        return []
    if isinstance(data, dict) and data.get("error"):
        print(f"  [xueqiu] fetch error: {data['error']}", file=sys.stderr)
        return []
    return data if isinstance(data, list) else []


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "世纪互联"
    rows = xueqiu_search(q, max_results=10)
    print(f"query={q!r} → {len(rows)} 条")
    for r in rows:
        print(f"  {r['publish_time']!s:<17} @{r['author']}: {r['body'][:54]}  {r['href']}")
