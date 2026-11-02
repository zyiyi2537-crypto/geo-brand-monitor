"""add clusters_json to ai_telemetry_topics

Revision ID: 4ffb8290f4b2
Revises: 43685ae506e6
Create Date: 2026-05-14 10:15:21.524091

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ffb8290f4b2'
down_revision: Union[str, None] = '43685ae506e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # picker 端嵌入 + K-Means 出的簇元数据 (list[{cluster_id, label, size}]),
    # 跑批结果按 cluster_id 分组用。
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "clusters_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_telemetry_topics", schema=None) as batch_op:
        batch_op.drop_column("clusters_json")
