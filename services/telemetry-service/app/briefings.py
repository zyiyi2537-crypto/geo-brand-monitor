"""v1.2 — Topic 周报生成 + 邮件投递.

scheduler 每周一 09:00 北京时间触发 generate_all_briefings_for_week();
邮件投递走 backend 已有的 sentiment notify_emails 通路(若可达),否则降级 log.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date, timedelta, timezone
from typing import Any

import httpx

from .storage import (
    db_session, TopicORM, ResponseORM, QueryHitORM, CellInsightORM, TopicBriefingORM,
    parse_target, parse_topic,
)
from .llm import generate_topic_briefing, BRIEFING_PROMPT_VERSION

log = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
EMAIL_DELIVER_ENABLED = os.environ.get("TELEMETRY_BRIEFING_EMAIL", "0") == "1"


def _last_week_range_utc() -> tuple[datetime, datetime, str]:
    """返回 (period_start_utc, period_end_utc, label).
    period = 上周一 00:00 ~ 上周日 23:59:59 北京时间,转 UTC.
    """
    tz_offset_h = int(os.environ.get("SCHEDULER_TIMEZONE_OFFSET", "8"))
    tz = timezone(timedelta(hours=tz_offset_h))
    now_local = datetime.now(tz)
    # 本周一(weekday Mon=0)
    this_monday = (now_local - timedelta(days=now_local.weekday())).date()
    last_monday = this_monday - timedelta(days=7)
    last_sunday = last_monday + timedelta(days=6)
    p_start = datetime.combine(last_monday, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    p_end = datetime.combine(last_sunday, datetime.max.time(), tzinfo=tz).astimezone(timezone.utc)
    iso_week = last_monday.isocalendar()
    label = f"{iso_week.year}-W{iso_week.week:02d}"
    return p_start.replace(tzinfo=None), p_end.replace(tzinfo=None), label


def _build_kpi_snapshot(topic: TopicORM, p_start: datetime, p_end: datetime) -> dict[str, Any]:
    """计算周报 KPI:命中率 / TTFM / 新命中数 / 流失数."""
    with db_session() as s:
        cells = list(s.query(QueryHitORM).filter(QueryHitORM.topic_id == topic.id).all())
        total_cells = len(cells)
        hit_cells = sum(1 for c in cells if (c.total_hits or 0) >= 1)
        hit_rate = round(hit_cells / total_cells * 100, 1) if total_cells > 0 else 0.0

        # TTFM:取所有 cell 中首次命中距 topic.created_at 的天数中位数
        diffs: list[int] = []
        for c in cells:
            if c.first_hit_at and topic.created_at:
                diffs.append(max(0, (c.first_hit_at - topic.created_at).days))
        diffs.sort()
        ttfm = diffs[len(diffs) // 2] if diffs else None

        new_hits = [
            {"query": c.query, "engine": c.engine,
             "first_hit_at": c.first_hit_at.isoformat() if c.first_hit_at else None}
            for c in cells
            if c.first_hit_at and p_start <= c.first_hit_at <= p_end
        ]
        # 流失 = 本周有跑批但 hit=0 且历史曾命中 (total_hits<total_runs 视为不稳定;严格"流失"
        # 需要历史命中率 → 本周 0,这里简化用 cell.total_hits 与窗口内 hit_count 对比)
        lost_hits: list[dict[str, Any]] = []
        for c in cells:
            if c.total_hits == 0:
                continue
            recent_rows = list(
                s.query(ResponseORM)
                 .filter(ResponseORM.topic_id == topic.id)
                 .filter(ResponseORM.query == c.query)
                 .filter(ResponseORM.engine == c.engine)
                 .filter(ResponseORM.created_at >= p_start)
                 .filter(ResponseORM.created_at <= p_end)
                 .all()
            )
            if recent_rows and not any(r.hit for r in recent_rows):
                lost_hits.append({"query": c.query, "engine": c.engine})

    return {
        "hit_rate": hit_rate,
        "ttfm_days": ttfm,
        "total_cells": total_cells,
        "hit_cells": hit_cells,
        "new_hits_count": len(new_hits),
        "lost_hits_count": len(lost_hits),
        "_new_hits": new_hits,
        "_lost_hits": lost_hits,
    }


def _gather_cell_insights(topic_id: int) -> list[dict[str, Any]]:
    """取该 topic 所有 cell 最新一条 insight(按 generated_at DESC,unique by cell)."""
    out = []
    seen: set[tuple[str, str]] = set()
    with db_session() as s:
        rows = (
            s.query(CellInsightORM)
             .filter(CellInsightORM.topic_id == topic_id)
             .order_by(CellInsightORM.generated_at.desc())
             .all()
        )
        for r in rows:
            key = (r.query, r.engine)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "query": r.query,
                "engine": r.engine,
                "verdict": r.verdict,
                "summary": r.summary,
                "recommendations": json.loads(r.recommendations_json or "[]")[:2],  # 精简
            })
    return out


def generate_briefing_for_topic(topic_id: int) -> dict[str, Any] | None:
    """对单个 topic 生成上一周的周报并入库.
    返回生成的 briefing dict;若该 period 已有 briefing 则返回旧的.
    """
    p_start, p_end, label = _last_week_range_utc()
    with db_session() as s:
        t = s.get(TopicORM, topic_id)
        if t is None:
            return None
        target, _ = parse_target(t)

        existing = (
            s.query(TopicBriefingORM)
             .filter(TopicBriefingORM.topic_id == topic_id)
             .filter(TopicBriefingORM.period_end == p_end)
             .filter(TopicBriefingORM.prompt_version == BRIEFING_PROMPT_VERSION)
             .one_or_none()
        )
        if existing is not None:
            return _briefing_to_dict(existing)

    kpi = _build_kpi_snapshot_safe(topic_id, p_start, p_end)
    new_hits = kpi.pop("_new_hits", [])
    lost_hits = kpi.pop("_lost_hits", [])
    insights = _gather_cell_insights(topic_id)

    result = generate_topic_briefing(
        target=target, period_label=label, kpi_snapshot=kpi,
        new_hits=new_hits, lost_hits=lost_hits, cell_insights=insights,
    )
    body_md = result.get("body_md") or ""
    top_actions = result.get("top_actions") or []
    llm_model = result.get("llm_model") or "stub"

    with db_session() as s:
        b = TopicBriefingORM(
            topic_id=topic_id,
            period_start=p_start, period_end=p_end,
            body_md=body_md,
            kpi_snapshot_json=json.dumps(kpi, ensure_ascii=False),
            top_actions_json=json.dumps(top_actions, ensure_ascii=False),
            llm_model=llm_model,
            prompt_version=BRIEFING_PROMPT_VERSION,
            generated_at=datetime.utcnow(),
        )
        s.add(b)
        s.flush()
        bid = b.id

    # 邮件投递(可选)
    if EMAIL_DELIVER_ENABLED:
        try:
            _deliver_email(topic_id, bid, body_md, label)
            with db_session() as s:
                b2 = s.get(TopicBriefingORM, bid)
                if b2 is not None:
                    b2.delivered_email_at = datetime.utcnow()
        except Exception as e:  # noqa: BLE001
            log.warning("briefing email deliver failed (topic %d): %s", topic_id, e)

    with db_session() as s:
        return _briefing_to_dict(s.get(TopicBriefingORM, bid))


def _build_kpi_snapshot_safe(topic_id: int, p_start: datetime, p_end: datetime) -> dict[str, Any]:
    """包 _build_kpi_snapshot 一层异常兜底."""
    try:
        with db_session() as s:
            t = s.get(TopicORM, topic_id)
            if t is None:
                return {}
            return _build_kpi_snapshot(t, p_start, p_end)
    except Exception as e:  # noqa: BLE001
        log.exception("kpi snapshot failed for topic %d: %s", topic_id, e)
        return {}


def _briefing_to_dict(b: TopicBriefingORM | None) -> dict[str, Any] | None:
    if b is None:
        return None
    return {
        "id": b.id,
        "topic_id": b.topic_id,
        "period_start": b.period_start.isoformat() if b.period_start else None,
        "period_end": b.period_end.isoformat() if b.period_end else None,
        "body_md": b.body_md or "",
        "kpi_snapshot": json.loads(b.kpi_snapshot_json or "{}"),
        "top_actions": json.loads(b.top_actions_json or "[]"),
        "delivered_email_at": b.delivered_email_at.isoformat() if b.delivered_email_at else None,
        "feedback_score": b.feedback_score,
        "llm_model": b.llm_model or "",
        "prompt_version": b.prompt_version or "",
        "generated_at": b.generated_at.isoformat() if b.generated_at else None,
    }


def _deliver_email(topic_id: int, briefing_id: int, body_md: str, label: str) -> None:
    """走 backend /internal/email 端点投递(若存在);否则只记日志.

    Backend 应实现 POST /api/internal/telemetry-briefing-email 接收 (topic_id, body_md, label),
    内部转给 Resend / SMTP. 此处只 fire,不阻断.
    """
    url = f"{BACKEND_URL}/api/internal/telemetry-briefing-email"
    payload = {"topic_id": topic_id, "briefing_id": briefing_id, "label": label, "body_md": body_md}
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        try:
            r = client.post(url, json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.info("briefing email endpoint not available (%s) — falling back to log", e)
            log.info("[BRIEFING %s] topic=%d:\n%s", label, topic_id, body_md[:500])


def generate_all_briefings_for_week() -> int:
    """周一 09:00 cron 调:对所有 enabled topic 生成周报. Returns 成功数."""
    n = 0
    with db_session() as s:
        topic_ids = [t.id for t in s.query(TopicORM).filter(TopicORM.enabled == True).all()]  # noqa: E712
    for tid in topic_ids:
        try:
            generate_briefing_for_topic(tid)
            n += 1
        except Exception as e:  # noqa: BLE001
            log.exception("briefing generation failed for topic %d: %s", tid, e)
    log.info("weekly briefings: %d / %d topics", n, len(topic_ids))
    return n
