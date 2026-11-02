"""add ai_telemetry_topics.seed_prompts_json + backfill queries[].status=approved

Revision ID: b3f72e408cd1
Revises: a8c5b3d1f0e9
Create Date: 2026-05-14 19:30:00.000000

Phase C — 审核固化机制:
- 新增 seed_prompts_json 列(JSON list,默认空)
- queries_json 项目内嵌 status 字段;legacy 记录 backfill status="approved"
  保证现有 topic 不被新 PUT 校验逻辑误判为"试图改 approved 项"
"""
import json
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f72e408cd1'
down_revision: Union[str, None] = 'a8c5b3d1f0e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 加列
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("seed_prompts_json", sa.Text(), nullable=False, server_default="[]"),
        )

    # 2) backfill 历史 queries_json:str → {text, status: approved};
    #    dict 没 status 字段的补 status=approved + approved_at
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, queries_json FROM ai_telemetry_topics")).fetchall()
    now_iso = datetime.utcnow().isoformat()
    for row in rows:
        topic_id = row[0]
        raw = row[1] or "[]"
        try:
            items = json.loads(raw)
        except Exception:
            continue
        if not isinstance(items, list):
            continue
        changed = False
        new_items = []
        for q in items:
            if isinstance(q, str):
                new_items.append({
                    "text": q,
                    "status": "approved",
                    "approved_at": now_iso,
                })
                changed = True
            elif isinstance(q, dict):
                if "status" not in q:
                    q = dict(q)
                    q["status"] = "approved"
                    q.setdefault("approved_at", now_iso)
                    changed = True
                new_items.append(q)
            else:
                new_items.append(q)
        if changed:
            conn.execute(
                sa.text("UPDATE ai_telemetry_topics SET queries_json = :qj WHERE id = :id"),
                {"qj": json.dumps(new_items, ensure_ascii=False), "id": topic_id},
            )


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.drop_column("seed_prompts_json")
    # queries_json 里加的 status 字段不删 — 无害且可重复 upgrade
