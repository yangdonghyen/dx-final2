from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.trip import Trip, TripCompanion, TripInterest, TripPreference, TripSelectedPlace, TripShareLink, TripSource


class TripRepository:
    def __init__(self, session: Session): self.session = session
    def get(self, trip_id: int): return self.session.get(Trip, trip_id)
    def list_active_for_user(self, user_id: int):
        return list(self.session.scalars(select(Trip).where(Trip.user_id == user_id, Trip.status != "ARCHIVED").order_by(Trip.start_date, Trip.trip_id)))
    def list_joined_by_member(self, user_id: int):
        """Trips this user joined through an invite link (not owned)."""
        return list(self.session.scalars(
            select(Trip).join(TripCompanion, TripCompanion.trip_id == Trip.trip_id)
            .where(TripCompanion.member_user_id == user_id, Trip.user_id != user_id, Trip.status != "ARCHIVED")
            .order_by(Trip.start_date, Trip.trip_id)
        ))
    def create(self, user_id: int, **fields):
        trip = Trip(user_id=user_id, **fields)
        self.session.add(trip); self.session.flush(); return trip
    def update(self, trip, **fields):
        for field, value in fields.items(): setattr(trip, field, value)
        self.session.flush(); return trip


class TripPreferenceRepository:
    def __init__(self, session: Session): self.session = session
    def get(self, trip_id: int): return self.session.scalar(select(TripPreference).where(TripPreference.trip_id == trip_id))
    def create(self, trip_id: int, **fields):
        preference = TripPreference(trip_id=trip_id, **fields)
        self.session.add(preference); self.session.flush(); return preference
    def update(self, preference, **fields):
        for field, value in fields.items(): setattr(preference, field, value)
        self.session.flush(); return preference


class TripSelectedPlaceRepository:
    def __init__(self, session: Session): self.session = session
    def list(self, trip_id: int):
        return list(self.session.scalars(select(TripSelectedPlace).where(TripSelectedPlace.trip_id == trip_id).order_by(TripSelectedPlace.selected_order, TripSelectedPlace.trip_selected_place_id)))
    def replace(self, trip_id: int, places):
        # MySQL can process a pending INSERT before a DELETE in one flush,
        # which violates the still-existing (trip_id, place_id) unique key.
        deduplicated = []
        seen_place_ids = set()
        for place in places:
            if place.place_id not in seen_place_ids:
                deduplicated.append(place)
                seen_place_ids.add(place.place_id)
        existing = self.list(trip_id)
        if [row.place_id for row in existing] == [place.place_id for place in deduplicated]:
            return
        for selected in existing:
            self.session.delete(selected)
        # Force DELETE statements out before replacement INSERT statements.
        self.session.flush()
        for selected_order, place in enumerate(deduplicated, start=1):
            self.session.add(TripSelectedPlace(trip_id=trip_id, place_id=place.place_id, selected_order=selected_order))
        self.session.flush()


class TripCompanionRepository:
    def __init__(self, session: Session): self.session = session
    def list(self, trip_id: int): return list(self.session.scalars(select(TripCompanion).where(TripCompanion.trip_id == trip_id).order_by(TripCompanion.trip_companion_id)))
    def create(self, trip_id: int, **fields):
        snapshot = TripCompanion(trip_id=trip_id, **fields)
        self.session.add(snapshot); self.session.flush(); return snapshot
    def get_member(self, trip_id: int, member_user_id: int):
        return self.session.scalar(select(TripCompanion).where(TripCompanion.trip_id == trip_id, TripCompanion.member_user_id == member_user_id))
    def remove_not_in(self, trip_id: int, companion_ids: list[int]):
        # Invited members are not owner-managed companion profiles; keep them.
        for snapshot in self.list(trip_id):
            if snapshot.member_user_id is None and snapshot.companion_id not in companion_ids: self.session.delete(snapshot)
        self.session.flush()


class TripShareLinkRepository:
    def __init__(self, session: Session): self.session = session
    def get_by_token_hash(self, token_hash: str):
        return self.session.scalar(select(TripShareLink).where(TripShareLink.token_hash == token_hash))
    def create(self, **fields):
        link = TripShareLink(**fields)
        self.session.add(link); self.session.flush(); return link


class TripInterestRepository:
    def __init__(self, session: Session): self.session = session
    def list(self, trip_id: int): return list(self.session.scalars(select(TripInterest).where(TripInterest.trip_id == trip_id).order_by(TripInterest.interest_code)))
    def create(self, trip_id: int, interest_code: str, source_type: str, is_confirmed: bool):
        interest = TripInterest(trip_id=trip_id, interest_code=interest_code, source_type=source_type, is_confirmed=is_confirmed)
        self.session.add(interest); self.session.flush(); return interest
    def remove_user_and_codes(self, trip_id: int, codes: list[str]):
        for interest in self.list(trip_id):
            if interest.source_type == "USER" or interest.interest_code in codes: self.session.delete(interest)
        self.session.flush()
    def remove_content_ai(self, trip_id: int):
        for interest in self.list(trip_id):
            if interest.source_type == "CONTENT_AI": self.session.delete(interest)
        self.session.flush()



class TripSourceRepository:
    def __init__(self, session: Session): self.session = session
    def get(self, source_id: int): return self.session.get(TripSource, source_id)
    def get_by_external(self, trip_id: int, external_id: str):
        return self.session.scalar(select(TripSource).where(TripSource.trip_id == trip_id, TripSource.source_type == "YOUTUBE", TripSource.external_id == external_id))
    def list_active(self, trip_id: int):
        return list(self.session.scalars(select(TripSource).where(TripSource.trip_id == trip_id, TripSource.is_active.is_(True)).order_by(TripSource.source_id)))
    def create(self, trip_id: int, **fields):
        source = TripSource(trip_id=trip_id, source_type="YOUTUBE", **fields)
        self.session.add(source); self.session.flush(); return source
    def update(self, source, **fields):
        for field, value in fields.items(): setattr(source, field, value)
        self.session.flush(); return source


