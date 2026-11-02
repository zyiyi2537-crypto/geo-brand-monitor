"""add ai_telemetry_topics.auto_publish_enabled

Revision ID: a7c3e9f12b04
Revises: d4a7e2f1c930
Create Date: 2026-06-09 11:00:00.000000

按 publish_date 自动发布开关.默认开(server_default=true),admin 可关闭后续发文.
content_scheduler.publish_tick 每天 11:00 扫这个开关开着的已审批 topic,把到期且未发布
的稿真发 Mediumsly + 标记其他平台.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c3e9f12b04'
down_revision: Union[str, None] = 'd4a7e2f1c930'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("auto_publish_enabled", sa.Boolean(),
                      nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.drop_column("auto_publish_enabled")
