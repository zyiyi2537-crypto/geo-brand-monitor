"""add api_tenants and api_keys (public gateway P1)

Revision ID: e2c4f8a1b360
Revises: d7b3e9f1a240
Create Date: 2026-06-09 13:00:00.000000

对外多租户网关(/v1)的两张表:

- api_tenants:租户。一套配额(每引擎日配额 + 默认)+ 引擎白名单 + 计费档(tier,
  决定外部 job 的优先级)。
- api_keys:租户的 API Key,库里只存 sha256(key_hash),明文仅创建时返回一次。

用量来源直接用 browser_jobs.tenant_id 当日计数(P1),独立 usage_ledger 计费账本是 P2。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2c4f8a1b360'
down_revision: Union[str, None] = 'd7b3e9f1a240'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("tier", sa.String(), nullable=False, server_default="free"),
        sa.Column("engines_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("daily_quota_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("daily_quota_default", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    # 注意:credit_balance 不在这里加 —— 本迁移已落库,改它不会被 alembic 重跑。
    # 该列由后续 f4a1c7e9d580 用 add_column 补,保证现有库与全新库 schema 一致。
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("key_prefix", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["api_tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_api_keys_tenant", "api_keys", ["tenant_id"])
    op.create_index("uq_api_keys_hash", "api_keys", ["key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_api_keys_hash", table_name="api_keys")
    op.drop_index("idx_api_keys_tenant", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("api_tenants")
