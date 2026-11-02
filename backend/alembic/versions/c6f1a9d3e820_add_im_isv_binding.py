"""add IM ISV binding tables (user_bindings / bind_codes / isv_state)

新建表,不动现有数据。见 agent integration API。

Revision ID: c6f1a9d3e820
Revises: b5d2e8c1a740
Create Date: 2026-06-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6f1a9d3e820"
down_revision: Union[str, None] = "b5d2e8c1a740"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_im_user_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("tenant_key", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("open_id", sa.String(length=128), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_im_bind_lookup", "agent_im_user_bindings", ["platform", "tenant_key", "open_id"], unique=True)
    op.create_index("ix_agent_im_bind_account", "agent_im_user_bindings", ["account_id"])

    op.create_table(
        "agent_im_bind_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_im_bind_codes_code", "agent_im_bind_codes", ["code"], unique=True)

    op.create_table(
        "agent_isv_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("app_ticket", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_isv_state_app", "agent_isv_state", ["app_id"], unique=True)


def downgrade() -> None:
    op.drop_table("agent_isv_state")
    op.drop_index("ix_agent_im_bind_codes_code", table_name="agent_im_bind_codes")
    op.drop_table("agent_im_bind_codes")
    op.drop_index("ix_agent_im_bind_account", table_name="agent_im_user_bindings")
    op.drop_index("ix_agent_im_bind_lookup", table_name="agent_im_user_bindings")
    op.drop_table("agent_im_user_bindings")
