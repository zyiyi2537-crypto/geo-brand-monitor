"""Phase D — 画像审核工作流 + 执行计划书 + 内容文档

Revision ID: d7e3a91c4f50
Revises: c4e98a712f60
Create Date: 2026-05-15 10:00:00.000000

新增:
- ai_telemetry_topics 加 profile_json / submission_status / submitted_at /
  approved_at / rejected_at / reviewer_id / topic_changelog_json / expansion_log_json
- 新表 ai_telemetry_topic_execution_plans(审核通过那一刻的快照 + 触发的 run_id)
- 新表 topic_generated_docs(内容文案稿 + 内容审核状态 + 发布目标)

向后兼容:
- 历史 topic 的 submission_status 写 "approved"(默认认为已上线)
- 历史 query 项不补 selected 字段;读端按 selected=True 兜底
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e3a91c4f50'
down_revision: Union[str, None] = 'c4e98a712f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) topics 表加列
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.add_column(sa.Column("profile_json", sa.Text(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("submission_status", sa.String(length=16), nullable=False, server_default="draft"))
        batch_op.add_column(sa.Column("submitted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("rejected_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("reviewer_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("topic_changelog_json", sa.Text(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("expansion_log_json", sa.Text(), nullable=False, server_default="[]"))

    # 2) 历史 topic 视为已上线(避免存量数据被新审核流程困住)
    op.execute("UPDATE ai_telemetry_topics SET submission_status = 'approved' WHERE submission_status = 'draft'")

    # 3) 执行计划书表
    op.create_table(
        "ai_telemetry_topic_execution_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("generated_by_reviewer_id", sa.Integer(), nullable=True),
        sa.Column("overview_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("topic_changelog_snapshot_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("expansion_log_snapshot_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("monitored_queries_snapshot_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="generating"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["topic_id"], ["ai_telemetry_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["ai_telemetry_runs.id"], ondelete="SET NULL"),
    )
    with op.batch_alter_table("ai_telemetry_topic_execution_plans", schema=None) as batch_op:
        batch_op.create_index("idx_tep_topic", ["topic_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ai_telemetry_topic_execution_plans_id"), ["id"], unique=False)

    # 4) 内容文档表
    op.create_table(
        "topic_generated_docs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("execution_plan_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("source_query_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("body_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("llm_model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("generation_error", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("selected_for_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("review_decision_at", sa.DateTime(), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("publish_targets_json", sa.Text(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(["topic_id"], ["ai_telemetry_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_plan_id"], ["ai_telemetry_topic_execution_plans.id"], ondelete="SET NULL"),
    )
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.create_index("idx_tgd_topic", ["topic_id"], unique=False)
        batch_op.create_index("idx_tgd_status", ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_topic_generated_docs_id"), ["id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.drop_index("idx_tgd_status")
        batch_op.drop_index("idx_tgd_topic")
        batch_op.drop_index(batch_op.f("ix_topic_generated_docs_id"))
    op.drop_table("topic_generated_docs")

    with op.batch_alter_table("ai_telemetry_topic_execution_plans", schema=None) as batch_op:
        batch_op.drop_index("idx_tep_topic")
        batch_op.drop_index(batch_op.f("ix_ai_telemetry_topic_execution_plans_id"))
    op.drop_table("ai_telemetry_topic_execution_plans")

    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.drop_column("expansion_log_json")
        batch_op.drop_column("topic_changelog_json")
        batch_op.drop_column("reviewer_id")
        batch_op.drop_column("rejected_at")
        batch_op.drop_column("approved_at")
        batch_op.drop_column("submitted_at")
        batch_op.drop_column("submission_status")
        batch_op.drop_column("profile_json")
