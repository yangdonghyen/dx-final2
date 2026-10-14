from datetime import UTC, datetime
from decimal import Decimal

from app.core.exceptions import AppError
from app.repositories.place_repository import PlaceRepository
from app.schemas.place import PlaceSearchItemResponse


class PlaceSearchService:
    def __init__(self, session, place_provider, *, commit: bool = True):
        self.session = session
        self.places = PlaceRepository(session)
        self.place_provider = place_provider
        # Plan generation owns its own all-or-nothing transaction.  Direct
        # search endpoints retain the existing immediate-cache behaviour.
        self.commit_on_success = commit

    @staticmethod
    def _fields(candidate, region):
        if (
            candidate.external_provider != "KAKAO"
            or not candidate.external_id
            or not candidate.name
        ):
            raise AppError("EXTERNAL_PROVIDER_ERROR", "Invalid place provider result", 500)
        if not isinstance(candidate.latitude, (int, float)) or not isinstance(
            candidate.longitude, (int, float)
        ):
            raise AppError("EXTERNAL_PROVIDER_ERROR", "Invalid place provider result", 500)
        if not -90 <= candidate.latitude <= 90 or not -180 <= candidate.longitude <= 180:
            raise AppError("EXTERNAL_PROVIDER_ERROR", "Invalid place provider result", 500)
        return {
            "name": candidate.name,
            "category": candidate.category,
            "region": region,
            "address": candidate.address,
            "latitude": Decimal(str(candidate.latitude)),
            "longitude": Decimal(str(candidate.longitude)),
            "kakao_place_id": candidate.external_id,
            "phone": candidate.phone,
            "website": candidate.source_url,
            "details_updated_at": datetime.now(UTC).replace(tzinfo=None),
        }

    def upsert_candidates(self, candidates, region: str | None = None):
        unique = []
        seen = set()
        for candidate in candidates:
            key = (candidate.external_provider, candidate.external_id)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        try:
            results = []
            for candidate in unique:
                fields = self._fields(candidate, region)
                place = self.places.get_by_kakao_place_id(candidate.external_id)
                if place is None:
                    place = self.places.create(**fields)
                else:
                    place = self.places.update(place, **fields)
                results.append(
                    PlaceSearchItemResponse(
                        place_id=place.place_id,
                        name=place.name,
                        region=place.region,
                        address=place.address,
                        latitude=place.latitude,
                        longitude=place.longitude,
                    )
                )
            if self.commit_on_success:
                self.session.commit()
            else:
                self.session.flush()
            return results
        except Exception:
            self.session.rollback()
            raise

    def search(self, query: str, region: str | None = None):
        return self.upsert_candidates(self.place_provider.search(query, region), region)
