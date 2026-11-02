"""users.name = email 的历史脏数据回填成 NULL

Revision ID: e7a14b3f9c2d
Revises: d4f9a72c8e15
Create Date: 2026-05-25 12:00:00.000000

历史上 user_service.create_user 在 name 为空时 fallback 成 email,导致
admin 画像列表(/workbench/accounts)的"名称"列里很多客户显示成邮箱.
fallback 已去掉,这里把存量脏数据 NULL 掉,这样前端 `a.name || '—'`
就能正常显示占位符.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e7a14b3f9c2d'
down_revision: Union[str, None] = 'd4f9a72c8e15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE users SET name = NULL WHERE name = email")


def downgrade() -> None:
    # 不可逆 — 我们无法分辨"原本就 = email"和"fallback 写进去的".
    # downgrade 是 no-op,保持业务字段干净优先于严格可逆.
    pass
