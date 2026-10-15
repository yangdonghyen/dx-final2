from app.core.exceptions import AppError
import logging
from datetime import date

from app.repositories.companion_repository import CompanionInterestRepository, CompanionPreferenceRepository, CompanionRepository
from app.repositories.trip_repository import TripCompanionRepository, TripInterestRepository, TripPreferenceRepository, TripRepository, TripSelectedPlaceRepository
from app.repositories.user_repository import InterestCodeRepository, UserInterestRepository, UserPreferenceRepository
from app.schemas.trip import TripCompanionResponse, TripDetailResponse, TripInterestResponse, TripListItemResponse, TripPreferenceResponse, TripSelectedPlaceResponse


class TripService:
    def __init__(self, session):
        self.session = session
        self.trips = TripRepository(session)
        self.preferences = TripPreferenceRepository(session)
        self.selected_places = TripSelectedPlaceRepository(session)
        self.trip_companions = TripCompanionRepository(session)
        self.trip_interests = TripInterestRepository(session)
        self.user_preferences = UserPreferenceRepository(session)
        self.user_interests = UserInterestRepository(session)
        self.companions = CompanionRepository(session)
        self.companion_preferences = CompanionPreferenceRepository(session)
        self.companion_interests = CompanionInterestRepository(session)
        self.codes = InterestCodeRepository(session)

    def _owned(self, user_id, trip_id):
        trip = self.trips.get(trip_id)
        if trip is None: raise AppError("TRIP_NOT_FOUND", "Trip not found", 404)
        if trip.user_id != user_id: raise AppError("FORBIDDEN", "You do not own this trip", 403)
        return trip

    def _validate_codes(self, codes):
        if len(self.codes.active_codes(codes)) != len(codes): raise AppError("INVALID_INTEREST_CODE", "Invalid interest code", 400)

    def _validated_companions(self, user_id, companion_ids):
        result = []
        for companion_id in companion_ids:
            companion = self.companions.get(companion_id)
            if companion is None: raise AppError("COMPANION_NOT_FOUND", "Companion not found", 404)
            if companion.user_id != user_id: raise AppError("FORBIDDEN", "You do not own this companion", 403)
            if companion.status != "ACTIVE": raise AppError("COMPANION_ARCHIVED", "Companion is archived", 400)
            result.append(companion)
        return result

    def _preference_values(self, user_id, override):
        source = self.user_preferences.get(user_id)
        values = {"walking_tolerance": source.walking_tolerance if source else None, "rest_frequency": source.rest_frequency if source else None, "avoid_stairs": source.avoid_stairs if source else False, "avoid_hills": source.avoid_hills if source else False, "taxi_allowed": source.taxi_allowed if source else True, "travel_style": getattr(source, "travel_style", None) if source else None}
        if override is not None: values.update(override.model_dump(exclude_unset=True))
        return values

    def _companion_snapshot(self, companion):
        preference = self.companion_preferences.get(companion.companion_id)
        return {"companion_id": companion.companion_id, "name_snapshot": companion.name, "relation_snapshot": companion.relation, "age_group_snapshot": companion.age_group, "walking_tolerance": preference.walking_tolerance, "rest_frequency": preference.rest_frequency, "avoid_stairs": preference.avoid_stairs, "avoid_hills": preference.avoid_hills, "taxi_allowed": preference.taxi_allowed, "interests_snapshot": self.companion_interests.list_codes(companion.companion_id)}

    def _detail(self, trip):
        preference = self.preferences.get(trip.trip_id)
        companions = [TripCompanionResponse(companion_id=row.companion_id, name=row.name_snapshot, relation=row.relation_snapshot, age_group=row.age_group_snapshot, preferences=TripPreferenceResponse(walking_tolerance=row.walking_tolerance, rest_frequency=row.rest_frequency, avoid_stairs=row.avoid_stairs, avoid_hills=row.avoid_hills, taxi_allowed=row.taxi_allowed), interests=row.interests_snapshot or [], joined_by_invite=getattr(row, "member_user_id", None) is not None) for row in self.trip_companions.list(trip.trip_id)]
        interests = [TripInterestResponse(interest_code=row.interest_code, source_type=row.source_type, is_confirmed=row.is_confirmed) for row in self.trip_interests.list(trip.trip_id)]
        selected_places = [TripSelectedPlaceResponse(place_id=row.place_id, name=row.place.name, region=row.place.region, address=row.place.address, latitude=float(row.place.latitude) if row.place.latitude is not None else None, longitude=float(row.place.longitude) if row.place.longitude is not None else None, category=row.place.category, selected_order=row.selected_order) for row in self.selected_places.list(trip.trip_id) if row.place is not None]
        return TripDetailResponse(trip_id=trip.trip_id, title=trip.title, departure=trip.departure, destination=trip.destination, start_date=trip.start_date, end_date=trip.end_date, status=trip.status, budget_krw=trip.budget_krw, transport_mode=trip.transport_mode, preferences=TripPreferenceResponse(walking_tolerance=preference.walking_tolerance, rest_frequency=preference.rest_frequency, avoid_stairs=preference.avoid_stairs, avoid_hills=preference.avoid_hills, taxi_allowed=preference.taxi_allowed, travel_style=getattr(preference, "travel_style", None)), companions=companions, interests=interests, selected_places=selected_places)

    def create(self, user_id, request):
        companions = self._validated_companions(user_id, request.companion_ids)
        user_codes = request.interest_codes or []
        self._validate_codes(user_codes)
        try:
            trip = self.trips.create(user_id, **request.model_dump(exclude={"companion_ids", "trip_preferences", "interest_codes"}, by_alias=False))
            self.preferences.create(trip.trip_id, **self._preference_values(user_id, request.trip_preferences))
            for companion in companions: self.trip_companions.create(trip.trip_id, **self._companion_snapshot(companion))
            # A trip is an explicit planning request.  Do not merge profile
            # interests here: that could reintroduce an interest the user did
            # not select for this trip, such as SEA after choosing CITY.
            for code in user_codes: self.trip_interests.create(trip.trip_id, code, "USER", True)
            logging.getLogger("uvicorn.error").info(
                "trip interest snapshot trip_id=%s request_interests=%s snapshot_interests=%s",
                trip.trip_id,
                user_codes,
                [row.interest_code for row in self.trip_interests.list(trip.trip_id)],
            )
            self.session.commit()
            return trip
        except Exception:
            self.session.rollback(); raise

    def list(self, user_id):
        row = lambda trip, role: TripListItemResponse(trip_id=trip.trip_id, title=trip.title, departure=trip.departure, destination=trip.destination, start_date=trip.start_date, end_date=trip.end_date, status=trip.status, role=role)
        owned = [row(trip, "OWNER") for trip in self.trips.list_active_for_user(user_id)]
        joined_lookup = getattr(self.trips, "list_joined_by_member", None)
        joined = [row(trip, "MEMBER") for trip in joined_lookup(user_id)] if joined_lookup else []
        return sorted(owned + joined, key=lambda item: (item.start_date is None, item.start_date or date.max, item.trip_id))

    def detail(self, user_id, trip_id): return self._detail(self._owned(user_id, trip_id))

    def update(self, user_id, trip_id, request):
        trip = self._owned(user_id, trip_id)
        values = request.model_dump(exclude_unset=True, exclude={"companion_ids", "trip_preferences", "interest_codes"}, by_alias=False)
        if "start_date" not in values: values["start_date"] = trip.start_date
        if "end_date" not in values: values["end_date"] = trip.end_date
        if values["start_date"] and values["end_date"] and values["end_date"] < values["start_date"]: raise AppError("VALIDATION_ERROR", "end_date must not be before start_date", 422)
        companions = self._validated_companions(user_id, request.companion_ids) if request.companion_ids is not None else None
        if request.interest_codes is not None: self._validate_codes(request.interest_codes)
        try:
            self.trips.update(trip, **values)
            if request.trip_preferences is not None:
                override = request.trip_preferences.model_dump(exclude_unset=True)
                if override: self.preferences.update(self.preferences.get(trip_id), **override)
            if companions is not None:
                existing = {row.companion_id for row in self.trip_companions.list(trip_id)}
                self.trip_companions.remove_not_in(trip_id, request.companion_ids)
                for companion in companions:
                    if companion.companion_id not in existing: self.trip_companions.create(trip_id, **self._companion_snapshot(companion))
            if request.interest_codes is not None:
                self.trip_interests.remove_user_and_codes(trip_id, request.interest_codes)
                for code in request.interest_codes: self.trip_interests.create(trip_id, code, "USER", True)
            self.session.commit()
            return self._detail(trip)
        except Exception:
            self.session.rollback(); raise

    def archive(self, user_id, trip_id):
        trip = self._owned(user_id, trip_id)
        try:
            self.trips.update(trip, status="ARCHIVED")
            self.session.commit()
        except Exception:
            self.session.rollback(); raise


