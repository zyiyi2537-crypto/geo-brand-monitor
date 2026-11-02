"""add usage_ledger (metering/billing P2)

Revision ID: f4a1c7e9d580
Revises: e2c4f8a1b360
Create Date: 2026-06-09 14:00:00.000000

计量计费账本。每个外部 job 终态时由调度中心 _result_job 写一行:
成功 → billable=True + cost(按引擎单价)+ 扣租户 credit_balance;失败 → 不计费。
对账 / 用量统计都从这张表查。Stripe 充值是外部依赖,P2 只做 credits 余额扣减。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4a1c7e9d580'
down_revision: Union[str, None] = 'e2c4f8a1b360'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cost", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("idx_usage_ledger_tenant", "usage_ledger", ["tenant_id"])
    op.create_index("idx_usage_ledger_job", "usage_ledger", ["job_id"])

    # credit_balance 本应在 e2c4f8a1b360 建表时就有,但那条已落库无法重跑,
    # 故在此 add_column 补上 —— 现有库经本迁移补列,全新库同样在此补,schema 收敛一致。
    op.add_column("api_tenants",
                  sa.Column("credit_balance", sa.Integer(), nullable=False, server_default="100"))


def downgrade() -> None:
    op.drop_column("api_tenants", "credit_balance")
    op.drop_index("idx_usage_ledger_job", table_name="usage_ledger")
    op.drop_index("idx_usage_ledger_tenant", table_name="usage_ledger")
    op.drop_table("usage_ledger")
