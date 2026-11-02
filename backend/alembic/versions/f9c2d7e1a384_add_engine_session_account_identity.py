"""add engine_sessions.account_id / account_handle

Revision ID: f9c2d7e1a384
Revises: b8e2f4a16c90
Create Date: 2026-06-11 12:00:00.000000

账号身份识别:upload 时从 storage_state 按引擎提取稳定的用户标识
(豆包 uid_tt / 元宝 hy_user / JWT sub 等),哈希后存 account_id,
upsert 改按 (engine, account_id) 优先 —— 不再依赖人填的 source_label。
account_handle 是采集端抓的昵称/掩码手机号,纯展示用。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9c2d7e1a384'
down_revision: Union[str, None] = 'b8e2f4a16c90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("engine_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("account_handle", sa.String(), nullable=True))
    op.create_index("idx_sessions_account", "engine_sessions", ["engine", "account_id"])


def downgrade() -> None:
    op.drop_index("idx_sessions_account", table_name="engine_sessions")
    with op.batch_alter_table("engine_sessions", schema=None) as batch_op:
        batch_op.drop_column("account_handle")
        batch_op.drop_column("account_id")
