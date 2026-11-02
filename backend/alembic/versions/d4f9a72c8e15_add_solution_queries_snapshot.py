"""v3.3.1 — solution 表加 queries_snapshot_json

Revision ID: d4f9a72c8e15
Revises: c0d3e2a9b471
Create Date: 2026-05-24 10:00:00.000000

报告生成时把 topic.queries_json 里 selected=True 的监测 Query + clusters_json 簇标签
快照下来,落到 ai_telemetry_topic_solutions.queries_snapshot_json,前端报告页直接展示.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f9a72c8e15'
down_revision: Union[str, None] = 'c0d3e2a9b471'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topic_solutions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("queries_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topic_solutions", schema=None) as batch_op:
        batch_op.drop_column("queries_snapshot_json")
