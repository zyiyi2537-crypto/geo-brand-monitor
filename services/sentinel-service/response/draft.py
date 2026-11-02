"""Response draft generator (OpenAI).

For one post (or topic + custom situation), produce three response drafts at
different risk postures: conservative / standard / proactive. Knowledge base
files in mvp/knowledge/ are concatenated into the system prompt, so OpenAI's
automatic prompt caching can amortize that prefix across calls.

Output is for human review, never auto-published (HITL by design).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import openai

from storage import (
    connect, init_schema, brand_post_lookup, insert_draft,
)
from llm_client import chat_create, has_openai, has_qwen

DRAFT_MODEL = os.environ.get("YUQING_DRAFT_MODEL", "gpt-4.1")
MAX_TOKENS = 3000
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

DRAFT_SYSTEM_HEADER = """你是一名公关 + 投资者关系 (IR) 联合岗位的资深从业者，正在为一家上市公司起草外发回应草稿。

输出三个版本的草稿（保守版 / 标准版 / 主动版），格式为 JSON：

{
  "summary": "对当前情况的判断 (≤50 字)",
  "drafts": [
    {
      "variant": "conservative",
      "body": "回应正文（中文，可直接发布）",
      "rationale": "为什么这个版本合适",
      "predicted_effect": "预期舆论反应",
      "cautions": "发布前需要确认的事项 / 风险点"
    },
    {"variant": "standard", ...},
    {"variant": "proactive", ...}
  ],
  "recommendation": "推荐使用哪一版及理由 (1-2 句)",
  "hitl_required": true,
  "hitl_notes": "必须由谁审核（法务 / IR / 管理层），原因"
}

## 规则
- 严格遵守下文中的"品牌语调"和"法务红线"，违反红线的选项必须在 cautions 中明确指出并避免
- 不要承诺未确认的事实；如有不确定，写"以公司公告为准"
- 严格输出 JSON，不要附加任何额外文字 / 代码块标记

---

## 知识库

"""


def _load_knowledge() -> str:
    parts = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        parts.append(f"### {path.stem}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _system_prompt() -> str:
    return DRAFT_SYSTEM_HEADER + _load_knowledge()


def _post_payload(post) -> dict:
    return {
        "source": post["source"],
        "post_id": post["post_id"],
        "author": post["author"],
        "title": post["title"],
        "content": post["content"],
        "publish_time": post["publish_time"],
        "view_count": post["view_count"],
        "reply_count": post["reply_count"],
        "url": post["url"],
        "summary": post["summary"],
        "sentiment_label": post["sentiment_label"],
        "risk_level": post["risk_level"],
        "topics": json.loads(post["topics_json"] or "[]") if post["topics_json"] else [],
        "intent": post["intent"],
        "stance": post["stance"],
    }


def generate_drafts(symbol: str, source: str | None = None,
                    post_id: str | None = None, topic: str | None = None,
                    situation: str | None = None,
                    db_path=None) -> dict:
    if not (post_id or topic):
        sys.exit("supply either --post-id (with --source) or --topic")
    if not (has_openai() or has_qwen()):
        sys.exit("no LLM key available. Set OPENAI_API_KEY (sk-...) or QWEN_API_KEY.")

    conn = connect(db_path) if db_path else connect()
    init_schema(conn)

    if post_id:
        if not source:
            source = "eastmoney"
        post = brand_post_lookup(conn, source, post_id)
        if not post:
            sys.exit(f"post not found: source={source} post_id={post_id}")
        target = {"type": "post", "data": _post_payload(post)}
    else:
        target = {
            "type": "topic", "symbol": symbol, "topic": topic,
            "situation": situation or "",
        }

    user_msg = (
        f"为 {symbol} 起草三档回应。情况如下：\n\n"
        f"```json\n{json.dumps(target, ensure_ascii=False, indent=2)}\n```\n\n"
        "请按系统说明输出 JSON。"
    )

    resp = chat_create(
        DRAFT_MODEL,
        max_completion_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user_msg},
        ],
    )
    text = resp.choices[0].message.content or "{}"
    result = json.loads(text)

    for d in result.get("drafts", []):
        insert_draft(
            conn, symbol=symbol, source=source, post_id=post_id, topic=topic,
            variant=d.get("variant", "?"),
            body=d.get("body", ""),
            rationale=d.get("rationale"),
            predicted_effect=d.get("predicted_effect"),
            cautions=d.get("cautions"),
            model=DRAFT_MODEL,
        )
    conn.commit()

    details = getattr(resp.usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    print(f"[drafts] {symbol} → {len(result.get('drafts', []))} variants saved")
    print(f"  in={resp.usage.prompt_tokens} out={resp.usage.completion_tokens} "
          f"cached={cached}")
    return result
