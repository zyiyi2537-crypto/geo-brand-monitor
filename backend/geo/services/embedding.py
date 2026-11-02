"""文本 embedding(多供应商,OpenAI 兼容)—— 给 agent 资料 RAG 做向量语义检索。

供应商优先级:
  1) GLM 智谱(GLM_API_KEY,open.bigmodel.cn,model embedding-3)—— 项目已在用、账户正常
  2) 通义 DashScope(QWEN_API_KEY / DASHSCOPE_API_KEY,text-embedding-v3)
无任何 key 时 embedding_enabled()=False,ask_knowledge 自动回退 bigram 关键词检索。
"""
from __future__ import annotations

import math
import os


def _provider() -> tuple[str | None, str, str, str]:
    """返回 (provider, url, model, key);无 key 返回 (None, ...)。

    顺序:OpenAI(有 key 且支持 embedding)→ GLM 智谱 → DashScope 通义。
    可用 AGENT_EMBED_PROVIDER 强制指定(openai/glm/dashscope)。
    """
    force = (os.environ.get("AGENT_EMBED_PROVIDER") or "").strip().lower()

    oa = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if oa and force in ("", "openai"):
        base = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        return "openai", f"{base}/embeddings", os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small"), oa

    glm = (os.environ.get("GLM_API_KEY") or "").strip()
    if glm and force in ("", "glm"):
        base = (os.environ.get("GLM_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4/").rstrip("/")
        return "glm", f"{base}/embeddings", os.environ.get("GLM_EMBED_MODEL", "embedding-3"), glm

    qwen = (os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if qwen and force in ("", "dashscope"):
        url = os.environ.get("DASHSCOPE_EMBED_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings")
        return "dashscope", url, os.environ.get("AGENT_EMBED_MODEL", "text-embedding-v3"), qwen

    return None, "", "", ""


def embedding_enabled() -> bool:
    return _provider()[0] is not None


def current_provider() -> str | None:
    return _provider()[0]


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """批量 embedding;失败/无 key 返回 None(调用方回退关键词)。input 截断到 ~2000 字。"""
    import httpx

    provider, url, model, key = _provider()
    cleaned = [(t or "")[:2000] for t in texts if (t or "").strip()]
    if not provider or not cleaned:
        return None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=8) as client:   # 短超时:供应商不可用时快速回退 bigram
            r = await client.post(url, json={"model": model, "input": cleaned}, headers=headers)
            r.raise_for_status()
            data = sorted(r.json().get("data", []), key=lambda d: d.get("index", 0))
            vecs = [d["embedding"] for d in data]
            return vecs if len(vecs) == len(cleaned) else None
    except Exception:  # noqa: BLE001 — embedding 失败不阻断,回退关键词
        return None


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
