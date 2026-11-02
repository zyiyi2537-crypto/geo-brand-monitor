"""命中判定 + QueryHit 矩阵维护 — v1 引用追踪核心.

每条 Response 落库后调 update_query_hit_after_response():
  - 若 (topic_id, query, engine) cell 不存在 → 创建(默认 pending → done)
  - total_runs +=1, last_checked_at = now
  - 若 hit:total_hits+=1,first_hit_at/first_hit_response_id 为空则填
  - status 重算(pending/running/done)
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable
from sqlalchemy.orm import Session

from .storage import QueryHitORM, ResponseORM, TopicORM, parse_topic, query_created_at


def detect_hit(answer: str, target: str, aliases: Iterable[str]) -> tuple[bool, str | None]:
    """字符串匹配 — lowercase,组间 OR,组内 AND.

    每个 target / alias 条目用 `&` 分隔成多个子串,**组内必须全部出现**才算
    该条命中(AND);任意一条命中即返回 True(OR)。无 `&` 的条目就是单子串.

    示例 aliases=["程晓峰", "竞天程晓峰", "竞天公诚 & 程晓峰"]:
      - answer 含 "程晓峰" → 第 1 条命中
      - answer 仅含 "竞天公诚" → 不算(第 3 条要求同时含"程晓峰")
      - answer 同时含 "竞天公诚" + "程晓峰" → 第 1 条命中(也满足第 3 条)

    Returns (hit, excerpt). excerpt = 首条命中的首个子串位置前后各 100 字符.
    """
    if not answer:
        return False, None
    raw: list[str] = []
    if target:
        raw.append(target)
    raw.extend(aliases or [])
    # 每条 → AND-组(list[str]),去掉空段
    groups: list[list[str]] = []
    for entry in raw:
        if not entry:
            continue
        parts = [p.strip().lower() for p in entry.split("&") if p.strip()]
        if parts:
            groups.append(parts)
    if not groups:
        return False, None

    hay = answer.lower()
    for grp in groups:
        if not all(sub in hay for sub in grp):
            continue
        # excerpt:用组内第一个子串的首次出现位置
        first = grp[0]
        i = hay.find(first)
        start = max(0, i - 100)
        end = min(len(answer), i + len(first) + 100)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(answer) else ""
        return True, f"{prefix}{answer[start:end]}{suffix}"
    return False, None


def _get_or_create_cell(s: Session, topic_id: int, query: str, engine: str) -> QueryHitORM:
    cell = (
        s.query(QueryHitORM)
         .filter(QueryHitORM.topic_id == topic_id)
         .filter(QueryHitORM.query == query)
         .filter(QueryHitORM.engine == engine)
         .one_or_none()
    )
    if cell is None:
        cell = QueryHitORM(
            topic_id=topic_id, query=query, engine=engine,
            status="pending", total_runs=0, total_hits=0,
        )
        s.add(cell)
        s.flush()
    return cell


def update_query_hit_after_response(
    s: Session, *, response: ResponseORM, topic: TopicORM,
) -> None:
    """单条 response 落库后,维护对应的 QueryHit cell."""
    cell = _get_or_create_cell(s, response.topic_id, response.query, response.engine)
    cell.total_runs = (cell.total_runs or 0) + 1
    cell.last_checked_at = datetime.utcnow()
    if response.hit:
        cell.total_hits = (cell.total_hits or 0) + 1
        if cell.first_hit_at is None:
            cell.first_hit_at = response.created_at or datetime.utcnow()
            cell.first_hit_response_id = response.id
    # 跑过至少一次 → done(无论 hit 与否)
    cell.status = "done"


def initialize_pending_cells(s: Session, topic: TopicORM) -> None:
    """创建/更新 Topic 的所有 (query × engine) cell 为 pending(若不存在).

    新建 Topic 或加新 query 时调,保证矩阵满格,UI 不出现"未知 cell".
    """
    queries, engines = parse_topic(topic)
    for q in queries:
        for e in engines:
            _ = _get_or_create_cell(s, topic.id, q, e)


def mark_cells_running(s: Session, topic: TopicORM) -> None:
    """跑批开始时,把该 topic 所有 cell 置 running(对于历史从没跑过的 pending → running)."""
    for cell in s.query(QueryHitORM).filter(QueryHitORM.topic_id == topic.id).all():
        if cell.total_runs == 0:
            cell.status = "running"


def backfill_query_hits(s: Session, topic: TopicORM) -> int:
    """根据现有 Response 历史,重算该 topic 的 QueryHit 行(用于迁移 / 修复).

    Returns: 处理的 response 行数.
    """
    initialize_pending_cells(s, topic)
    cells_by_key: dict[tuple[str, str], QueryHitORM] = {}
    for cell in s.query(QueryHitORM).filter(QueryHitORM.topic_id == topic.id).all():
        cells_by_key[(cell.query, cell.engine)] = cell
        cell.total_runs = 0
        cell.total_hits = 0
        cell.first_hit_at = None
        cell.first_hit_response_id = None
        cell.last_checked_at = None
        cell.status = "pending"

    rows = (
        s.query(ResponseORM)
         .filter(ResponseORM.topic_id == topic.id)
         .order_by(ResponseORM.created_at.asc(), ResponseORM.id.asc())
         .all()
    )
    target = (topic.target or topic.name or "").strip()
    aliases = []
    try:
        import json as _json
        aliases = _json.loads(topic.target_aliases_json or "[]")
    except Exception:  # noqa: BLE001
        aliases = []
    # 新 query 不回填 — 跳过 created_at < query_created_at 的 Response
    q_created = {q: query_created_at(topic, q) for q, _ in {(r.query, r.engine) for r in rows}}

    for r in rows:
        if r.error:
            continue
        q_ts = q_created.get(r.query) or topic.created_at
        if r.created_at and q_ts and r.created_at < q_ts:
            continue
        cell = cells_by_key.get((r.query, r.engine))
        if cell is None:
            # 该 query/engine 已从配置移除,跳过
            continue
        cell.total_runs += 1
        cell.last_checked_at = r.created_at or cell.last_checked_at
        cell.status = "done"
        # hit 字段在 ALTER 之后才有,老 response 用 detect_hit 现算
        is_hit = bool(r.hit) if r.hit is not None else False
        if not is_hit and (target or aliases):
            is_hit, excerpt = detect_hit(r.answer or "", target, aliases)
            if is_hit:
                r.hit = True
                r.hit_excerpt = excerpt
        # mention_position 兜底:hit 但没 position 的,用 excerpt 在 answer 的位置粗判
        if is_hit and not r.mention_position:
            r.mention_position = _position_from_excerpt(r.answer, r.hit_excerpt)
        if is_hit or r.hit:
            cell.total_hits += 1
            if cell.first_hit_at is None:
                cell.first_hit_at = r.created_at
                cell.first_hit_response_id = r.id
    return len(rows)


def _position_from_excerpt(answer: str | None, hit_excerpt: str | None) -> str | None:
    """与 runner._fallback_position 等价 — 用 excerpt 在 answer 的字符位置算 lead/body/tail."""
    if not answer or not hit_excerpt:
        return None
    needle = hit_excerpt.strip("…").strip()
    if not needle:
        return None
    i = answer.find(needle[:20]) if len(needle) >= 20 else answer.find(needle)
    if i < 0:
        return None
    pct = i / max(1, len(answer))
    if pct < 0.30:
        return "lead"
    if pct > 0.70:
        return "tail"
    return "body"
