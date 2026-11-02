"""add agent_materials.embedding_json (向量语义检索)

加性加列(nullable),不改现有数据 —— 低风险。

Revision ID: e3c9a7b1d520
Revises: d8b2e1c4f0a6
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3c9a7b1d520"
down_revision: Union[str, None] = "d8b2e1c4f0a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_materials", sa.Column("embedding_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_materials", "embedding_json")
