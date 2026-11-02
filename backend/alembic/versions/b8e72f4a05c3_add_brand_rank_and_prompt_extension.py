"""add ai_telemetry_responses.brand_rank + ai_telemetry_topics.prompt_extension

Revision ID: b8e72f4a05c3
Revises: a1b2c3d4e5f6
Create Date: 2026-05-19 12:00:00.000000

brand_rank: AI 答复中 brand(含别名)第几个被提到,1-based。未命中 NULL。
            用来聚 Top1/Top3/Top5 占比(品牌增长页雷达)。

prompt_extension: admin 给单 topic 配的扩展提示词,跑批时拼到 prompt 模板末尾。
                  普通用户看不见,只 admin 工作台能编辑。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e72f4a05c3'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_telemetry_responses", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("brand_rank", sa.Integer(), nullable=True),
        )

    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("prompt_extension", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.drop_column("prompt_extension")

    with op.batch_alter_table("ai_telemetry_responses", schema=None) as batch_op:
        batch_op.drop_column("brand_rank")
