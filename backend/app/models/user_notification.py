"""In-app notifications shown in the app's bell (알림함).

Written by the server when something happens to a shared trip: an invited
companion joined, or someone else edited the itinerary.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (
        Index("ix_user_notifications_user_created", "user_id", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )

    notification_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", name="fk_user_notifications_user", ondelete="CASCADE"), nullable=False
    )
    trip_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("trips.trip_id", name="fk_user_notifications_trip", ondelete="CASCADE"), nullable=True
    )
    # MEMBER_JOINED | PLAN_EDITED
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
