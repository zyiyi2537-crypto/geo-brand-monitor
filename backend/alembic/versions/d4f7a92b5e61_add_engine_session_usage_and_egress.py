"""add engine_sessions.used_today / used_date / egress

模型(EngineSessionORM)在加 account_handle 的同一波改动里引入了
used_today / used_date(每日 check-out 配额记账)和 egress(每账号出口
标记:None=按引擎默认 / 'proxy' / 'host'),但 f9c2d7e1a384 只建了
account_id / account_handle,这三列漏建,任何 SELECT 都报 UndefinedColumn。

Revision ID: d4f7a92b5e61
Revises: 126330e1d309
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f7a92b5e61"
down_revision: Union[str, None] = "126330e1d309"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("engine_sessions") as batch_op:
        batch_op.add_column(sa.Column("used_today", sa.Integer(), nullable=False,
                                      server_default="0"))
        batch_op.add_column(sa.Column("used_date", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("egress", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("engine_sessions") as batch_op:
        batch_op.drop_column("egress")
        batch_op.drop_column("used_date")
        batch_op.drop_column("used_today")
