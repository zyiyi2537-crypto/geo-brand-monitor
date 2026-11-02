"""Phase D.1 — 内容来源 source 字段 + topic AI 自动生成排程

Revision ID: c91d72e58a14
Revises: a8c5d2f1e0b3
Create Date: 2026-05-17 13:00:00.000000

新增:
- topic_generated_docs.source ("ai" / "user"),老数据兼容 "ai"
- ai_telemetry_topics.auto_generate_enabled / auto_generate_time /
  auto_generate_count / auto_generate_last_run_at
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c91d72e58a14'
down_revision: Union[str, None] = 'a8c5d2f1e0b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(length=8),
                                      nullable=False, server_default="ai"))
        batch_op.create_index("idx_tgd_source", ["source"], unique=False)

    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.add_column(sa.Column("auto_generate_enabled", sa.Boolean(),
                                      nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("auto_generate_time", sa.String(length=8),
                                      nullable=False, server_default="09:00"))
        batch_op.add_column(sa.Column("auto_generate_count", sa.Integer(),
                                      nullable=False, server_default="3"))
        batch_op.add_column(sa.Column("auto_generate_last_run_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.drop_column("auto_generate_last_run_at")
        batch_op.drop_column("auto_generate_count")
        batch_op.drop_column("auto_generate_time")
        batch_op.drop_column("auto_generate_enabled")

    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.drop_index("idx_tgd_source")
        batch_op.drop_column("source")
