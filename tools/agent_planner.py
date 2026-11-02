"""Small OpenAI-compatible planner used by the desktop GEO task form."""

from __future__ import annotations

import json
import re

try:
    from .model_client import chat_content, endpoint
except ImportError:
    from model_client import chat_content, endpoint


def _endpoint(base_url: str) -> str:
    return endpoint(base_url)


def _extract_questions(content: object) -> list[str]:
    if not isinstance(content, str):
        raise ValueError("模型没有返回文字内容")
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    candidates = [fenced.group(1).strip()] if fenced else []
    candidates.append(text)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            value = value.get("questions")
        if isinstance(value, list):
            questions = [item.strip() for item in value if isinstance(item, str) and item.strip()]
            if questions:
                return list(dict.fromkeys(questions))[:50]

    # Tolerate a model that ignores the JSON instruction and returns a numbered list.
    questions = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", line).strip()
        if line.endswith(("?", "？")) and len(line) >= 4:
            questions.append(line)
    if questions:
        return list(dict.fromkeys(questions))[:50]
    raise ValueError("模型返回内容中没有可识别的问题列表")


def generate_questions(
    *,
    brand: str,
    article_urls: list[str],
    keywords: list[str],
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = 90,
    wire_api: str = "chat",
) -> list[str]:
    """Generate natural user questions through an OpenAI-compatible chat API."""
    if not api_key.strip():
        raise ValueError("API Key 不能为空")
    if not model.strip():
        raise ValueError("模型名称不能为空")
    prompt = (
        "你是 GEO 监测任务规划 Agent。请根据目标品牌、已发布文章链接和关键词，"
        "生成用于询问 DeepSeek、豆包、元宝、文心一言、通义千问的自然中文用户问题。"
        "问题要围绕行业选型、供应商比较、产品能力、稳定性、交付、应用场景等真实搜索意图，"
        "不要把目标品牌强行写进每个问题，避免诱导回答。只返回 JSON 数组，数组元素是问题字符串，"
        "最多 20 个，不要输出解释。\n\n"
        f"目标品牌：{brand.strip()}\n"
        f"已发布文章链接：{json.dumps(article_urls, ensure_ascii=False)}\n"
        f"关键词：{json.dumps(keywords, ensure_ascii=False)}"
    )
    content = chat_content(
        base_url=base_url, api_key=api_key, model=model, timeout=timeout, wire_api=wire_api,
        messages=[
            {"role": "system", "content": "你只输出合法 JSON，不要 Markdown。"},
            {"role": "user", "content": prompt},
        ],
    )
    return _extract_questions(content)
