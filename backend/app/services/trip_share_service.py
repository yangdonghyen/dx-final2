"""Share and invite links for a trip.

Raw tokens only leave the server once, inside the created URL; the database
keeps their SHA-256 hash so a leaked table cannot be turned into links.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from app.core.exceptions import AppError
from app.repositories.plan_repository import PlanItemRepository, PlanRepository
from app.repositories.trip_repository import TripCompanionRepository, TripRepository, TripSelectedPlaceRepository, TripShareLinkRepository
from app.repositories.user_repository import UserRepository
from app.services.notification_service import NotificationService
from app.schemas.trip import SharedTripCompanionResponse, SharedTripDay, SharedTripResponse, SharedTripStop, TripJoinResponse, TripShareLinkResponse

INVITE_LINK_LIFETIME = timedelta(days=7)
# Shown when an invited user has no nickname; it describes the row, it is not a guessed name.
UNNAMED_MEMBER_LABEL = "초대받은 동행자"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TripShareService:
    def __init__(self, session, now=datetime.now):
        self.session = session
        self.now = now
        self.trips = TripRepository(session)
        self.links = TripShareLinkRepository(session)
        self.trip_companions = TripCompanionRepository(session)
        self.selected_places = TripSelectedPlaceRepository(session)
        self.users = UserRepository(session)
        self.plans = PlanRepository(session)
        self.plan_items = PlanItemRepository(session)

    def _owned_trip(self, user_id, trip_id):
        trip = self.trips.get(trip_id)
        if trip is None or trip.status == "ARCHIVED": raise AppError("TRIP_NOT_FOUND", "Trip not found", 404)
        if trip.user_id != user_id: raise AppError("FORBIDDEN", "You do not own this trip", 403)
        return trip

    def _active_link(self, token):
        link = self.links.get_by_token_hash(hash_token(token))
        if link is None or link.revoked_at is not None: raise AppError("SHARE_LINK_NOT_FOUND", "Share link not found", 404)
        if link.expires_at is not None and link.expires_at <= self.now(): raise AppError("SHARE_LINK_EXPIRED", "Share link expired", 410)
        trip = self.trips.get(link.trip_id)
        if trip is None or trip.status == "ARCHIVED": raise AppError("SHARE_LINK_NOT_FOUND", "Share link not found", 404)
        return link, trip

    def create_link(self, user_id, trip_id, link_type, base_url):
        self._owned_trip(user_id, trip_id)
        token = secrets.token_urlsafe(24)
        expires_at = self.now() + INVITE_LINK_LIFETIME if link_type == "INVITE" else None
        try:
            self.links.create(trip_id=trip_id, created_by_user_id=user_id, token_hash=hash_token(token), link_type=link_type, expires_at=expires_at)
            self.session.commit()
        except Exception:
            self.session.rollback(); raise
        return TripShareLinkResponse(link_type=link_type, url=f"{base_url.rstrip('/')}/api/v1/shared-trips/{token}", expires_at=expires_at)

    def shared_trip(self, token):
        link, trip = self._active_link(token)
        owner = self.users.get(trip.user_id)
        companions = [SharedTripCompanionResponse(name=row.name_snapshot, relation=row.relation_snapshot) for row in self.trip_companions.list(trip.trip_id)]
        places = [row.place.name for row in self.selected_places.list(trip.trip_id) if row.place is not None]
        return SharedTripResponse(link_type=link.link_type, title=trip.title, destination=trip.destination, start_date=trip.start_date, end_date=trip.end_date, owner_nickname=owner.nickname if owner else None, companions=companions, selected_places=places, days=self._shared_days(trip))

    def _shared_days(self, trip):
        """The saved itinerary as shown to people who open the link."""
        plan = self.plans.get_by_trip_id(trip.trip_id)
        if plan is None: return []
        grouped = {}
        for item in self.plan_items.list(plan.plan_id): grouped.setdefault(item.visit_date, []).append(item)
        return [
            SharedTripDay(
                day=(visit_date - trip.start_date).days + 1 if trip.start_date else index,
                visit_date=visit_date,
                stops=[SharedTripStop(start_time=item.start_time.strftime("%H:%M") if item.start_time else None, title=item.title, item_type=item.item_type, note=getattr(item, "user_note", None)) for item in rows],
            )
            for index, (visit_date, rows) in enumerate(sorted(grouped.items()), 1)
        ]

    def leave(self, user, trip_id):
        """A companion leaves a trip they joined by invite; the owner is told.
        Joining again needs a new invite link."""
        trip = self.trips.get(trip_id)
        if trip is None or trip.status == "ARCHIVED": raise AppError("TRIP_NOT_FOUND", "Trip not found", 404)
        if trip.user_id == user.user_id: raise AppError("OWNER_CANNOT_LEAVE", "The owner deletes the trip instead", 400)
        member = self.trip_companions.get_member(trip.trip_id, user.user_id)
        if member is None: raise AppError("NOT_A_MEMBER", "You are not part of this trip", 404)
        try:
            self.session.delete(member)
            NotificationService(self.session).member_left(trip, user)
            self.session.commit()
        except Exception:
            self.session.rollback(); raise
        return {"trip_id": trip.trip_id, "left": True}

    def join(self, user, token):
        link, trip = self._active_link(token)
        if link.link_type != "INVITE": raise AppError("SHARE_LINK_NOT_INVITE", "This link is view only", 400)
        if trip.user_id == user.user_id: raise AppError("OWNER_CANNOT_JOIN", "Trip owner is already part of this trip", 400)
        if self.trip_companions.get_member(trip.trip_id, user.user_id) is not None:
            return TripJoinResponse(trip_id=trip.trip_id, already_joined=True)
        try:
            self.trip_companions.create(trip.trip_id, member_user_id=user.user_id, name_snapshot=(user.nickname or UNNAMED_MEMBER_LABEL)[:50], relation_snapshot="FRIEND", age_group_snapshot=getattr(user, "age_group", None))
            NotificationService(self.session).member_joined(trip, user)
            self.session.commit()
        except Exception:
            self.session.rollback(); raise
        return TripJoinResponse(trip_id=trip.trip_id, already_joined=False)
