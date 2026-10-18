"""Server-side notifications for the app's bell (알림함).

Kept deliberately small: who joined a shared trip, and who changed its
itinerary.  Creating a notification never breaks the action that caused it.
"""

import logging
from datetime import datetime

from sqlalchemy import select, update

from app.models.user_notification import UserNotification
from app.repositories.trip_repository import TripCompanionRepository, TripRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger("uvicorn.error")

LIST_LIMIT = 50


def trip_label(trip) -> str:
    title = (getattr(trip, "title", None) or "").strip()
    if title:
        return title
    destination = (getattr(trip, "destination", None) or "").strip()
    return f"{destination} 여행" if destination else "여행"


def person_label(user) -> str:
    name = (getattr(user, "nickname", None) or "").strip()
    return f"{name}님" if name else "동행자"


class NotificationService:
    def __init__(self, session):
        self.session = session

    # -- writing ---------------------------------------------------------
    def _add(self, user_id, trip_id, kind, title, body):
        self.session.add(UserNotification(user_id=user_id, trip_id=trip_id, kind=kind, title=title[:100], body=body[:255]))

    def member_joined(self, trip, member):
        """The trip owner learns that an invited companion joined."""
        try:
            self._add(trip.user_id, trip.trip_id, "MEMBER_JOINED", "동행자가 참여했어요",
                      f"{person_label(member)}이 '{trip_label(trip)}'에 참여했어요.")
        except Exception as error:  # never block the join itself
            logger.info("notification_failed kind=MEMBER_JOINED reason=%s", type(error).__name__)

    def member_left(self, trip, member):
        """The trip owner learns that a companion left the shared trip."""
        try:
            self._add(trip.user_id, trip.trip_id, "MEMBER_LEFT", "동행자가 나갔어요",
                      f"{person_label(member)}이 '{trip_label(trip)}'에서 나갔어요.")
        except Exception as error:
            logger.info("notification_failed kind=MEMBER_LEFT reason=%s", type(error).__name__)

    def plan_edited(self, trip, editor_id, detail):
        """Everyone on the trip except the editor learns about the change."""
        try:
            editor = UserRepository(self.session).get(editor_id)
            recipients = {trip.user_id} | {
                row.member_user_id for row in TripCompanionRepository(self.session).list(trip.trip_id)
                if row.member_user_id is not None
            }
            recipients.discard(editor_id)
            for user_id in recipients:
                self._add(user_id, trip.trip_id, "PLAN_EDITED", "일정이 수정됐어요",
                          f"{person_label(editor)}이 '{trip_label(trip)}' 일정을 수정했어요. {detail}".strip())
        except Exception as error:
            logger.info("notification_failed kind=PLAN_EDITED reason=%s", type(error).__name__)

    # -- reading ---------------------------------------------------------
    def list(self, user_id):
        rows = self.session.scalars(
            select(UserNotification).where(UserNotification.user_id == user_id)
            .order_by(UserNotification.created_at.desc(), UserNotification.notification_id.desc()).limit(LIST_LIMIT)
        )
        return [
            {"notification_id": row.notification_id, "trip_id": row.trip_id, "kind": row.kind, "title": row.title,
             "body": row.body, "created_at": row.created_at, "read": row.read_at is not None}
            for row in rows
        ]

    def mark_all_read(self, user_id):
        self.session.execute(
            update(UserNotification).where(UserNotification.user_id == user_id, UserNotification.read_at.is_(None))
            .values(read_at=datetime.utcnow())
        )
        self.session.commit()
