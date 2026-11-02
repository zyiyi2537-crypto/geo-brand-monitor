"""v1.1 — Cell 级 LLM 诊断 按需触发 + window cache.

调用方:backend /ai-telemetry/topics/{tid}/cell-insight?query=...&engine=...&force=...

策略:
- 默认窗口 = 近 7 天(以最近一次跑批的 created_at 为 anchor,前 7 天)
- cache 命中条件:存在同 (topic, query, engine, window_end, prompt_version) 行,
  且 evidence_response_ids 集合相同(=本期没新数据)
- force=1 → 强制重算(用户在 drawer 点"重新分析")
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .storage import (
    db_session, ResponseORM, CellInsightORM, TopicORM,
    parse_target,
)
from .llm import generate_cell_insight, CELL_PROMPT_VERSION

log = logging.getLogger(__name__)

WINDOW_DAYS = 7
MAX_RESPONSES_IN_WINDOW = 20


def _gather_window_responses(s, topic_id: int, query: str, engine: str) -> list[ResponseORM]:
    cutoff = datetime.utcnow() - timedelta(days=WINDOW_DAYS)
    return list(
        s.query(ResponseORM)
         .filter(ResponseORM.topic_id == topic_id)
         .filter(ResponseORM.query == query)
         .filter(ResponseORM.engine == engine)
         .filter(ResponseORM.created_at >= cutoff)
         .order_by(ResponseORM.created_at.desc())
         .limit(MAX_RESPONSES_IN_WINDOW)
         .all()
    )


def _responses_to_window(rs: list[ResponseORM]) -> list[dict[str, Any]]:
    out = []
    for r in rs:
        out.append({
            "response_id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "hit": bool(r.hit),
            "hit_excerpt": r.hit_excerpt,
            "answer": r.answer or "",
            "competitors": json.loads(r.competitors_json or "[]") if r.competitors_json else [],
            "citation_domains": json.loads(r.citation_domains_json or "[]") if r.citation_domains_json else [],
            "answer_format": r.answer_format,
        })
    return out


def get_or_generate_cell_insight(
    *, topic_id: int, query: str, engine: str, force: bool = False,
) -> dict[str, Any] | None:
    """读取/生成 cell insight. 返回 dict;若 topic 不存在返回 None."""
    with db_session() as s:
        t = s.get(TopicORM, topic_id)
        if t is None:
            return None
        target, _ = parse_target(t)
        responses = _gather_window_responses(s, topic_id, query, engine)
        evidence_ids = sorted([r.id for r in responses])
        # 窗口边界 — 取该 cell 最新一条 Response 的 created_at 作为 window_end
        window_end = responses[0].created_at if responses else datetime.utcnow()
        window_start = window_end - timedelta(days=WINDOW_DAYS)

        if not force:
            cached = (
                s.query(CellInsightORM)
                 .filter(CellInsightORM.topic_id == topic_id)
                 .filter(CellInsightORM.query == query)
                 .filter(CellInsightORM.engine == engine)
                 .filter(CellInsightORM.prompt_version == CELL_PROMPT_VERSION)
                 .order_by(CellInsightORM.generated_at.desc())
                 .first()
            )
            if cached:
                cached_ids = sorted(json.loads(cached.evidence_response_ids_json or "[]"))
                if cached_ids == evidence_ids:
                    return _row_to_dict(cached, responses)

        # 生成新一条
        window_payload = _responses_to_window(responses)

    result = generate_cell_insight(
        target=target, query=query, engine=engine,
        window_responses=window_payload,
    )

    with db_session() as s:
        row = CellInsightORM(
            topic_id=topic_id, query=query, engine=engine,
            window_start=window_start, window_end=window_end,
            verdict=result.get("verdict") or "no_signal",
            summary=result.get("summary") or "",
            competitors_top3_json=json.dumps(result.get("competitors_top3") or [], ensure_ascii=False),
            recommendations_json=json.dumps(result.get("recommendations") or [], ensure_ascii=False),
            evidence_response_ids_json=json.dumps(evidence_ids, ensure_ascii=False),
            llm_model=result.get("llm_model") or "stub",
            prompt_version=CELL_PROMPT_VERSION,
            generated_at=datetime.utcnow(),
        )
        s.add(row)
        s.flush()
        return _row_to_dict(row, responses)


def _row_to_dict(row: CellInsightORM, responses: list[ResponseORM]) -> dict[str, Any]:
    # citation_domains 聚合:整个 window 所有 Response 的 domain 并集 top 10
    all_domains: dict[str, int] = {}
    for r in responses:
        for d in json.loads(r.citation_domains_json or "[]") if r.citation_domains_json else []:
            all_domains[d] = all_domains.get(d, 0) + 1
    cd_top = [d for d, _ in sorted(all_domains.items(), key=lambda kv: -kv[1])[:10]]
    answer_formats = [r.answer_format for r in responses if r.answer_format]
    most_common_format = max(set(answer_formats), key=answer_formats.count) if answer_formats else None

    return {
        "id": row.id,
        "topic_id": row.topic_id,
        "query": row.query,
        "engine": row.engine,
        "window_start": row.window_start.isoformat() if row.window_start else None,
        "window_end": row.window_end.isoformat() if row.window_end else None,
        "verdict": row.verdict,
        "summary": row.summary or "",
        "competitors_top3": json.loads(row.competitors_top3_json or "[]"),
        "recommendations": json.loads(row.recommendations_json or "[]"),
        "answer_format": most_common_format,
        "citation_domains": cd_top,
        "evidence_response_ids": json.loads(row.evidence_response_ids_json or "[]"),
        "llm_model": row.llm_model or "",
        "prompt_version": row.prompt_version or "",
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "feedback": row.feedback,
    }


def update_feedback(insight_id: int, feedback: str) -> bool:
    """drawer 点 👍 / 👎 / wrong."""
    if feedback not in {"helpful", "not_helpful", "wrong"}:
        return False
    with db_session() as s:
        r = s.get(CellInsightORM, insight_id)
        if r is None:
            return False
        r.feedback = feedback
    return True
