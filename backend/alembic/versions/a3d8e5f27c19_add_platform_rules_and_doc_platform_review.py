"""add platform_rules table + doc platform review backfill columns

2026-06-12 — 平台审核规则库(生成文章时按平台注入审核红线)+
topic_generated_docs 平台审核结果回填字段(rejected 原因供「从拒稿学习」提炼规则)。

注意:down_revision 直接挂在 b8e2f4a16c90(已提交的 head)上,不依赖
本地未跟踪的 engine_session WIP 迁移;两边都是纯增量,出现双 head 时
merge 即可。

Revision ID: a3d8e5f27c19
Revises: b8e2f4a16c90
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "a3d8e5f27c19"
down_revision = "b8e2f4a16c90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_rules",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("rules_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("pending_rules_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("learned_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
    )
    op.create_index("idx_platform_rules_platform", "platform_rules",
                    ["platform"], unique=True)
    op.add_column("topic_generated_docs",
                  sa.Column("platform_review_status", sa.String(length=16), nullable=True))
    op.add_column("topic_generated_docs",
                  sa.Column("platform_reject_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("topic_generated_docs", "platform_reject_reason")
    op.drop_column("topic_generated_docs", "platform_review_status")
    op.drop_index("idx_platform_rules_platform", table_name="platform_rules")
    op.drop_table("platform_rules")
