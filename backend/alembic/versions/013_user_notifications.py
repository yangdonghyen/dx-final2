"""Add user_notifications for the app's bell (companion joined / plan edited).

New table only; no existing table or row changes.
"""

from alembic import op
import sqlalchemy as sa


revision = "013_user_notifications"
down_revision = "012_plan_item_user_note"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("notification_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("trip_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("body", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name="fk_user_notifications_user", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.trip_id"], name="fk_user_notifications_trip", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("notification_id"),
        mysql_charset="utf8mb4", mysql_engine="InnoDB",
    )
    op.create_index("ix_user_notifications_user_created", "user_notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_user_notifications_user_created", table_name="user_notifications")
    op.drop_table("user_notifications")
