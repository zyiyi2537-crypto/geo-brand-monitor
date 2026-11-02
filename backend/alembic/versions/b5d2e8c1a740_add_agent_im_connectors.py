"""add agent_im_connectors (IM 自建应用接入器)

新建表,不动现有数据 —— 低风险。见 agent integration API。

Revision ID: b5d2e8c1a740
Revises: a1f4c7e9b830
Create Date: 2026-06-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5d2e8c1a740"
down_revision: Union[str, None] = "a1f4c7e9b830"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_im_connectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("app_secret", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("verify_token", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("aes_key", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_im_account", "agent_im_connectors", ["account_id"])
    op.create_index("ix_agent_im_app", "agent_im_connectors", ["platform", "app_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_im_app", table_name="agent_im_connectors")
    op.drop_index("ix_agent_im_account", table_name="agent_im_connectors")
    op.drop_table("agent_im_connectors")
