#!/usr/bin/env python3
"""Vigilath GEO agent 轻客户端 —— 让宿主 agent(小龙虾)链接 Vigilath GEO agent。

零三方依赖(纯标准库),drop-in 即用。鉴权走环境变量,token 绝不硬编码/打印。

用法:
  python geo_client.py chat "今天投放效果怎么样?"
  python geo_client.py data today          # today / coverage / report ...
  python geo_client.py capabilities        # 当前 token 能做什么

凭证来源(优先级:环境变量 > ~/.vigilath/config):
  VIGILATH_AGENT_TOKEN   1 年期账号 token(Vigilath 领号发放),必填
  VIGILATH_BASE          选填,默认 https://geo.vigilath.com/api/agent/v1
一行安装(install.sh)会把 token 写进 ~/.vigilath/config,装完直接可用、无需设环境变量。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _load_config() -> dict:
    """读 ~/.vigilath/config(KEY=VALUE 行),给免设环境变量的安装方式用。"""
    cfg: dict[str, str] = {}
    path = os.path.expanduser("~/.vigilath/config")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return cfg


_CFG = _load_config()


def _conf(key: str, default: str = "") -> str:
    return (os.environ.get(key) or _CFG.get(key) or default).strip()


BASE = _conf("VIGILATH_BASE", "https://geo.vigilath.com/api/agent/v1").rstrip("/")


def _die(msg: str, code: int = 1) -> "None":
    print(f"[vigilath-geo] 错误:{msg}", file=sys.stderr)
    sys.exit(code)


def _headers() -> dict:
    token = _conf("VIGILATH_AGENT_TOKEN")
    if not token:
        _die("缺少 token —— 跑一行安装,或设环境变量 VIGILATH_AGENT_TOKEN / 写进 ~/.vigilath/config。")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _explain_http(e: urllib.error.HTTPError) -> str:
    try:
        body = e.read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        body = ""
    hint = {
        401: "token 无效 / 过期 / 已禁用 —— 联系 Vigilath 重发,别重试刷接口。",
        403: "无权限(能力未授权,或 Origin 不在白名单)。",
        429: "账号配额 / 限速,稍后退避重试。",
    }.get(e.code, "")
    return f"HTTP {e.code} {hint} {body}".strip()


def _request(req: urllib.request.Request, timeout: int):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        _die(_explain_http(e))
    except urllib.error.URLError as e:
        _die(f"连不上 Vigilath({BASE}):{e.reason}")


def chat(message: str) -> dict:
    """对话:流式收 delta + cards,返回 {'text': ..., 'cards': [...]}。"""
    req = urllib.request.Request(
        f"{BASE}/chat",
        method="POST",
        data=json.dumps({"message": message}).encode("utf-8"),
        headers=_headers(),
    )
    text_parts: list[str] = []
    cards: list = []
    with _request(req, timeout=180) as resp:
        for raw in resp:                                  # SSE:逐行 data: {...}
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            try:
                evt = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if "delta" in evt:
                text_parts.append(evt["delta"])
            elif "cards" in evt:
                cards = evt["cards"]
            elif "error" in evt:
                _die(evt["error"])
    return {"text": "".join(text_parts), "cards": cards}


def get(path: str, timeout: int = 30) -> dict:
    """GET 一个只读端点(如 data/today、meta/capabilities)。"""
    req = urllib.request.Request(f"{BASE}/{path.lstrip('/')}", headers=_headers())
    with _request(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list) -> "None":
    if len(argv) < 2:
        _die('用法:geo_client.py chat "问题" | data <name> | capabilities')
    cmd = argv[1]
    if cmd == "chat":
        if len(argv) < 3:
            _die('chat 需要一个问题参数,如:chat "今天投放效果?"')
        out = chat(argv[2])
        print(out["text"].strip())
        if out["cards"]:
            print("\n--- 结构化卡片(把数字念给用户)---")
            print(json.dumps(out["cards"], ensure_ascii=False, indent=2))
    elif cmd == "data":
        if len(argv) < 3:
            _die("data 需要名字:today / coverage / report ...")
        print(json.dumps(get(f"data/{argv[2]}"), ensure_ascii=False, indent=2))
    elif cmd == "capabilities":
        print(json.dumps(get("meta/capabilities"), ensure_ascii=False, indent=2))
    else:
        _die(f"未知命令:{cmd}(支持 chat / data / capabilities)")


if __name__ == "__main__":
    main(sys.argv)
