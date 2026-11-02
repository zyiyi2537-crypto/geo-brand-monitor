"""align legacy NOT NULL drift

Revision ID: 76b395a30508
Revises: 4ffb8290f4b2
Create Date: 2026-05-14 10:20:27.539593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '76b395a30508'
down_revision: Union[str, None] = '4ffb8290f4b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # memberships.slug — pre-alembic ADD COLUMN didn't set NOT NULL even
    # though every seeded tier supplies one. Tighten to NOT NULL.
    with op.batch_alter_table("memberships", schema=None) as batch_op:
        batch_op.alter_column(
            "slug",
            existing_type=sa.Text(),
            nullable=False,
        )

    # payment_sessions.stripe_session_id — was NOT NULL when only Stripe
    # existed; MoltsPay rows don't have one, so the ORM is already nullable.
    with op.batch_alter_table("payment_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "stripe_session_id",
            existing_type=sa.String(),
            nullable=True,
        )

    # users.name — registration no longer collects a name (email-only),
    # ORM has been nullable for a while.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "name",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "name",
            existing_type=sa.String(),
            nullable=False,
        )

    with op.batch_alter_table("payment_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "stripe_session_id",
            existing_type=sa.String(),
            nullable=False,
        )

    with op.batch_alter_table("memberships", schema=None) as batch_op:
        batch_op.alter_column(
            "slug",
            existing_type=sa.Text(),
            nullable=True,
        )
