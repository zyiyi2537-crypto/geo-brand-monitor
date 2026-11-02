"""add sentiment_accounts.weixin_album_urls_json + newsnow_sources_json

Revision ID: a8c5d2f1e0b3
Revises: f2d8c3a91e44
Create Date: 2026-05-17 00:00:00.000000

舆情账号加两个可选数据源配置:
- weixin_album_urls_json: list[str] — 微信公众号合集 URL,周级别盯防 KOL/竞品官号
- newsnow_sources_json:  list[str] — newsnow source id 列表,如 ['weibo','zhihu','v2ex']
                                       本地按 keywords/aliases 过滤标题入库

两个字段都默认 '[]',现存账号自动 = 关闭状态,不影响行为。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8c5d2f1e0b3'
down_revision: Union[str, None] = 'f2d8c3a91e44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sentiment_accounts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("weixin_album_urls_json", sa.Text(),
                      nullable=False, server_default="[]"),
        )
        batch_op.add_column(
            sa.Column("newsnow_sources_json", sa.Text(),
                      nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    with op.batch_alter_table("sentiment_accounts", schema=None) as batch_op:
        batch_op.drop_column("newsnow_sources_json")
        batch_op.drop_column("weixin_album_urls_json")
