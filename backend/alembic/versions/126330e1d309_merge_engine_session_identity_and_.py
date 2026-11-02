"""merge engine session identity and platform rules

Revision ID: 126330e1d309
Revises: a3d8e5f27c19, f9c2d7e1a384
Create Date: 2026-06-12 08:24:57.782880

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '126330e1d309'
down_revision: Union[str, None] = ('a3d8e5f27c19', 'f9c2d7e1a384')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
