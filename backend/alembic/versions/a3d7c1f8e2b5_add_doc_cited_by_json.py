"""add topic_generated_docs.cited_by_json

Revision ID: a3d7c1f8e2b5
Revises: b8e72f4a05c3
Create Date: 2026-05-19 20:00:00.000000

URL 级 ROI 命中:把 AI 答复 citations_json 里出现的 URL 跟 doc 的
publish_targets[].url 取交集,落到 doc.cited_by_json。
格式:{"deepseek": [response_id, ...], "doubao": [...], ...}
空对象 `{}` 即"还没被任何引擎引过"。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3d7c1f8e2b5'
down_revision: Union[str, None] = 'b8e72f4a05c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("cited_by_json", sa.Text(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.drop_column("cited_by_json")
