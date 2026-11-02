"""add topic_generated_docs.{creation_direction, copywriting_type}

Revision ID: e8f2c5d4a370
Revises: d1f4a2b8e7c9
Create Date: 2026-05-28 19:00:00.000000

2026-05-28 — 4 维场景扩展第二波: 创作方向 × 文案类型多变体生成.

content_generator 现在按 (creation_direction, copywriting_type) combo 出多篇稿,
同一 query 多份稿件用这俩字段区分.两列都可空(legacy doc 不需要 backfill).

creation_direction 候选(profile.creation_directions 多选自此):
  industry_insight / case_story / how_to_guide / trend_forecast /
  product_review / customer_story / faq

copywriting_type 候选(profile.copywriting_types 多选自此):
  long_form / medium_post / short_social / video_script_long /
  video_script_short / faq_list
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f2c5d4a370"
down_revision: Union[str, None] = "d1f4a2b8e7c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("creation_direction", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("copywriting_type", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("topic_generated_docs", schema=None) as batch_op:
        batch_op.drop_column("creation_direction")
        batch_op.drop_column("copywriting_type")
