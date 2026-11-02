"""DeepSeek 纯 HTTP 引擎 —— 不开浏览器,直接打 chat.deepseek.com 的内部 API。

为什么能做:deepseek 网页就是一套 Bearer-token 的 HTTP API。流程:
  1. 从登录态(storage_state.localStorage.userToken)拿 Bearer token;
  2. POST /chat_session/create 建会话;
  3. POST /chat/create_pow_challenge 拿 PoW 挑战;
  4. 用 deepseek 自己的 wasm(sha3_wasm.wasm)算 PoW —— 算法全在 wasm 里,
     wasmtime 直接调 wasm_solve(wasm-bindgen 约定),它改算法只需重下 wasm;
  5. POST /chat/completion 带 X-Ds-Pow-Response 头 → 流式返回答案 + 联网引用。

结果与网页**完全一致**(同一个内部接口),但秒级、可大并发、无 cloakbrowser/Xvfb/DOM。
账号池仍用于拿 token(check-out/check-in 在调用方做),本模块只负责"一次查询"。
"""

from __future__ import annotations

import base64
import json
import os
import struct
from typing import Optional
from urllib.parse import urlparse

import httpx

_BASE = "https://chat.deepseek.com/api/v0"
_WASM_PATH = os.path.join(os.path.dirname(__file__), "sha3_wasm.wasm")

# ── wasm PoW solver(进程内单例)──────────────────────────────────
_wasm = None


def _load_wasm():
    """懒加载 deepseek 的 sha3 wasm,返回 (store, exports)。"""
    global _wasm
    if _wasm is not None:
        return _wasm
    import wasmtime

    store = wasmtime.Store()
    module = wasmtime.Module.from_file(store.engine, _WASM_PATH)
    inst = wasmtime.Instance(store, module, [])
    ex = inst.exports(store)
    _wasm = (store, ex)
    return _wasm


def solve_pow(challenge: dict) -> Optional[int]:
    """用 deepseek 的 wasm 算 PoW,返回 answer(nonce);失败返回 None。

    challenge: {algorithm, challenge, salt, signature, difficulty, expire_at, target_path}
    调用约定(wasm-bindgen):wasm_solve(retptr, ch_ptr, ch_len, prefix_ptr, prefix_len, difficulty_f64),
    结果写在 retptr:status(i32) + value(f64);prefix = "{salt}_{expire_at}_"。
    """
    store, ex = _load_wasm()
    mem = ex["memory"]
    malloc = ex["__wbindgen_export_0"]
    add_sp = ex["__wbindgen_add_to_stack_pointer"]
    wasm_solve = ex["wasm_solve"]

    def w_str(s: str):
        b = s.encode("utf-8")
        ptr = malloc(store, len(b), 1)
        mem.write(store, b, ptr)
        return ptr, len(b)

    prefix = f"{challenge['salt']}_{challenge['expire_at']}_"
    retptr = add_sp(store, -16)
    cptr, clen = w_str(challenge["challenge"])
    pptr, plen = w_str(prefix)
    wasm_solve(store, retptr, cptr, clen, pptr, plen, float(challenge["difficulty"]))
    status = struct.unpack("<i", mem.read(store, retptr, retptr + 4))[0]
    value = struct.unpack("<d", mem.read(store, retptr + 8, retptr + 16))[0]
    add_sp(store, 16)
    return int(value) if status else None


def _make_pow_header(challenge: dict) -> Optional[str]:
    ans = solve_pow(challenge)
    if ans is None:
        return None
    obj = {
        "algorithm": challenge["algorithm"],
        "challenge": challenge["challenge"],
        "salt": challenge["salt"],
        "answer": ans,
        "signature": challenge["signature"],
        "target_path": challenge["target_path"],
    }
    return base64.b64encode(json.dumps(obj).encode()).decode()


# ── token 提取 ───────────────────────────────────────────────────
def extract_token(storage_state: dict) -> Optional[str]:
    """从登录态 localStorage.userToken 取 Bearer token。"""
    for o in (storage_state or {}).get("origins", []):
        ls = o.get("localStorage", [])
        if isinstance(ls, dict):
            ls = [{"name": k, "value": v} for k, v in ls.items()]
        for it in ls:
            if it.get("name") == "userToken":
                raw = it.get("value")
                try:
                    return json.loads(raw).get("value")
                except Exception:  # noqa: BLE001
                    return raw
    return None


# ── 流式响应解析 ─────────────────────────────────────────────────
def _parse_stream(lines) -> tuple[str, list]:
    """解析 deepseek 的 path-based 增量流:
      {"p":"response/content","o":"APPEND","v":"..."} + 后续裸 {"v":"..."} 续接答案;
      {"p":"response/search_results","v":[{url,title,snippet}...]} 是引用。
    """
    text = ""
    citations: list = []
    seen_urls: set = set()
    current = None
    for line in lines:
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            ev = json.loads(payload)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(ev, dict):
            continue
        if "p" in ev:
            current = ev["p"]
        v = ev.get("v")
        # 引用:累积 + 按 url 去重(deepseek 可能分多个 search_results 事件增量发,
        # 早先版本 `citations = v` 覆盖会丢掉前面批次 → 引用数被压到最后一批的量)
        if ev.get("p") == "response/search_results" and isinstance(v, list):
            for c in v:
                if isinstance(c, dict):
                    u = c.get("url", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        citations.append(c)
        elif current == "response/content" and isinstance(v, str):
            text += v
    cites = []
    for i, c in enumerate(citations):
        url = c.get("url", "")
        try:
            domain = urlparse(url).netloc
        except Exception:  # noqa: BLE001
            domain = ""
        cites.append({
            "url": url,
            "domain": domain,
            "title": c.get("title", ""),
            "snippet": c.get("snippet", ""),
            "position": i + 1,
        })
    return text.strip(), cites


# ── 主入口 ───────────────────────────────────────────────────────
def run_deepseek_http(
    storage_state: dict,
    query: str,
    *,
    proxy: Optional[str] = None,
    search: bool = True,
    timeout: float = 90.0,
) -> dict:
    """一次 deepseek 查询(纯 HTTP)。返回 {engine, query, answer, citations, error}。

    error 取值约定(供调用方 check-in 映射 FailureType):
      'login_lost' —— token 失效(401);'pow_failed' —— PoW 算不出;其余为原始错误串。
    """
    result = {"engine": "deepseek", "query": query, "answer": "", "citations": [], "error": None}
    token = extract_token(storage_state)
    if not token:
        result["error"] = "login_lost"
        return result
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    }
    try:
        with httpx.Client(timeout=timeout, headers=headers, proxy=proxy) as c:
            s = c.post(f"{_BASE}/chat_session/create", json={"character_id": None})
            if s.status_code in (401, 403):
                result["error"] = "login_lost"
                return result
            sid = s.json()["data"]["biz_data"]["id"]

            p = c.post(f"{_BASE}/chat/create_pow_challenge",
                       json={"target_path": "/api/v0/chat/completion"})
            challenge = p.json()["data"]["biz_data"]["challenge"]
            pow_header = _make_pow_header(challenge)
            if pow_header is None:
                result["error"] = "pow_failed"
                return result

            body = {
                "chat_session_id": sid,
                "parent_message_id": None,
                "prompt": query,
                "ref_file_ids": [],
                "thinking_enabled": False,
                "search_enabled": search,
            }
            with c.stream("POST", f"{_BASE}/chat/completion", json=body,
                          headers={"X-Ds-Pow-Response": pow_header}) as r:
                if r.status_code in (401, 403):
                    result["error"] = "login_lost"
                    return result
                # 业务层错误(如 PoW 被拒)在流首行
                lines = list(r.iter_lines())
            if lines and lines[0].lstrip().startswith("{") and "INVALID_POW" in lines[0]:
                result["error"] = "pow_failed"
                return result
            # 账号被 deepseek 风控禁言:completion 首行返回 biz_msg "user is muted"
            # → 标 rate_limited,让上层 failover 换号(临时禁言,不是登录失效)
            if lines and '"user is muted"' in lines[0]:
                result["error"] = "rate_limited"
                try:
                    bd = json.loads(lines[0]).get("data", {}).get("biz_data", {})
                    result["mute_until"] = bd.get("mute_until")
                except Exception:  # noqa: BLE001
                    pass
                print(f"[deepseek-http][muted] mute_until={result.get('mute_until')}", flush=True)
                return result
            text, cites = _parse_stream(lines)
            result["answer"] = text
            result["citations"] = cites
            if not text:
                result["error"] = "empty_answer"
    except Exception as e:  # noqa: BLE001
        result["error"] = repr(e)[:200]
    return result


def deepseek_http_enabled() -> bool:
    """DEEPSEEK_HTTP_MODE=1 且 wasm 文件就位时启用 HTTP 路径。"""
    return os.environ.get("DEEPSEEK_HTTP_MODE", "").strip() in ("1", "true", "True") \
        and os.path.exists(_WASM_PATH)
