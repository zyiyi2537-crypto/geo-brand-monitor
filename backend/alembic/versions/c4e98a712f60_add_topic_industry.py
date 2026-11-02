"""add ai_telemetry_topics.industry

Revision ID: c4e98a712f60
Revises: b3f72e408cd1
Create Date: 2026-05-14 22:00:00.000000

新增 industry 列(行业 / 业务定位).之前前端 step1 已经收集这个字段,
但 payload 没下传 → 后端只在 suggest-queries 临时用一次后就丢了.
此 migration 把 industry 持久化到 topic 上.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e98a712f60'
down_revision: Union[str, None] = 'b3f72e408cd1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("industry", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.drop_column("industry")
