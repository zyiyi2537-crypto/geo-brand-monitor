"""add users.is_admin

Revision ID: a8c5b3d1f0e9
Revises: 76b395a30508
Create Date: 2026-05-14 19:00:00.000000

Add `is_admin` boolean column to users table for the AEO 审核 menu.
Existing users default to is_admin=False; ops manually flips the platform
operator account to 1 after migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8c5b3d1f0e9'
down_revision: Union[str, None] = '76b395a30508'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("is_admin")
