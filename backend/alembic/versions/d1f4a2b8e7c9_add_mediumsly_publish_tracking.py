"""add topic_generated_docs.mediumsly_{post_id, url, pushed_at, last_error}

Revision ID: d1f4a2b8e7c9
Revises: c5f4a8b9e3d2
Create Date: 2026-05-29 17:00:00.000000

跟踪 doc 推到 Mediumsly 的状态。
  - mediumsly_post_id:  Mediumsly 那边 post 的 UUID(不透明字符串,不是 FK)
  - mediumsly_url:      绝对地址,前端展示链接
  - mediumsly_pushed_at: 最近一次成功推送的时间
  - mediumsly_last_error: 推送失败时记录的错误(成功时清空)

由 services/mediumsly_publisher.py 在 admin publish 时写入。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1f4a2b8e7c9'
down_revision: Union[str, None] = 'c5f4a8b9e3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mediumsly_post_id",    sa.String(length=64),  nullable=True))
        batch_op.add_column(sa.Column("mediumsly_url",        sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("mediumsly_pushed_at",  sa.DateTime(),         nullable=True))
        batch_op.add_column(sa.Column("mediumsly_last_error", sa.Text(),             nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.drop_column("mediumsly_last_error")
        batch_op.drop_column("mediumsly_pushed_at")
        batch_op.drop_column("mediumsly_url")
        batch_op.drop_column("mediumsly_post_id")
