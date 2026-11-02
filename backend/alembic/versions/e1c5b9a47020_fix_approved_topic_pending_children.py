"""fix approved topic with pending children

Revision ID: e1c5b9a47020
Revises: d7e3a91c4f50
Create Date: 2026-05-16 03:00:00.000000

历史 bug:`approve_topic` 只把 selected=True 的 query 翻到 approved,
seed_prompts 完全不动,unselected 候选 query 也保留 pending。结果就是
topic.submission_status='approved' 但里面的 seeds + 部分 queries 还卡在
pending,前端「外面已通过、里面待审」的状态裂开。

代码侧修复在 approve_topic 里改成把所有 pending 子项一起翻 approved。
这条 migration 把 DB 里已经处于错乱状态的旧数据一次性修平,
避免要求用户重新走一遍审批。

逻辑:对每个 submission_status='approved' 的 topic:
- seed_prompts: status='pending' → status='approved' + approved_at=topic.approved_at(没有就 utcnow)
- queries: status='pending' → status='approved' + approved_at=topic.approved_at
两个 JSON 列都是 TEXT,这里用纯 python 处理。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1c5b9a47020'
down_revision: Union[str, None] = 'd7e3a91c4f50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    fallback_iso = datetime.utcnow().isoformat()
    rows = conn.execute(sa.text(
        "SELECT id, submission_status, approved_at, "
        "seed_prompts_json, queries_json "
        "FROM ai_telemetry_topics WHERE submission_status = 'approved'"
    )).mappings().all()

    for r in rows:
        approved_at = r["approved_at"]
        if hasattr(approved_at, "isoformat"):
            approved_iso = approved_at.isoformat()
        elif isinstance(approved_at, str) and approved_at:
            approved_iso = approved_at
        else:
            approved_iso = fallback_iso

        new_seed_raw = _promote_pending(r["seed_prompts_json"], approved_iso)
        new_q_raw = _promote_pending(r["queries_json"], approved_iso)

        if new_seed_raw is None and new_q_raw is None:
            continue

        params = {"id": r["id"]}
        sets = []
        if new_seed_raw is not None:
            sets.append("seed_prompts_json = :seeds")
            params["seeds"] = new_seed_raw
        if new_q_raw is not None:
            sets.append("queries_json = :queries")
            params["queries"] = new_q_raw
        conn.execute(
            sa.text(f"UPDATE ai_telemetry_topics SET {', '.join(sets)} WHERE id = :id"),
            params,
        )


def downgrade() -> None:
    # 不可逆 — 旧数据原本就是 bug 态,没有有意义的回滚
    pass


def _promote_pending(raw: str | None, approved_iso: str) -> str | None:
    """如果 raw 里有 status='pending' 的项,翻 approved 并返回新 JSON;
    否则返回 None(免得无谓 UPDATE)。"""
    if not raw:
        return None
    try:
        items = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(items, list):
        return None
    touched = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "pending" and item.get("text"):
            item["status"] = "approved"
            item.setdefault("approved_at", approved_iso)
            touched = True
    if not touched:
        return None
    return json.dumps(items, ensure_ascii=False)
