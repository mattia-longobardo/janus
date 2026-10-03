"""guests: access value and expiry columns

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres cannot use a new enum value in the transaction that adds it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE access ADD VALUE IF NOT EXISTS 'guest'")
    op.add_column("devices", sa.Column("guest_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("guest_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "guest_expires_at")
    op.drop_column("devices", "guest_since")
    op.execute("UPDATE devices SET access = 'pending' WHERE access = 'guest'")
    # The 'guest' enum value stays: Postgres cannot drop a value from an enum type.
