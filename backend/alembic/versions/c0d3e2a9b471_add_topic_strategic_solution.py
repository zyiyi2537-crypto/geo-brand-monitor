"""v3.3 — GEO 品牌增长战略方案表

Revision ID: c0d3e2a9b471
Revises: a3d7c1f8e2b5
Create Date: 2026-05-21 10:00:00.000000

新表 ai_telemetry_topic_solutions:
  - 每个 topic 至多一条战略方案(unique topic_id)
  - admin 在工作台点"生成战略方案"时,后端跑 geo_checker 拿诊断 + 调 DeepSeek 写文案,
    结果落本表;前端轮询 status='ready'|'failed' 后渲染 + 导出 PDF
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c0d3e2a9b471'
down_revision: Union[str, None] = 'a3d7c1f8e2b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_telemetry_topic_solutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="idle"),
        sa.Column("website_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("diagnosis_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("narrative_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("keywords_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("brand_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("llm_model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("generated_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["topic_id"], ["ai_telemetry_topics.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("topic_id", name="uq_topic_solution"),
    )
    with op.batch_alter_table("ai_telemetry_topic_solutions", schema=None) as batch_op:
        batch_op.create_index("idx_topic_solution_topic", ["topic_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ai_telemetry_topic_solutions_id"), ["id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topic_solutions", schema=None) as batch_op:
        batch_op.drop_index("idx_topic_solution_topic")
        batch_op.drop_index(batch_op.f("ix_ai_telemetry_topic_solutions_id"))
    op.drop_table("ai_telemetry_topic_solutions")
