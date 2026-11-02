"""Brand ranking extraction — determine where a brand ranks in AI responses.

Analyzes AI-generated answers to extract the ordinal position of a target
brand in ordered lists and recommendations, producing rankings like "#1",
"#2", "Top 5", "Top 10", "Mentioned", "Not mentioned".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class BrandRanking:
    position: Optional[int]   # 1-based ordinal, None if not found
    mentioned: bool
    is_first: bool
    rank_label: str           # "#1", "#2", "Top 5", "Top 10", "Mentioned", "Not mentioned"
    context: str              # sentence/list-item where brand appears


# Chinese ordinal patterns
_ZH_ORDINALS = ["首先", "第一", "其次", "第二", "再次", "第三", "最后", "第四", "第五"]


def _rank_label(position: Optional[int], mentioned: bool) -> str:
    if not mentioned or position is None:
        return "Not mentioned"
    if position == 1:
        return "#1"
    if position == 2:
        return "#2"
    if position == 3:
        return "#3"
    if position <= 5:
        return "Top 5"
    if position <= 10:
        return "Top 10"
    return "Mentioned"


def _extract_ordered_items(text: str) -> List[str]:
    """Extract items from numbered/bulleted lists and bold sequences."""
    items: List[str] = []

    # Pattern 1: Numbered lists — "1. **Brand**" or "1. Brand"
    for m in re.finditer(
        r'(?:^|\n)\s*(\d+)[\.、)\]]\s*\*{0,2}([^\n*]{2,60})',
        text,
    ):
        item = m.group(2).strip().strip('*').strip()
        # Take first capitalized chunk as the entity
        entity = re.match(r'^([A-Z一-鿿][\w一-鿿\s&\-\.]{1,40})', item)
        if entity:
            items.append(entity.group(1).strip())

    # Pattern 2: Bold items — "**Brand Name**"
    for m in re.finditer(r'\*\*([^*]{2,40})\*\*', text):
        name = m.group(1).strip()
        if name and not name[0].islower():
            items.append(name)

    # Pattern 3: Chinese numbered — "一、品牌" "二、品牌"
    for m in re.finditer(r'[一二三四五六七八九十]+[、.）)]\s*([^\n]{2,40})', text):
        item = m.group(1).strip()
        entity = re.match(r'^([一-鿿\w\s&\-\.]{2,40})', item)
        if entity:
            items.append(entity.group(1).strip())

    # Pattern 4: Dash/bullet items — "- Brand" or "• Brand"
    for m in re.finditer(r'(?:^|\n)\s*[-•·]\s*\*{0,2}([^\n*]{2,60})', text):
        item = m.group(1).strip().strip('*').strip()
        entity = re.match(r'^([A-Z一-鿿][\w一-鿿\s&\-\.]{1,40})', item)
        if entity:
            items.append(entity.group(1).strip())

    return items


def _find_in_paragraphs(text: str, brand: str) -> Optional[int]:
    """Fallback: find brand position by scanning paragraphs in order."""
    brand_lower = brand.lower()
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

    entity_count = 0
    for para in paragraphs:
        # Count capitalized entities before/during this paragraph
        entities_in_para = re.findall(
            r'(?:^|[.!?。！？])\s*([A-Z一-鿿][\w一-鿿\s&\-\.]{1,30})',
            para,
        )
        if brand_lower in para.lower():
            entity_count += 1
            return entity_count
        entity_count += len(entities_in_para)

    return None


def extract_brand_ranking(answer: str, brand: str) -> BrandRanking:
    """Extract the ranking position of a brand within an AI answer.

    Args:
        answer: The AI-generated response text.
        brand: The brand/entity name to look for.

    Returns:
        BrandRanking with position, mention status, and context.
    """
    brand_lower = brand.lower()
    answer_lower = answer.lower()

    if brand_lower not in answer_lower:
        return BrandRanking(
            position=None, mentioned=False, is_first=False,
            rank_label="Not mentioned", context="",
        )

    # Extract ordered items from lists
    items = _extract_ordered_items(answer)

    # Find brand in ordered items (case-insensitive)
    position = None
    for i, item in enumerate(items, 1):
        if brand_lower in item.lower():
            position = i
            break

    # Fallback: paragraph scan
    if position is None:
        position = _find_in_paragraphs(answer, brand)

    # Extract context — sentence containing the brand mention
    context = ""
    sentences = re.split(r'[。！？.!?\n]', answer)
    for sent in sentences:
        if brand_lower in sent.lower():
            context = sent.strip()[:120]
            break

    mentioned = True
    is_first = position == 1
    rank_label = _rank_label(position, mentioned)

    return BrandRanking(
        position=position,
        mentioned=mentioned,
        is_first=is_first,
        rank_label=rank_label,
        context=context,
    )


def aggregate_rankings(
    results, brand: str,
) -> dict:
    """Aggregate brand rankings across multiple engine results.

    Returns a dict with per-engine rankings and overall summary.
    """
    per_engine = {}
    positions = []

    for r in results:
        if r.error or not r.answer:
            continue
        ranking = extract_brand_ranking(r.answer, brand)
        per_engine[r.engine] = {
            "position": ranking.position,
            "rank_label": ranking.rank_label,
            "mentioned": ranking.mentioned,
            "is_first": ranking.is_first,
        }
        if ranking.position is not None:
            positions.append(ranking.position)

    valid = [p for p in positions if p is not None]
    rank_dist: dict[str, int] = {}
    for e in per_engine.values():
        lbl = e["rank_label"]
        rank_dist[lbl] = rank_dist.get(lbl, 0) + 1

    return {
        "brand": brand,
        "per_engine": per_engine,
        "avg_position": round(sum(valid) / len(valid), 1) if valid else None,
        "best_position": min(valid) if valid else None,
        "rank_distribution": rank_dist,
        "engines_checked": len(per_engine),
        "engines_mentioned": sum(1 for e in per_engine.values() if e["mentioned"]),
    }
