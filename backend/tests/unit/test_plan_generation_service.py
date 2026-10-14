from dataclasses import dataclass
from datetime import date, time
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.schemas.plan import PlanGenerateRequest
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.place.provider import PlaceCandidate
from app.services.external.routing.provider import RouteEstimate
from app.services.external.naver_api_hub_provider import NaverBlogPost, NaverLocalPlace


@dataclass
class Place:
    place_id: int
    name: str
    category: str = "CULTURE"
    region: str = "Seoul"
    address: str = "Seoul Jongno-gu"
    latitude: float = 37.5
    longitude: float = 126.9
    kakao_place_id: str | None = None
    opening_hours: dict | None = None
    verification_status: str = "UNKNOWN"
    event_start_date: date | None = None
    event_end_date: date | None = None


class Session:
    def __init__(self):
        self.trips = {
            1: SimpleNamespace(trip_id=1, user_id=1, status="DRAFT", departure="Seoul", destination="Seoul", start_date=date(2026, 10, 10), end_date=date(2026, 10, 10), budget_krw=100000, transport_mode="PUBLIC_TRANSIT"),
            2: SimpleNamespace(trip_id=2, user_id=2, status="DRAFT", departure="Seoul", destination="Seoul", start_date=date(2026, 10, 10), end_date=date(2026, 10, 10), budget_krw=100000, transport_mode="PUBLIC_TRANSIT"),
            3: SimpleNamespace(trip_id=3, user_id=1, status="ARCHIVED"),
        }
        self.places = [Place(101, "Museum", kakao_place_id="anchor"), Place(104, "Cafe", latitude=37.501, longitude=126.901, kakao_place_id="cached")]
        self.plans = {}
        self.selected_places = {}
        self.items = []
        self.interest_codes = ["CULTURE"]
        self.commits = self.rollbacks = 0

    def commit(self):
        self.commits += 1
        self._committed_selected_places = {trip_id: list(places) for trip_id, places in self.selected_places.items()}
        self._committed_plans = dict(self.plans)
        self._committed_items = list(self.items)
    def rollback(self):
        self.rollbacks += 1
        self.selected_places = {trip_id: list(places) for trip_id, places in getattr(self, "_committed_selected_places", {}).items()}
        self.plans = dict(getattr(self, "_committed_plans", {}))
        self.items = list(getattr(self, "_committed_items", []))
    def flush(self): pass


class Trips:
    def __init__(self, session): self.session = session
    def get(self, trip_id): return self.session.trips.get(trip_id)


class Preferences:
    def __init__(self, session): pass
    def get(self, trip_id): return SimpleNamespace(walking_tolerance="LOW", rest_frequency="HIGH", avoid_stairs=True, avoid_hills=False, taxi_allowed=True)


class UserPreferences:
    def __init__(self, session): self.session = session
    def get(self, user_id): return SimpleNamespace(senior_mode=getattr(self.session, "senior_mode", False))


class Companions:
    def __init__(self, session): pass
    def list(self, trip_id): return []


class Interests:
    def __init__(self, session): self.session = session
    def list(self, trip_id): return [SimpleNamespace(interest_code=code) for code in self.session.interest_codes]


class Places:
    def __init__(self, session): self.session = session
    def get(self, place_id): return next((place for place in self.session.places if place.place_id == place_id), None)
    def list(self): return list(self.session.places)
    def list_nearby(self, latitude, longitude, radius_meters, excluded_place_ids=None):
        excluded_place_ids = excluded_place_ids or set()
        return [place for place in self.session.places if place.place_id not in excluded_place_ids]
    @staticmethod
    def _distance_meters(*_): return 100


class SelectedPlaces:
    def __init__(self, session): self.session = session
    def list(self, trip_id):
        return [SimpleNamespace(place=place, place_id=place.place_id, selected_order=index) for index, place in enumerate(self.session.selected_places.get(trip_id, []), start=1)]
    def replace(self, trip_id, places):
        self.session.selected_places[trip_id] = list(places)


class Plans:
    def __init__(self, session): self.session = session
    def get_by_trip_id(self, trip_id): return self.session.plans.get(trip_id)
    def create(self, trip_id):
        plan = SimpleNamespace(plan_id=len(self.session.plans) + 30, trip_id=trip_id, status="DRAFT")
        self.session.plans[trip_id] = plan
        return plan


class Items:
    def __init__(self, session): self.session = session
    def create(self, plan_id, **fields):
        item = SimpleNamespace(item_id=len(self.session.items) + 1001, plan_id=plan_id, **fields)
        self.session.items.append(item)
        return item


class Validation:
    def __init__(self, session): self.session = session
    def validate(self, plan, trip):
        for item in self.session.items: item.validation_status = "VALID"
        return []


class Provider:
    def __init__(self, draft): self.draft = draft; self.calls = []
    def generate_plan(self, *args): self.calls.append(args); return self.draft


class NearbyProvider:
    def __init__(self, candidates=None, error=None): self.candidates = candidates or []; self.error = error; self.calls = []
    def search_nearby(self, *args):
        self.calls.append(args)
        if self.error: raise self.error
        return self.candidates


class NearbySearchService:
    def __init__(self, session, provider, *, commit=True): self.session = session; self.provider = provider; self.commit = commit
    def upsert_candidates(self, candidates, region):
        result = []
        for candidate in candidates:
            place = next((row for row in self.session.places if row.kakao_place_id == candidate.external_id), None)
            if place is None:
                place = Place(len(self.session.places) + 101, candidate.name, candidate.category, region or "", candidate.address, candidate.latitude, candidate.longitude, candidate.external_id)
                self.session.places.append(place)
            result.append(SimpleNamespace(place_id=place.place_id))
        return result


class Routes:
    def __init__(self, estimates): self.estimates = estimates; self.calls = []
    def route(self, *_coordinates_and_mode):
        self.calls.append(_coordinates_and_mode)
        return self.estimates.get(_coordinates_and_mode[-1])


class NaverEvidence:
    def search_local(self, query):
        return [NaverLocalPlace("Verified Cafe", "카페", "Seoul Jongno-gu 1", "Seoul Jongno-gu 1", 37.5005, 126.9005)]
    def search_blog(self, query, limit=5):
        return [NaverBlogPost("Verified Cafe 방문 후기", "Seoul Jongno-gu 조용한 휴식", date(2026, 1, 1), "https://example.test/post")]


def draft(*place_ids):
    items = [PlanDraftItem(index + 1, "PLACE", f"Place {place_id}", place_id, f"{10 + index}:00", f"{10 + index}:30", "reason") for index, place_id in enumerate(place_ids)]
    items.append(PlanDraftItem(len(items) + 1, "REST", "Rest", None, "15:00", "15:30", "reason"))
    return GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), items)])


@pytest.fixture
def service(monkeypatch):
    import app.services.plan_generation_service as module
    replacements = {"TripRepository": Trips, "TripPreferenceRepository": Preferences, "UserPreferenceRepository": UserPreferences, "TripSelectedPlaceRepository": SelectedPlaces, "TripCompanionRepository": Companions, "TripInterestRepository": Interests, "PlaceRepository": Places, "PlanRepository": Plans, "PlanItemRepository": Items, "PlanValidationService": Validation, "PlaceSearchService": NearbySearchService}
    for name, replacement in replacements.items(): monkeypatch.setattr(module, name, replacement)
    session = Session()
    provider = Provider(draft(101))
    return module.PlanGenerationService(session, provider), session, provider, module


def test_selected_places_are_anchors_and_cached_nearby_places_are_reused(service):
    generator, session, provider, _ = service
    response = generator.generate(1, 1, [101])
    candidates = provider.calls[0][5]
    assert [row["place_id"] for row in candidates] == [101, 104]
    assert [row["is_anchor"] for row in candidates] == [True, False]
    assert response.days[0].items[0].latitude == 37.5
    assert response.days[0].items[-1].place_id is None
    assert response.days[0].items[-1].latitude is None
    assert session.commits == 1


@pytest.mark.parametrize("failure", [
    AppError("ROUTE_TIME_CONFLICT", "verified route does not fit", 422),
    TimeoutError("EXAONE timed out"),
])
def test_failed_generation_keeps_previously_committed_selection_and_plan_state(service, failure):
    """Model/validation failures must not replace a user's saved anchors."""
    generator, session, _, _ = service
    previous = session.places[1]
    session.selected_places[1] = [previous]
    session.commit()  # Model the state that existed before this request.

    class FailingProvider:
        def generate_plan(self, *_args):
            raise failure

    generator.provider = FailingProvider()
    with pytest.raises(type(failure)):
        generator.generate(1, 1, [101])

    assert [place.place_id for place in session.selected_places[1]] == [104]
    assert session.plans == {}
    assert session.items == []
    assert session.commits == 1
    assert session.rollbacks >= 1


def test_late_save_validation_failure_rolls_back_selection_and_new_plan(service):
    generator, session, _, _ = service
    session.selected_places[1] = [session.places[1]]
    session.commit()

    class FailingValidation:
        def validate(self, *_args):
            raise AppError("OUTSIDE_OPENING_HOURS", "verified hours do not fit", 422)

    generator.validation = FailingValidation()
    with pytest.raises(AppError, match="verified hours"):
        generator.generate(1, 1, [101])

    assert [place.place_id for place in session.selected_places[1]] == [104]
    assert session.plans == {}
    assert session.items == []
    assert session.commits == 1


def test_omitted_place_ids_keep_existing_anchors(service):
    generator, session, provider, _ = service
    session.selected_places[1] = [session.places[0]]

    generator.generate(1, 1, None)

    assert session.selected_places[1] == [session.places[0]]
    assert provider.calls[0][5][0]["place_id"] == 101
    assert provider.calls[0][5][0]["is_anchor"] is True


def test_generation_enriches_only_linked_places_before_ai_input(service):
    generator, session, provider, _ = service

    class TourHours:
        calls = []
        def get_place_detail(self, content_id, *, include_images=True):
            self.calls.append((content_id, include_images))
            return {"operating_hours": "\ub9e4\uc77c 09:00~18:00", "rest_date": None}

    session.places[0].tour_content_id = "12345"
    generator.tour_hours_provider = TourHours()
    generator.generate(1, 1, [101])

    assert generator.tour_hours_provider.calls == [("12345", False)]
    assert provider.calls[0][5][0]["opening_hours"]["monday"] == {"open": "09:00", "close": "18:00"}


def test_verified_lunch_hours_conflict_is_rejected(service):
    generator, _, _, _ = service
    place = Place(101, "Lunch", category="FD6")
    place.verification_status = "VERIFIED"
    place.opening_hours = {"saturday": {"open": "09:00", "close": "11:30"}}
    item = PlanDraftItem(1, "MEAL", "Lunch", 101, "12:00", "13:00", "reason")

    with pytest.raises(AppError) as error:
        generator._validate_temporal_draft([(date(2026, 10, 10), [(item, time(12), time(13))])], {101: place})

    assert error.value.code == "OUTSIDE_OPENING_HOURS"


def test_rest_slot_uses_verified_nearby_cafe_without_changing_its_time(service):
    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = NaverEvidence()
    generator.route_provider = Routes({"PUBLIC_TRANSIT": RouteEstimate(5 * 60, "PUBLIC_TRANSIT", distance_meters=400)})
    places = {place.place_id: place for place in session.places}
    proposal = GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
        PlanDraftItem(3, "PLACE", "Next", 104, "11:50", "12:30", "next"),
    ])])

    attached = generator._attach_rest_cafes(proposal, places, session.trips[1], {"rest_frequency": "HIGH"})

    cafe = attached.days[0].items[1]
    assert (cafe.item_type, cafe.title, cafe.start_time, cafe.end_time) == ("PLACE", "Verified Cafe", "11:10", "11:40")
    assert cafe.place_id in places and session.places[-1].kakao_place_id == "rest-cafe"


def test_rest_slot_stays_unassigned_when_route_fact_is_unknown(service):
    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = NaverEvidence()
    generator.route_provider = Routes({})
    places = {place.place_id: place for place in session.places}
    proposal = GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
    ])])

    attached = generator._attach_rest_cafes(proposal, places, session.trips[1], {"rest_frequency": "HIGH"})

    assert attached.days[0].items[1].item_type == "REST"
    assert attached.days[0].items[1].title == "자유 휴식"


def test_mock_cafe_selection_logs_only_slot_diagnostics(service, caplog):
    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = NaverEvidence()
    generator.route_provider = Routes({"PUBLIC_TRANSIT": RouteEstimate(5 * 60, "PUBLIC_TRANSIT", distance_meters=400)})
    places = {place.place_id: place for place in session.places}
    proposal = GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
    ])])

    with caplog.at_level("DEBUG", logger="uvicorn.error"):
        generator._attach_rest_cafes(proposal, places, session.trips[1], {"rest_frequency": "HIGH"})

    message = next(record.getMessage() for record in caplog.records if "plan_rest_cafe_selection" in record.getMessage())
    assert "kakao_candidates" in message and "naver_matches" in message and "route_checks" in message
    assert "Verified Cafe" not in message and "37.5005" not in message
    candidate_log = next(record.getMessage() for record in caplog.records if "rest_cafe_candidate " in record.getMessage())
    assert "kakao_rank=1" in candidate_log and "chain_group=" in candidate_log and "industry_pass=True" in candidate_log
    route_log = next(record.getMessage() for record in caplog.records if "naver_status=MATCHED" in record.getMessage())
    assert "review_status=VERIFIED" in route_log and "incoming_seconds=300" in route_log and "outgoing_seconds=None" in route_log
    assert "37.5005" not in candidate_log and "37.5005" not in route_log


def test_mock_cafe_selection_reports_naver_api_failure_not_business_mismatch(service, caplog):
    class FailingNaver:
        def search_local(self, query): raise AppError("NAVER_API_HUB_AUTH_FAILED", "hidden", 502)
        def search_blog(self, query, limit=5): pytest.fail("blog must not run")

    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = FailingNaver()
    generator.route_provider = Routes({"PUBLIC_TRANSIT": RouteEstimate(5 * 60, "PUBLIC_TRANSIT")})
    places = {place.place_id: place for place in session.places}
    proposal = GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
    ])])

    with caplog.at_level("INFO", logger="uvicorn.error"):
        attached = generator._attach_rest_cafes(proposal, places, session.trips[1], {"rest_frequency": "HIGH"})

    message = next(record.getMessage() for record in caplog.records if "plan_rest_cafe_selection" in record.getMessage())
    assert attached.days[0].items[1].item_type == "REST"
    assert "NAVER_LOCAL_API_FAILED" in message
    assert "NAVER_API_HUB_AUTH_FAILED" in message


def test_route_verified_kakao_cafe_can_be_selected_when_naver_has_no_same_business(service):
    class NoLocalBusiness:
        def search_local(self, query):
            return [NaverLocalPlace("Other Cafe", "Cafe", "Seoul Jongno-gu 1", "Seoul Jongno-gu 1", 37.5005, 126.9005)]
        def search_blog(self, query, limit=5):
            pytest.fail("blog must not run without a same-business match")

    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = NoLocalBusiness()
    generator.route_provider = Routes({"PUBLIC_TRANSIT": RouteEstimate(5 * 60, "PUBLIC_TRANSIT")})
    proposal = GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
    ])])

    attached = generator._attach_rest_cafes(proposal, {place.place_id: place for place in session.places}, session.trips[1], {"rest_frequency": "HIGH"})

    assert attached.days[0].items[1].item_type == "PLACE"
    assert "NAVER" not in attached.days[0].items[1].recommendation_reason


def test_cafe_lookup_interleaves_same_kakao_chain_before_spending_slot_budget(service):
    _, _, _, module = service
    cafes = [
        SimpleNamespace(place_id=1, name="Chain A one", category="Food > Cafe > Chain A"),
        SimpleNamespace(place_id=2, name="Chain A two", category="Food > Cafe > Chain A"),
        SimpleNamespace(place_id=3, name="Local cafe", category="Food > Cafe > \uce74\ud398"),
    ]

    ordered = module._diverse_cafe_lookup_order(cafes)

    # The original Kakao distance ordering within Chain A is retained, but a
    # distinct candidate receives one of the scarce local-evidence turns.
    assert [cafe.place_id for cafe in ordered] == [1, 3, 2]


def test_cafe_lookup_keeps_generic_cafe_categories_independent(service):
    _, _, _, module = service
    cafes = [
        SimpleNamespace(place_id=1, category="Food > Cafe > \ubd81\uce74\ud398"),
        SimpleNamespace(place_id=2, category="Food > Cafe > \ubd81\uce74\ud398"),
        SimpleNamespace(place_id=3, category="Food > Cafe > \ud14c\ub9c8\uce74\ud398"),
        SimpleNamespace(place_id=4, category="Food > Cafe > \ub8e8\ud504\ud0d1\uce74\ud398"),
        SimpleNamespace(place_id=5, category="Food > Cafe > \uc2a4\ud130\ub514\uce74\ud398"),
        SimpleNamespace(place_id=6, category=""),
        SimpleNamespace(place_id=7, category="Food > Cafe > Chain A"),
        SimpleNamespace(place_id=8, category="Food > Cafe > Chain A"),
    ]

    assert [module._cafe_lookup_family_key(cafe) for cafe in cafes[:6]] == [
        ("place", 1), ("place", 2), ("place", 3), ("place", 4), ("place", 5), ("place", 6),
    ]
    assert module._cafe_lookup_family_key(cafes[6]) == module._cafe_lookup_family_key(cafes[7])


def test_no_recent_naver_match_does_not_outrank_better_route_verified_cafe(service):
    class MixedEvidence:
        def search_local(self, query):
            if "Chain Cafe" in query:
                return [NaverLocalPlace("Chain Cafe", "Cafe", "Seoul Jongno-gu 9", "Seoul Jongno-gu 9", 37.506, 126.906)]
            return [NaverLocalPlace("Different Cafe", "Cafe", "Seoul Jongno-gu 1", "Seoul Jongno-gu 1", 37.5004, 126.9004)]
        def search_blog(self, query, limit=5):
            return []

    class QualityRoutes:
        def route(self, first_lat, first_lon, second_lat, second_lon, mode):
            # Chain Cafe is feasible but meaningfully farther on either leg.
            seconds = 600 if 126.906 in (first_lon, second_lon) else 60
            return RouteEstimate(seconds, mode, distance_meters=seconds * 2)

    generator, session, _, _ = service
    session.places.extend([
        Place(105, "Chain Cafe", "CE7", "Seoul", "Seoul Jongno-gu 9", 37.506, 126.906, "chain"),
        Place(106, "Local Cafe", "CE7", "Seoul", "Seoul Jongno-gu 1", 37.5004, 126.9004, "local"),
    ])
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "chain", "Chain Cafe", "CE7", "Seoul Jongno-gu 9", 37.506, 126.906, None, None),
        PlaceCandidate("KAKAO", "local", "Local Cafe", "CE7", "Seoul Jongno-gu 1", 37.5004, 126.9004, None, None),
    ])
    generator.naver_cafe_provider = MixedEvidence()
    generator.route_provider = QualityRoutes()
    proposal = GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
        PlanDraftItem(3, "PLACE", "Next", 104, "11:50", "12:30", "next"),
    ])])

    attached = generator._attach_rest_cafes(
        proposal, {place.place_id: place for place in session.places}, session.trips[1], {"rest_frequency": "HIGH"},
    )

    # A local-business match with NO_RECENT_EVIDENCE confirms identity only;
    # it cannot beat another Kakao-and-route-verified cafe on that fact alone.
    assert attached.days[0].items[1].title == "Local Cafe"


def test_senior_mode_can_select_a_verified_rest_cafe_even_without_rest_preference(service):
    generator, session, _, _ = service
    session.senior_mode = True
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = NaverEvidence()
    generator.route_provider = Routes({"PUBLIC_TRANSIT": RouteEstimate(5 * 60, "PUBLIC_TRANSIT", distance_meters=400)})
    places = {place.place_id: place for place in session.places}
    proposal = GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
    ])])

    attached = generator._attach_rest_cafes(proposal, places, session.trips[1], {"rest_frequency": "LOW"})

    assert attached.days[0].items[1].item_type == "PLACE"


def test_slow_trip_style_can_select_a_verified_rest_cafe_without_high_rest_frequency(service):
    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = NaverEvidence()
    generator.route_provider = Routes({"PUBLIC_TRANSIT": RouteEstimate(5 * 60, "PUBLIC_TRANSIT", distance_meters=400)})
    places = {place.place_id: place for place in session.places}
    proposal = GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
    ])])

    attached = generator._attach_rest_cafes(
        proposal, places, session.trips[1], {"rest_frequency": "LOW", "travel_style": "SLOW"},
    )

    assert attached.days[0].items[1].item_type == "PLACE"


def test_generated_cafe_rest_is_persisted_and_returned_with_place_fields(service):
    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = NaverEvidence()
    generator.route_provider = Routes({"PUBLIC_TRANSIT": RouteEstimate(5 * 60, "PUBLIC_TRANSIT", distance_meters=400)})

    response = generator.generate(1, 1, [101])

    cafe = next(item for item in response.days[0].items if item.name == "Verified Cafe")
    stored = next(item for item in session.items if item.item_id == cafe.item_id)
    assert (stored.item_type, stored.place_id) == ("PLACE", cafe.place_id)
    assert (cafe.address, cafe.latitude, cafe.longitude, cafe.category) == ("Seoul Jongno-gu 1", 37.5005, 126.9005, "CE7")


def test_anchor_address_defines_citywide_destination_not_anchor_district(service):
    generator, session, provider, _ = service
    session.trips[1].destination = "Busan Suyeong-gu"
    session.places = [
        Place(101, "Anchor beach", "AT4", "Busan Suyeong-gu", "Busan Suyeong-gu", 35.15, 129.11, "anchor"),
        Place(104, "City museum", "CT1", "Busan Jung-gu", "Busan Jung-gu", 35.10, 129.03, "city"),
    ]

    generator.generate(1, 1, [101])

    trip_input, _, _, _, _, candidates = provider.calls[0]
    assert trip_input["destination"] == "Busan"
    assert [candidate["place_id"] for candidate in candidates] == [101, 104]


def test_route_facts_change_candidate_selection_by_transport_and_walking_limit(service):
    generator, session, _, module = service
    session.places.extend([
        Place(105, "Broad district", "CT1", "Seoul", "Seoul Mapo-gu", 37.6, 126.8, "wide"),
        Place(106, "Walk-heavy district", "CT1", "Seoul", "Seoul Yongsan-gu", 37.7, 126.7, "walk"),
    ])
    RouteEstimate = __import__("app.services.external.routing.provider", fromlist=["RouteEstimate"]).RouteEstimate
    generator.route_provider = Routes({
        "CAR": RouteEstimate(50 * 60, "CAR"),
        "PUBLIC_TRANSIT": RouteEstimate(50 * 60, "PUBLIC_TRANSIT", walking_seconds=25 * 60, transfer_count=1),
        "WALK": RouteEstimate(30 * 60, "WALK", walking_seconds=30 * 60),
    })
    anchors = [session.places[0]]

    session.trips[1].transport_mode = "CAR"
    car_ids = [place.place_id for place in generator._candidate_places(session.trips[1], anchors, {"walking_tolerance": "VERY_LOW"})]
    session.trips[1].transport_mode = "PUBLIC_TRANSIT"
    transit_ids = [place.place_id for place in generator._candidate_places(session.trips[1], anchors, {"walking_tolerance": "VERY_LOW"})]
    session.trips[1].transport_mode = "WALK"
    walking_ids = [place.place_id for place in generator._candidate_places(session.trips[1], anchors, {"walking_tolerance": "VERY_LOW"})]

    assert {105, 106}.issubset(car_ids)
    assert 105 not in transit_ids and 106 not in transit_ids
    assert 105 not in walking_ids and 106 not in walking_ids


def test_verified_route_time_shifts_impossible_adjacent_visits(service):
    # Task 7.5k: a 45-minute leg after a 10:30 end no longer fails; the next visit moves to 11:15.
    generator, session, provider, _ = service
    RouteEstimate = __import__("app.services.external.routing.provider", fromlist=["RouteEstimate"]).RouteEstimate
    generator.route_provider = Routes({"PUBLIC_TRANSIT": RouteEstimate(45 * 60, "PUBLIC_TRANSIT", walking_seconds=5 * 60, transfer_count=0)})
    provider.draft = draft(101, 104)

    response = generator.generate(1, 1, [101])

    items = response.days[0].items
    assert [(item.place_id, item.start_time, item.end_time) for item in items[:2]] == [(101, time(10), time(10, 30)), (104, time(11, 15), time(11, 45))]
    assert items[1].travel_minutes_from_previous == 45 and items[1].travel_status == "KNOWN"


def test_missing_route_data_does_not_create_route_or_transit_claims(service):
    generator, session, _, _ = service
    generator.route_provider = Routes({})

    generator._candidate_places(session.trips[1], [session.places[0]], {"walking_tolerance": "VERY_LOW"})

    assert generator.route_provider.calls


def test_candidate_pool_reserves_non_food_activity_when_food_candidates_dominate(service):
    generator, session, _, _ = service
    session.trips[1].end_date = date(2026, 10, 13)
    session.places.extend(
        Place(200 + index, f"Meal {index}", "FD6", kakao_place_id=f"meal-{index}")
        for index in range(30)
    )
    session.places.append(Place(300, "Verified activity", "CT1", kakao_place_id="activity"))

    candidates = generator._candidate_places(session.trips[1], [session.places[0]])

    assert {104, 300}.issubset(place.place_id for place in candidates)
    assert len(candidates) == 15


def test_verified_non_food_activities_are_required_even_for_food_focused_plan(service):
    generator, session, _, _ = service
    session.trips[1].end_date = date(2026, 10, 11)
    session.places.extend([
        Place(105, "Restaurant one", "FD6", kakao_place_id="food-1"),
        Place(106, "Restaurant two", "FD6", kakao_place_id="food-2"),
        Place(107, "Verified activity one", "CT1", kakao_place_id="activity-1"),
        Place(108, "Verified activity two", "AT4", kakao_place_id="activity-2"),
    ])
    food_only_days = [
        (date(2026, 10, 10), [(PlanDraftItem(1, "MEAL", "Restaurant one", 105, "10:00", "11:00", "reason"), time(10), time(11))]),
        (date(2026, 10, 11), [(PlanDraftItem(1, "MEAL", "Restaurant two", 106, "10:00", "11:00", "reason"), time(10), time(11))]),
    ]
    candidates = {place.place_id: place for place in session.places}

    with pytest.raises(AppError) as error:
        generator._validate_activity_diversity(food_only_days, candidates, session.trips[1])

    assert error.value.code == "INSUFFICIENT_NON_FOOD_ACTIVITY"


def test_generate_normalizes_application_interests_without_mutating_stored_values(service):
    generator, session, provider, _ = service
    session.interest_codes = ["CAFE", "FOOD", "SEA", "NATURE", "REST", "CITY"]

    generator.generate(1, 1, [101])

    assert session.interest_codes == ["CAFE", "FOOD", "SEA", "NATURE", "REST", "CITY"]
    assert provider.calls[0][3] == ["CAFE", "FOOD", "NATURE"]
    assert provider.calls[0][4] == {"raw_interest_codes": ["SEA", "REST", "CITY"]}


def test_city_only_interest_never_receives_sea_or_nature_weight(service):
    generator, session, provider, _ = service
    session.interest_codes = ["CITY"]
    session.places.extend([
        Place(105, "Beach candidate", "AT4", kakao_place_id="beach"),
        Place(106, "City candidate", "CT1", kakao_place_id="city"),
    ])

    generator.generate(1, 1, [101])

    assert provider.calls[0][3] == []
    assert provider.calls[0][4] == {"raw_interest_codes": ["CITY"]}
    assert [candidate["place_id"] for candidate in provider.calls[0][5]][:3] == [101, 106, 104]


def test_city_only_four_day_flow_repairs_missing_model_dates_and_rest_only_days(service):
    generator, session, provider, _ = service
    session.trips[1].destination = "Busan"
    session.trips[1].start_date = date(2026, 10, 20)
    session.trips[1].end_date = date(2026, 10, 23)
    session.interest_codes = ["CITY"]
    session.places = [
        Place(101, "Selected anchor", "AT4", "Busan", "Busan Suyeong-gu", 35.15, 129.11, "anchor"),
        Place(102, "City museum", "CT1 > Culture", "Busan", "Busan Jung-gu", 35.10, 129.03, "museum"),
        Place(103, "City market", "CT1 > Market", "Busan", "Busan Dong-gu", 35.12, 129.04, "market"),
        Place(104, "Cafe", "CE7 > Cafe", "Busan", "Busan Haeundae-gu", 35.16, 129.16, "cafe"),
        Place(105, "Restaurant", "FD6 > Restaurant", "Busan", "Busan Seo-gu", 35.08, 129.01, "restaurant"),
    ]
    provider.draft = GeneratedPlanDraft([PlanDraftDay(date(2026, 10, 20), [
        PlanDraftItem(1, "PLACE", "wrong", 101, "09:00", "10:00", "reason"),
    ])])

    response = generator.generate(1, 1, [101, 101])

    assert [day.visit_date for day in response.days] == [date(2026, 10, day) for day in range(20, 24)]
    all_items = [item for day in response.days for item in day.items]
    assert [item.place_id for item in all_items if item.place_id is not None].count(101) == 1
    assert len({item.place_id for item in all_items if item.place_id is not None}) == len([item for item in all_items if item.place_id is not None])
    assert any(item.name == "City museum" for item in all_items)
    assert provider.calls[0][3] == []
    assert provider.calls[0][4] == {"raw_interest_codes": ["CITY"]}


def test_sea_only_interest_maps_to_nature_only_when_explicitly_selected(service):
    generator, session, provider, _ = service
    session.interest_codes = ["SEA"]
    session.places.extend([
        Place(105, "Beach candidate", "AT4", kakao_place_id="beach"),
        Place(106, "City candidate", "CT1", kakao_place_id="city"),
    ])

    generator.generate(1, 1, [101])

    assert provider.calls[0][3] == ["NATURE"]
    assert provider.calls[0][4] == {"raw_interest_codes": ["SEA"]}
    assert [candidate["place_id"] for candidate in provider.calls[0][5]][:3] == [101, 105, 104]


@pytest.mark.parametrize("interest_codes", [["FOOD"], []])
def test_unselected_sea_is_absent_from_candidate_and_exaone_input(service, interest_codes):
    generator, session, provider, _ = service
    session.interest_codes = interest_codes

    generator.generate(1, 1, [101])

    assert "SEA" not in provider.calls[0][3]
    assert "NATURE" not in provider.calls[0][3]
    assert provider.calls[0][4]["raw_interest_codes"] == []


def test_selected_ids_are_deduplicated_in_order_and_every_anchor_must_be_included(service):
    generator, session, provider, _ = service
    provider.draft = draft(101, 104)
    generator.generate(1, 1, [101, 101, 104])
    candidates = provider.calls[0][5]
    assert [row["place_id"] for row in candidates[:2]] == [101, 104]
    assert [row["is_anchor"] for row in candidates[:2]] == [True, True]
    assert [place.place_id for place in session.selected_places[1]] == [101, 104]


def test_selected_places_are_kept_independently_for_each_trip(service):
    generator, session, provider, _ = service
    provider.draft = draft(101, 104)
    generator.generate(1, 1, [101, 104])
    provider.draft = draft(104)
    generator.generate(2, 2, [104])
    assert [place.place_id for place in session.selected_places[1]] == [101, 104]
    assert [place.place_id for place in session.selected_places[2]] == [104]


def test_stored_selected_places_are_the_anchor_source_for_later_generation(service):
    generator, session, _, _ = service
    session.selected_places[1] = [session.places[1]]
    _, _, _, _, _, candidates, anchor_ids, _ = generator._input(session.trips[1])
    assert anchor_ids == {104}
    assert candidates[0]["place_id"] == 104
    assert candidates[0]["is_anchor"] is True


def test_missing_or_empty_selected_anchor_is_rejected(service):
    generator, _, provider, _ = service
    with pytest.raises(AppError, match="Selected place") as missing:
        generator.generate(1, 1, [999])
    assert missing.value.code == "PLACE_NOT_FOUND" and provider.calls == []
    assert PlanGenerateRequest(selected_place_ids=[]).selected_place_ids == []
    assert PlanGenerateRequest().selected_place_ids is None


def test_empty_ids_without_destination_are_rejected(service):
    generator, session, provider, _ = service
    for destination in (None, "", "   "):
        session.trips[1].destination = destination
        with pytest.raises(AppError) as empty:
            generator.generate(1, 1, [])
        assert empty.value.code == "PLACE_IDS_REQUIRED"
        assert empty.value.status_code == 422
    assert provider.calls == []


def test_empty_ids_with_destination_generate_from_citywide_candidates(service):
    generator, session, _, _ = service
    session.trips[1].destination = "Busan"
    session.places = [Place(110, "Seoul Palace", "CT1", "Seoul", "Seoul Jongno-gu", 37.57, 126.97, "seoul")]

    class CitywideProvider(NearbyProvider):
        def __init__(self):
            super().__init__()
            self.searches = []

        def search(self, query, region):
            self.searches.append((query, region))
            return [
                PlaceCandidate("KAKAO", f"busan-{len(self.searches)}-{index}", f"Busan {query} {index}", "AT4", f"Busan Haeundae-gu {index}", 35.16, 129.16, None, None)
                for index in range(2)
            ]

    citywide = CitywideProvider()
    generator.place_provider = citywide

    class FirstCandidateProvider(Provider):
        def generate_plan(self, *args):
            self.calls.append(args)
            return draft(args[5][0]["place_id"])

    generator.provider = FirstCandidateProvider(None)

    response = generator.generate(1, 1, [])

    trip_input, _, _, _, _, candidates = generator.provider.calls[0][:6]
    assert trip_input["destination"] == "Busan"
    assert citywide.searches and all(region == "Busan" for _, region in citywide.searches)
    assert citywide.calls == []
    assert candidates and all(row["is_anchor"] is False for row in candidates)
    assert all(row["address"].startswith("Busan") for row in candidates)
    assert 110 not in [row["place_id"] for row in candidates]
    assert len(candidates) <= 15
    assert session.selected_places[1] == []
    assert response.days[0].items[0].place_id == candidates[0]["place_id"]


def test_kakao_is_used_only_when_cached_candidates_are_insufficient(service):
    generator, session, provider, module = service
    session.places = [session.places[0]]
    nearby = NearbyProvider([PlaceCandidate("KAKAO", "nearby", "Nearby Cafe", "CE7", "Seoul Jongno-gu", 37.501, 126.901, None, None)])
    generator.place_provider = nearby
    generator.generate(1, 1, [101])
    assert len(nearby.calls) == 1
    assert any(place.kakao_place_id == "nearby" for place in session.places)
    assert [row["place_id"] for row in provider.calls[0][5]] == [101, 102]


def test_other_region_candidates_are_excluded_before_provider_call(service):
    generator, session, provider, _ = service
    session.places.append(Place(105, "Elsewhere", region="Seoul", address="Busan Suyeong-gu", latitude=37.501, longitude=126.901, kakao_place_id="elsewhere"))
    generator.generate(1, 1, [101])
    assert 105 not in [row["place_id"] for row in provider.calls[0][5]]


def test_candidate_limit_keeps_anchor_and_caps_nearby_candidates(service):
    generator, session, provider, _ = service
    session.places.extend(
        Place(200 + index, f"Nearby {index}", latitude=37.51 + index / 10000, longitude=126.91, kakao_place_id=f"nearby-{index}")
        for index in range(30)
    )
    generator.generate(1, 1, [101])
    candidates = provider.calls[0][5]
    assert len(candidates) == 15 and candidates[0]["place_id"] == 101


def test_kakao_error_allows_generation_when_cached_candidates_are_sufficient(service):
    generator, _, provider, _ = service
    generator.place_provider = NearbyProvider(error=AppError("KAKAO_TIMEOUT", "timeout", 504))
    generator.generate(1, 1, [101])
    assert provider.calls


def test_kakao_error_with_only_anchor_returns_clear_candidate_error(service):
    generator, session, _, _ = service
    session.places = [session.places[0]]
    generator.place_provider = NearbyProvider(error=AppError("KAKAO_TIMEOUT", "timeout", 504))
    with pytest.raises(AppError) as error:
        generator.generate(1, 1, [101])
    assert error.value.code == "INSUFFICIENT_PLACE_CANDIDATES"


def test_missing_anchor_is_repaired_from_verified_anchor_and_unknown_provider_place_is_rejected(service):
    generator, session, provider, _ = service
    provider.draft = draft(104)
    response = generator.generate(1, 1, [101])
    assert [item.place_id for item in response.days[0].items if item.place_id is not None] == [104, 101]
    session.plans.clear()
    provider.draft = draft(999)
    with pytest.raises(AppError) as unknown_place:
        generator.generate(1, 1, [101])
    assert unknown_place.value.code == "AI_SCHEMA_VALIDATION_FAILED"


def test_duplicate_places_are_safely_converted_to_free_time_and_anchor_is_once(service):
    generator, session, provider, _ = service
    provider.draft = draft(101, 101)

    response = generator.generate(1, 1, [101])

    assert [item.place_id for item in response.days[0].items] == [101, None, None]
    assert response.days[0].items[1].item_type == "FREE_TIME"


def test_candidate_data_canonicalizes_titles_and_item_types(service):
    generator, session, provider, _ = service
    session.places[0].name = "광안리해수욕장"
    session.places[0].category = "AT4 관광명소"
    session.places[1].name = "자갈치횟집"
    session.places[1].category = "FD6 음식점"
    provider.draft = GeneratedPlanDraft([PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "MEAL", "부산불꽃축제", 101, "10:00", "10:30", "reason"),
        PlanDraftItem(2, "PLACE", "다른 이름", 104, "11:00", "11:30", "reason"),
    ])])

    response = generator.generate(1, 1, [101])

    assert [(item.name, item.item_type) for item in response.days[0].items] == [
        ("광안리해수욕장", "PLACE"), ("자갈치횟집", "MEAL"),
    ]


@pytest.mark.parametrize("name,category", [
    ("수영구 행정복지센터", "공공기관"),
    ("바다 호텔", "숙박"),
])
def test_automatic_candidates_exclude_administrative_and_accommodation_places(service, name, category):
    generator, session, _, _ = service
    session.places.append(Place(105, name, category, kakao_place_id="blocked"))

    candidates = generator._candidate_places(session.trips[1], [session.places[0]])

    assert 105 not in [place.place_id for place in candidates]


@pytest.mark.parametrize(
    "event_start,event_end,expected",
    [
        (date(2026, 10, 1), date(2026, 10, 5), False),  # before trip
        (date(2026, 11, 7), date(2026, 11, 7), False),  # after trip
        (date(2026, 10, 23), date(2026, 10, 23), True),
        (date(2026, 10, 19), date(2026, 10, 21), True),  # multi-day overlap
    ],
)
def test_event_candidates_require_verified_dates_that_overlap_trip(service, event_start, event_end, expected):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.end_date = date(2026, 10, 23)
    event = Place(105, "부산불꽃축제", "축제", event_start_date=event_start, event_end_date=event_end)
    session.places.append(event)

    candidates = generator._candidate_places(trip, [session.places[0]])

    assert (105 in [place.place_id for place in candidates]) is expected


def test_event_with_unknown_dates_is_excluded_from_automatic_candidates(service):
    generator, session, _, _ = service
    session.places.append(Place(105, "지역 문화축제", "행사"))

    candidates = generator._candidate_places(session.trips[1], [session.places[0]])

    assert 105 not in [place.place_id for place in candidates]


def test_expired_event_candidate_triggers_verified_place_backfill(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.end_date = date(2026, 10, 23)
    session.places = [
        session.places[0],
        Place(105, "부산불꽃축제", "축제", event_start_date=date(2026, 11, 7), event_end_date=date(2026, 11, 7)),
    ]
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "museum", "Nearby Museum", "CT1", "Seoul Jongno-gu", 37.501, 126.901, None, None),
    ])

    candidates = generator._candidate_places(trip, [session.places[0]])

    assert 105 not in [place.place_id for place in candidates]
    assert any(place.name == "Nearby Museum" for place in candidates)


@pytest.mark.parametrize(
    "start,end,expected",
    [("10:00", "11:00", True), ("08:00", "09:00", False)],
)
def test_verified_opening_hours_are_checked_but_unknown_hours_are_not_assumed(service, start, end, expected):
    generator, session, _, _ = service
    place = session.places[0]
    place.opening_hours = {"saturday": {"open": "09:00", "close": "18:00"}}
    place.verification_status = "VERIFIED"
    visit_date = date(2026, 10, 10)  # Saturday
    draft_days = [(visit_date, [(PlanDraftItem(1, "PLACE", place.name, place.place_id, start, end, "reason"), time.fromisoformat(start), time.fromisoformat(end))])]

    if expected:
        generator._validate_temporal_draft(draft_days, {place.place_id: place})
    else:
        with pytest.raises(AppError):
            generator._validate_temporal_draft(draft_days, {place.place_id: place})

    place.verification_status = "UNKNOWN"
    generator._validate_temporal_draft(draft_days, {place.place_id: place})


def test_plan_generation_enforces_existing_trip_ownership_and_state(service):
    generator, _, provider, _ = service
    for user_id, trip_id, code in [(1, 99, "TRIP_NOT_FOUND"), (2, 1, "FORBIDDEN"), (1, 3, "TRIP_ARCHIVED")]:
        with pytest.raises(AppError) as error:
            generator.generate(user_id, trip_id, [101])
        assert error.value.code == code
    assert provider.calls == []


def test_plan_generation_endpoint_requires_the_new_request_shape(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/trips/{trip_id}/plans/generate" in schema["paths"]
    assert client.post("/api/v1/trips/1/plans/generate", json={"selected_place_ids": [101]}).status_code == 401


def test_candidate_pool_reserves_two_activities_per_day_before_food(service):
    generator, session, _, _ = service
    session.trips[1].end_date = date(2026, 10, 12)
    session.places.extend(
        Place(200 + index, f"Meal {index}", "FD6", kakao_place_id=f"meal-{index}")
        for index in range(30)
    )
    session.places.extend(
        Place(300 + index, f"Activity {index}", "CT1", kakao_place_id=f"activity-{index}")
        for index in range(10)
    )

    candidates = generator._candidate_places(session.trips[1], [session.places[0]])

    activities = [place for place in candidates if place.category == "CT1"]
    assert len(activities) >= 6
    assert len(candidates) == 15


def test_food_only_day_swaps_back_to_back_restaurant_for_unused_activity(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.end_date = trip.start_date
    places = {
        105: Place(105, "Restaurant one", "FD6", kakao_place_id="food-1"),
        106: Place(106, "Restaurant two", "FD6", kakao_place_id="food-2"),
        107: Place(107, "Verified activity", "CT1", kakao_place_id="activity-1"),
    }
    draft = GeneratedPlanDraft([PlanDraftDay(trip.start_date, [
        PlanDraftItem(1, "MEAL", "Restaurant one", 105, "11:30", "13:00", "reason"),
        PlanDraftItem(2, "MEAL", "Restaurant two", 106, "14:00", "15:30", "reason"),
    ])])

    repaired = generator._prepare_draft(draft, places, set(), trip)

    assert [item.place_id for item in repaired.days[0].items] == [105, 107]
    assert repaired.days[0].items[1].start_time == "14:00"


def test_model_timeout_leaves_no_plan_and_the_trip_can_be_retried(service):
    generator, session, provider, _ = service
    good_draft = provider.draft

    def timeout(*args):
        provider.calls.append(args)
        raise AppError("OLLAMA_TIMEOUT", "Ollama request timed out", 504)

    provider.generate_plan = timeout
    with pytest.raises(AppError) as error:
        generator.generate(1, 1, [101])

    assert error.value.code == "OLLAMA_TIMEOUT"
    assert session.plans == {}
    assert session.trips[1].status == "DRAFT"

    provider.generate_plan = lambda *args: good_draft
    response = generator.generate(1, 1, [101])
    assert response.plan_id == session.plans[1].plan_id


def _rest_slot_draft():
    return GeneratedPlanDraft(days=[PlanDraftDay(date(2026, 10, 10), [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "11:00", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "11:10", "11:40", "rest"),
    ])])


def test_cafe_next_to_the_previous_stop_is_checked_with_a_walking_route(service):
    # Trip 91: the car route between a beach and the cafe 60 m away is refused
    # (Kakao result 104), so every candidate looked unverified.
    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Verified Cafe", "CE7", "Seoul Jongno-gu 1", 37.5005, 126.9005, None, None),
    ])
    generator.naver_cafe_provider = NaverEvidence()
    generator.route_provider = Routes({"WALK": RouteEstimate(85, "WALK", distance_meters=92)})
    places = {place.place_id: place for place in session.places}

    attached = generator._attach_rest_cafes(_rest_slot_draft(), places, session.trips[1], {"rest_frequency": "HIGH"})

    cafe = attached.days[0].items[1]
    assert (cafe.item_type, cafe.title, cafe.start_time, cafe.end_time) == ("PLACE", "Verified Cafe", "11:10", "11:40")
    assert any(call[-1] == "WALK" for call in generator.route_provider.calls)


def test_a_far_cafe_is_never_confirmed_by_a_walking_route(service):
    generator, session, _, _ = service
    generator.place_provider = NearbyProvider([
        PlaceCandidate("KAKAO", "rest-cafe", "Far Cafe", "CE7", "Seoul Jongno-gu 1", 37.5100, 126.9100, None, None),
    ])
    generator.naver_cafe_provider = NaverEvidence()
    generator.route_provider = Routes({"WALK": RouteEstimate(900, "WALK", distance_meters=1400)})
    places = {place.place_id: place for place in session.places}

    attached = generator._attach_rest_cafes(_rest_slot_draft(), places, session.trips[1], {"rest_frequency": "HIGH"})

    rest = attached.days[0].items[1]
    assert (rest.item_type, rest.place_id, rest.title) == ("REST", None, "자유 휴식")
    assert "자유 휴식 시간" in rest.recommendation_reason
    assert not any(call[-1] == "WALK" for call in generator.route_provider.calls)
