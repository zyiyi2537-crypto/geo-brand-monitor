"""add engine_sessions.daily_cap / exit_ip / exit_ip_at

Worker 管理(2026-06):
  - daily_cap   单账号日上限覆盖(None=用 env 默认,0=不限),可在管理页逐账号调
  - exit_ip     该账号实际出口 IP(check-in 时由 worker 按 egress 代理解析回报)
  - exit_ip_at  出口 IP 最近一次解析时间

Revision ID: b1e4f7c20a93
Revises: d4f7a92b5e61
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1e4f7c20a93"
down_revision: Union[str, None] = "d4f7a92b5e61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("engine_sessions") as batch_op:
        batch_op.add_column(sa.Column("daily_cap", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("exit_ip", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("exit_ip_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("engine_sessions") as batch_op:
        batch_op.drop_column("exit_ip_at")
        batch_op.drop_column("exit_ip")
        batch_op.drop_column("daily_cap")
