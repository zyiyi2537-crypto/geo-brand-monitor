"""add agent_conversations (账号级多轮对话记忆)

加性新表,不改现有表。

Revision ID: d8b2e1c4f0a6
Revises: c7a1f0d2b9e4
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8b2e1c4f0a6"
down_revision: Union[str, None] = "c7a1f0d2b9e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("messages_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_conversations_account_id", "agent_conversations", ["account_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_agent_conversations_account_id", table_name="agent_conversations")
    op.drop_table("agent_conversations")
