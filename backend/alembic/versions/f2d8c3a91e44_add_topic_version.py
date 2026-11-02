"""add ai_telemetry_topics.version

Revision ID: f2d8c3a91e44
Revises: e1c5b9a47020
Create Date: 2026-05-16 21:00:00.000000

Topic 修订号 — 每次 _append_changelog 自增。新建 topic 时 1,之后每次画像 /
种子 / queries / 审核状态机改动都 +1。前端用来在卡片角显示 "v3" 之类。

老数据回填策略:把现有 topic 的 version 设成 `len(topic_changelog_json) + 1`,
跟代码侧"version=N 对应 changelog 第 N-1 条之后的状态"语义对齐。changelog
为空(或无效)的算 1。
"""
from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2d8c3a91e44'
down_revision: Union[str, None] = 'e1c5b9a47020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )

    # 回填:历史 changelog 条数 + 1
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, topic_changelog_json FROM ai_telemetry_topics"
    )).mappings().all()
    for r in rows:
        try:
            arr = json.loads(r["topic_changelog_json"] or "[]")
            count = len(arr) if isinstance(arr, list) else 0
        except Exception:  # noqa: BLE001
            count = 0
        new_version = max(1, count + 1)
        if new_version != 1:
            conn.execute(
                sa.text("UPDATE ai_telemetry_topics SET version = :v WHERE id = :id"),
                {"v": new_version, "id": r["id"]},
            )


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.drop_column("version")
