"""Validate answer-backed brand entities and aggregate comparable mention counts."""
from __future__ import annotations

import re
import unicodedata

ENGINE_NAMES = {"deepseek": "DeepSeek", "doubao": "豆包", "yuanbao": "元宝",
                "wenxin": "文心一言", "qwen": "千问"}


def brand_key(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def _contains(text: str, name: str) -> bool:
    pattern = re.escape(name)
    if name and name[0].isascii() and name[0].isalnum():
        pattern = r"(?<![A-Za-z0-9])" + pattern
    if name and name[-1].isascii() and name[-1].isalnum():
        pattern += r"(?![A-Za-z0-9])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def validate_mentions(value: object, answer: str) -> list[dict]:
    """Every entity needs an observed alias and a verbatim answer quotation."""
    if not isinstance(value, list):
        raise ValueError("品牌提及结果必须是数组")
    clean = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("品牌提及条目必须是对象")
        name, aliases, quote = item.get("name"), item.get("aliases"), item.get("evidence_quote")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100 or not brand_key(name):
            raise ValueError("品牌名称无效")
        if (not isinstance(aliases, list) or not aliases
                or any(not isinstance(a, str) or not a.strip() or len(a) > 100
                       or not _contains(answer, a.strip()) for a in aliases)):
            raise ValueError("品牌别名必须出现在本平台回答中")
        aliases = list(dict.fromkeys(a.strip() for a in aliases))
        if (not isinstance(quote, str) or not quote.strip() or len(quote) > 300
                or quote not in answer or not any(_contains(quote, a) for a in aliases)):
            raise ValueError("品牌依据必须是包含该品牌的连续回答原文")
        clean.append({"name": name.strip(), "aliases": aliases, "evidence_quote": quote})
    return clean


def mention_data(row: dict) -> list[dict] | None:
    raw = row.get("brand_mentions")
    if raw is None and isinstance(row.get("ai_verdict"), dict):
        raw = row["ai_verdict"].get("mentioned_brands")
    try:
        return validate_mentions(raw, row.get("answer") or "")
    except (ValueError, TypeError):
        return None


def summarize_mentions(config: dict, results: list[dict]) -> dict:
    def question_key(value: object) -> str:
        return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""

    questions = list(dict.fromkeys(question_key(q) for q in config.get("questions", []) if question_key(q)))
    selected = {}
    for row in results:
        if (not isinstance(row, dict) or row.get("error") or not isinstance(row.get("answer"), str)
                or not row["answer"].strip() or row.get("engine") not in ENGINE_NAMES
                or question_key(row.get("query")) not in questions):
            continue
        selected.setdefault((question_key(row.get("query")), row["engine"]), row)
    analyzed = {key: mention_data(row) for key, row in selected.items()}
    analyzed = {key: value for key, value in analyzed.items() if value is not None}
    groups = []
    target_key = brand_key(config.get("brand", ""))
    # Merge only explicit identity keys/aliases, never arbitrary substrings.
    for key, mentions in analyzed.items():
        for mention in mentions:
            identities = {brand_key(mention["name"]), *(brand_key(a) for a in mention["aliases"])} - {""}
            overlapping = [g for g in groups if g["identities"] & identities]
            group = overlapping[0] if overlapping else {
                "name": mention["name"], "identities": set(), "aliases": set(), "hits": {},
            }
            if not overlapping:
                groups.append(group)
            for other in overlapping[1:]:
                group["identities"].update(other["identities"])
                group["aliases"].update(other["aliases"])
                group["hits"].update(other["hits"])
                groups.remove(other)
            group["identities"].update(identities)
            group["aliases"].update(mention["aliases"])
            group["hits"].setdefault(key, mention["evidence_quote"])
    for group in groups:
        group["target"] = target_key in group["identities"]
        if group["target"]:
            group["name"] = config["brand"]
        group["count"] = len(group["hits"])
        group["questions"] = len({q for q, _ in group["hits"]})
        group["platforms"] = {e: sum(engine == e for _, engine in group["hits"]) for e in ENGINE_NAMES}
        group["evidence"] = [{"question": questions.index(q) + 1, "engine": e, "quote": quote}
                             for (q, e), quote in sorted(group["hits"].items(),
                                                        key=lambda h: (questions.index(h[0][0]), list(ENGINE_NAMES).index(h[0][1])))]
        group["aliases"] = sorted(group["aliases"], key=str.casefold)
    others = sorted((g for g in groups if not g["target"]),
                    key=lambda g: (-g["count"], -g["questions"], brand_key(g["name"])))
    return {"answered": len(selected), "analyzed": len(analyzed),
            "question_total": len({q for q, _ in analyzed}),
            "platform_totals": {e: sum(engine == e for _, engine in analyzed) for e in ENGINE_NAMES},
            "brands": others, "target": next((g for g in groups if g["target"]), None)}
