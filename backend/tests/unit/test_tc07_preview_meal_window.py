"""TC-07: plan 36 preview failed with ROUTE_TIME_CONFLICT (MEAL_WINDOW).

Real log: lunch at 14:00 on 10/26 would only be reached at 15:37 (97 minutes
over the window).  The preview called the travel shift without repair, so no
verified alternative was tried and every such draft became a 422.
"""

from datetime import date

import pytest

from app.core.exceptions import AppError
from app.schemas.plan import PlanRegenerateRequest
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_quality_rules import PlanQualityRules
from tests.unit.test_plan_generation_service import Place, service as generation_service  # noqa: F401  (fixture)
from tests.unit.test_plan_regeneration_preview_service import service as preview_service

DAY = date(2026, 1, 1)
MUSEUM = Place(1, "Museum", category="여행 > 관광,명소", latitude=37.50, longitude=127.00)
GALLERY = Place(2, "Gallery", category="여행 > 관광,명소", latitude=37.60, longitude=127.10)
FAR_MEAL = Place(3, "Far Restaurant", category="음식점 > 한식", latitude=38.20, longitude=127.80)
NEAR_MEAL = Place(4, "Near Restaurant", category="음식점 > 한식", latitude=37.51, longitude=127.01)
PLACES = {p.place_id: p for p in (MUSEUM, GALLERY, FAR_MEAL, NEAR_MEAL)}
WEATHER = PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Move indoors")


class Roads:
    def __init__(self, minutes):
        self.minutes = minutes

    def route(self, lat1, lon1, lat2, lon2, _mode):
        ids = {(p.latitude, p.longitude): p.place_id for p in PLACES.values()}
        value = self.minutes.get((ids[(lat1, lon1)], ids[(lat2, lon2)]))
        return None if value is None else RouteEstimate(value * 60, "CAR")


def preview_with_real_repair(generator, minutes, places=PLACES):
    svc, plan, trip, items, _, saved, _, draft = preview_service()
    trip.transport_mode = "CAR"
    draft.days[0] = PlanDraftDay(DAY, [
        PlanDraftItem(1, "PLACE", "Museum", 1, "10:00", "12:30", "kept"),
        PlanDraftItem(2, "MEAL", "Far Restaurant", 3, "14:00", "15:00", "lunch"),
    ])
    generator.route_provider = Roads(minutes)
    generator._quality_rules = PlanQualityRules()
    base_input = svc.generation._input
    svc.generation._input = lambda trip: (*base_input(trip)[:7], dict(places))
    svc.generation._adjust_route_timing = generator._adjust_route_timing
    return svc, plan, items, saved


def test_preview_repairs_a_meal_pushed_97_minutes_past_its_window(generation_service):
    generator, *_ = generation_service
    # Museum -> far restaurant 187 min: 12:30 + 187 = 15:37, 97 min after 14:00.
    svc, plan, items, saved = preview_with_real_repair(generator, {(1, 3): 187, (1, 4): 20})

    response = svc.create(1, 10, WEATHER)

    assert response.status == "PENDING"
    lunch = [row for row in saved[0]["proposed_itinerary"]["items"] if row["item_type"] == "MEAL"]
    assert [(row["place_id"], row["start_time"]) for row in lunch] == [(4, "14:00:00")]
    museum = next(row for row in saved[0]["proposed_itinerary"]["items"] if row["place_id"] == 1)
    assert museum["start_time"] == "10:00:00"  # the anchor keeps its slot
    assert plan.current_version == 4 and len(items) == 2  # nothing applied before approval


def test_preview_without_a_verified_fix_keeps_the_422_and_saves_nothing(generation_service):
    generator, *_ = generation_service
    places = {key: value for key, value in PLACES.items() if key != 4}
    svc, plan, items, saved = preview_with_real_repair(generator, {(1, 3): 187}, places)

    with pytest.raises(AppError) as error:
        svc.create(1, 10, WEATHER)

    assert error.value.code == "ROUTE_TIME_CONFLICT" and error.value.status_code == 422
    assert error.value.details["conflict"] == "MEAL_WINDOW"
    assert saved == [] and plan.current_version == 4 and len(items) == 2


def test_preview_passes_the_trip_preferences_to_meal_repair():
    svc, plan, _, items, _, saved, _, _ = preview_service()
    seen = []
    base_input = svc.generation._input
    svc.generation._input = lambda trip: (base_input(trip)[0], {"travel_style": "SLOW"}, *base_input(trip)[2:])
    svc.generation._prepare_draft = lambda value, places, anchors, trip, preferences=None: seen.append(preferences) or value
    svc.create(1, 10, WEATHER)
    assert seen == [{"travel_style": "SLOW"}]
    assert plan.current_version == 4 and len(items) == 2 and len(saved) == 1


def test_preview_keeps_places_of_the_stored_itinerary_as_candidates():
    """Plan 36: rest cafes and a recovered lunch were not in the rebuilt pool."""
    from types import SimpleNamespace
    from app.services.plan_regeneration_preview_service import with_current_places

    cafe = SimpleNamespace(place_id=876, name="Cafe", category="음식점 > 카페", region="제주", address="제주",
                           latitude=33.5, longitude=126.6, opening_hours=None, verification_status="UNKNOWN")
    no_coordinates = SimpleNamespace(place_id=877, name="Lost", category="음식점 > 카페", region="제주", address="제주",
                                     latitude=None, longitude=None, opening_hours=None, verification_status="UNKNOWN")
    generation = SimpleNamespace(places=SimpleNamespace(get={876: cafe, 877: no_coordinates}.get))
    trip = SimpleNamespace(start_date=DAY, end_date=DAY)
    current = [{"place_id": 1}, {"place_id": 876}, {"place_id": 877}, {"place_id": 999}, {"place_id": None}]

    candidates, places = with_current_places(generation, current, [{"place_id": 1}], {1: MUSEUM}, {1}, trip)

    assert set(places) == {1, 876}  # only a stored place with coordinates is added
    assert [row["place_id"] for row in candidates] == [1, 876] and candidates[1]["is_anchor"] is False


def test_identical_weather_proposal_is_reported_not_saved():
    """TC-08 real run (plan 38): every item came back UNCHANGED for rain."""
    svc, plan, _, items, _, saved, _, draft = preview_service()
    draft.days[0] = PlanDraftDay(DAY, [
        PlanDraftItem(1, "PLACE", "Museum", 1, "10:00", "11:00", "kept"),
        PlanDraftItem(2, "REST", "Rest", None, "12:00", "12:30", "kept"),
    ])
    for reason, code in [("WEATHER_CHANGE", "WEATHER_NO_ALTERNATIVE")]:
        with pytest.raises(AppError) as error:
            svc.create(1, 10, PlanRegenerateRequest(reason=reason, instruction="Move indoors"))
        assert error.value.code == code and error.value.status_code == 422
    assert saved == [] and plan.current_version == 4 and len(items) == 2


def test_weather_previews_add_verified_indoor_places_and_others_do_not():
    """Rain/heat (trip 107): the pool had beaches and parks only."""
    from types import SimpleNamespace
    from app.services.plan_regeneration_preview_service import with_indoor_places
    from app.services.plan_generation_service import PlanGenerationService

    museum = SimpleNamespace(place_id=900, name="참소리축음기에디슨박물관", category="여행 > 관광,명소 > 박물관", region="강릉", address="강릉",
                             latitude=37.79, longitude=128.9, opening_hours=None, verification_status="UNKNOWN")
    asked = []
    generation = SimpleNamespace(indoor_candidates=lambda trip, existing: asked.append(set(existing)) or [museum])
    beach = SimpleNamespace(place_id=1, name="정동진 해변", category="여행 > 관광,명소 > 해수욕장,해변")
    gallery = SimpleNamespace(place_id=2, name="하슬라아트월드", category="여행 > 관광,명소 > 미술관")
    candidates, places = with_indoor_places(generation, [{"place_id": 1}, {"place_id": 2}], {1: beach, 2: gallery}, {1}, SimpleNamespace())

    assert asked == [{1, 2}]
    assert [(row["place_id"], row.get("indoor")) for row in candidates] == [(1, None), (2, True), (900, True)]
    assert set(places) == {1, 2, 900}
    assert PlanGenerationService.is_indoor(museum) and not PlanGenerationService.is_indoor(beach)


def test_only_weather_previews_search_indoor_places():
    svc, plan, _, items, _, saved, received, _ = preview_service()
    asked = []
    svc.generation.indoor_candidates = lambda trip, existing: asked.append(1) or []
    svc.create(1, 10, PlanRegenerateRequest(reason="USER_FATIGUE", instruction="Less walking", feedback_codes=["rest"]))
    assert asked == []
    svc.create(1, 10, WEATHER)
    assert asked == [1]
