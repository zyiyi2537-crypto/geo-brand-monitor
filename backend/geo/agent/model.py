"""DeepSeek 大脑模型工厂(OpenAI 兼容)——对齐 query_expander 的 provider 回退:
   优先 DEEPSEEK_API_KEY 直连,否则用 OPENROUTER_API_KEY 走 OpenRouter 调 deepseek-chat。

注意:此处 DeepSeek 是**当大脑的 API 模型**,与「被观测的 DeepSeek 网页引擎(走 browser-service)」是两条线。
"""
from __future__ import annotations

import os


# 场景 → 默认模型:对话快(flash),诊断/重活强(pro)。env AGENT_MODEL_CHAT / AGENT_MODEL_PRO 可覆盖。
_SCENE_DEFAULT = {"chat": "deepseek-v4-flash", "pro": "deepseek-v4-pro"}


def get_deepseek_model(scene: str = "chat"):
    """构造 Pydantic AI 模型(按场景选型号)。无 pydantic-ai / 无任何 key 时给出明确报错。

    scene: 'chat'(对话,默认快模型 v4-flash)/ 'pro'(诊断等重活,v4-pro)。
    覆盖:env AGENT_MODEL_CHAT / AGENT_MODEL_PRO(填官方模型名,如 deepseek-v4-pro / deepseek-chat)。
    """
    try:
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("未安装 pydantic-ai,请先 `pip install pydantic-ai-slim[openai]`") from e

    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    name = (os.environ.get(f"AGENT_MODEL_{scene.upper()}") or "").strip() or _SCENE_DEFAULT.get(scene, "deepseek-v4-pro")

    if ds_key:
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        model_name = name                                     # 官方直连:用原始模型名
        provider = OpenAIProvider(base_url=base_url, api_key=ds_key)
    elif or_key:
        base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        model_name = name if "/" in name else f"deepseek/{name}"   # OpenRouter:补 deepseek/ 前缀
        provider = OpenAIProvider(base_url=base_url, api_key=or_key)
    else:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 或 OPENROUTER_API_KEY")

    return OpenAIModel(model_name, provider=provider)
