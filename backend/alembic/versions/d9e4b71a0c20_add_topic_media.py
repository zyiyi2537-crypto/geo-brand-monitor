"""Add topic_media table — 用户为某 topic 上传的图片 / 视频素材

Revision ID: d9e4b71a0c20
Revises: c91d72e58a14
Create Date: 2026-05-18 10:00:00.000000

资料上传弹窗:文本走 LLM 抽取直接回填,媒体(图片/视频)落本表 + 文件系统,
后续生稿 / 发文时引用。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e4b71a0c20'
down_revision: Union[str, None] = '9f1a4c8e3b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "topic_media",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("topic_id", sa.Integer(),
                  sa.ForeignKey("ai_telemetry_topics.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="image"),
        sa.Column("mime", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_topic_media_topic", "topic_media", ["topic_id"])
    op.create_index("idx_topic_media_user", "topic_media", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_topic_media_user", table_name="topic_media")
    op.drop_index("idx_topic_media_topic", table_name="topic_media")
    op.drop_table("topic_media")
