"""元宝引擎(API 模式)= 腾讯元宝联网搜索(SearchPro)+ deepseek 合成,模拟元宝网页作答。

替代脆弱的浏览器账号:不开浏览器、不占账号池,纯 API。流程:
  query → SearchPro 取网页(Cnt 必须 10/20/30/40/50)→ 模拟元宝网页的提示词喂 deepseek
  → 合成带「参考来源」的中文答案 → 返回 {answer, citations}(与其它引擎同构,可做命中判定)。

deepseek 走与 agent 一致的通道(OPENROUTER_API_KEY + OPENROUTER_BASE_URL,模型默认
deepseek/deepseek-v4-flash)。SearchPro key 走 TENCENT_SEARCH_API_KEY。两者都只读 env,
不进代码。任一 key 缺失则返回 error(上层会回退/记错,不杜撰)。

ENV:
- TENCENT_SEARCH_API_KEY   必填,腾讯云联网搜索 SearchPro 的 sk- key
- TENCENT_SEARCH_CNT        可选,取多少条(10/20/30/40/50),默认 10
- OPENROUTER_API_KEY        合成用(与 agent 同一把)
- OPENROUTER_BASE_URL       可选,默认 https://openrouter.ai/api/v1
- YUANBAO_SYNTH_MODEL       可选,默认 deepseek/deepseek-v4-flash
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("telemetry-service.yuanbao")

SEARCHPRO_URL = "https://api.wsa.cloud.tencent.com/SearchPro"

_YUANBAO_SYS = (
    "你是腾讯元宝网页版助手。请基于下方「联网搜索结果」用简洁中文回答用户问题:\n"
    "- 直接给结论,必要时分点说明;\n"
    "- 只依据搜索结果作答,信息不足就如实说明,绝不杜撰;\n"
    "- 末尾用「参考来源」列出实际引用到的序号与标题。"
)


def yuanbao_api_enabled() -> bool:
    return bool(os.environ.get("TENCENT_SEARCH_API_KEY", "").strip())


def _err(query: str, msg: str) -> dict[str, Any]:
    return {"engine": "yuanbao", "query": query, "answer": "", "citations": [],
            "video_url": None, "source_url": None, "error": msg}


async def run_yuanbao(client: httpx.AsyncClient, query: str, *, timeout: float = 60.0) -> dict[str, Any]:
    search_key = os.environ.get("TENCENT_SEARCH_API_KEY", "").strip()
    if not search_key:
        return _err(query, "TENCENT_SEARCH_API_KEY 未配置")
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not or_key:
        return _err(query, "OPENROUTER_API_KEY 未配置(合成需要)")
    or_base = (os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/")
    model = (os.environ.get("YUANBAO_SYNTH_MODEL") or "deepseek/deepseek-v4-flash").strip()
    cnt = int(os.environ.get("TENCENT_SEARCH_CNT", "10"))
    if cnt not in (10, 20, 30, 40, 50):
        cnt = 10

    # 1) 元宝联网搜索
    try:
        r = await client.post(SEARCHPRO_URL, json={"Query": query, "Cnt": cnt},
                              headers={"Authorization": f"Bearer {search_key}"}, timeout=timeout)
        r.raise_for_status()
        resp = r.json().get("Response", {})
        if "Error" in resp:
            return _err(query, f"searchpro: {resp['Error'].get('Message', 'error')}")
        pages_raw = resp.get("Pages", []) or []
        pages = []
        for p in pages_raw:
            try:
                pages.append(json.loads(p) if isinstance(p, str) else p)
            except (ValueError, TypeError):
                continue
    except Exception as e:  # noqa: BLE001
        return _err(query, f"searchpro exception: {e}")

    if not pages:
        return _err(query, "searchpro: 无结果")

    use = pages[:6]
    context = "\n".join(
        f"[{i+1}] {p.get('title','')} — {p.get('site','')}\n{(p.get('passage') or '')[:300]}"
        for i, p in enumerate(use)
    )
    citations = [{
        "url": p.get("url", ""), "domain": p.get("site", ""),
        "title": p.get("title", ""), "snippet": (p.get("passage") or "")[:200],
        "position": i + 1,
    } for i, p in enumerate(use)]

    # 2) 模拟元宝网页合成(deepseek,走 agent 同一通道)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _YUANBAO_SYS},
            {"role": "user", "content": f"问题:{query}\n\n联网搜索结果:\n{context}"},
        ],
        "max_tokens": 800,
        "temperature": 0.3,
    }
    try:
        r = await client.post(f"{or_base}/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {or_key}",
                                       "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "https://vigilath.ai")},
                              timeout=timeout)
        r.raise_for_status()
        answer = (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:  # noqa: BLE001
        return _err(query, f"synth exception: {e}")

    if not answer:
        return _err(query, "synth: 空答案")
    return {"engine": "yuanbao", "query": query, "answer": answer,
            "citations": citations, "video_url": None, "source_url": None, "error": None}
