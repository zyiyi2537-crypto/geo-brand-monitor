"""merge heads a7c3e9f12b04 + f4a1c7e9d580(消除双 alembic head)

空迁移,只把两条分叉链并到一起,不改任何表 / 不动两条原迁移文件。

Revision ID: b8e2f4a16c90
Revises: a7c3e9f12b04, f4a1c7e9d580
Create Date: 2026-06-09
"""
from typing import Sequence, Union

revision: str = "b8e2f4a16c90"
down_revision: Union[str, Sequence[str], None] = ("a7c3e9f12b04", "f4a1c7e9d580")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
