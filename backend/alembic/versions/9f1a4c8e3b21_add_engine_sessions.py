"""add engine_sessions

Revision ID: 9f1a4c8e3b21
Revises: c91d72e58a14
Create Date: 2026-05-18 13:00:00.000000

中央 session pool.每个 (engine, source_label) 是一份 Playwright storage_state
全量(cookies + localStorage),由 scripts/harvest_sessions.py 在用户机器上
登录后上传,browser-service 在 /search 调用前从这张表里 check-out 一条
"最少被用 + 没被 CAPTCHA"的 session 替换本地文件。

设计要点:
- captcha_count >= 3 自动 quarantine,防止一条挂掉的 session 被反复重试
- expires_at 默认 7 天,过期不再被 check-out
- storage_state 用 Text(SQLite 没有 JSONB,且我们存的是 ~1MB raw JSON,
  不做 in-DB query,Text 比 JSON 列省 schema 复杂度)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9f1a4c8e3b21'
down_revision: Union[str, None] = 'c91d72e58a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "engine_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("engine", sa.String(), nullable=False, index=True),
        sa.Column("source_label", sa.String(), nullable=True),
        sa.Column("storage_state", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("captcha_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_engine_sessions_pool",
        "engine_sessions",
        ["engine", "status", "captcha_count", "last_used_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_engine_sessions_pool", table_name="engine_sessions")
    op.drop_table("engine_sessions")
