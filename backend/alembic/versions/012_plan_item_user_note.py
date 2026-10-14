"""Add plan_items.user_note: the traveler's own description of a stop.

Additive and nullable; existing rows and AI reasons are untouched.
"""

from alembic import op
import sqlalchemy as sa


revision = "012_plan_item_user_note"
down_revision = "011_trip_transport_mode_walk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan_items", sa.Column("user_note", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("plan_items", "user_note")
