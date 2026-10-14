"""Trip 85 (2026-10-27~29): last-day MISSING_LUNCH turned into HTTP 500.

Real run: the meal-route comparison budget (16 candidate calls) was already
used when 2026-10-29's lunch was filled, so no candidate was measured
(``verified=0``) and the lunch stayed missing.  The 422 that followed carried
``details={"codes": ["MISSING_LUNCH"]}``, which ErrorDetail rejected, so the
client got a 500 instead of the intended MEAL_SCHEDULE_INCOMPLETE.
"""

import logging
from datetime import date

from fastapi.testclient import TestClient

from app.api.v1.plans import get_service
from app.core.config import Settings
from app.core.exceptions import AppError
from app.dependencies import get_current_user
from app.main import create_app
from app.schemas.common import ErrorDetail
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.cached_provider import CachedRouteProvider
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_quality_rules import PlanQualityRules
from tests.unit.test_plan_generation_service import Place, service  # noqa: F401  (pytest fixture)

DAY = date(2026, 10, 29)
TRIP = type("Trip", (), {"transport_mode": "CAR", "trip_id": 85})()

# Morning and afternoon sights about 20 km apart, as on the real last day.
MORNING = Place(1, "기장 해동용궁사", category="관광명소", latitude=35.188, longitude=129.223)
AFTERNOON = Place(2, "감천문화마을", category="관광명소", latitude=35.097, longitude=129.011)
NEAR, MIDDLE, FAR = (
    Place(10, "가까운식당", category="음식점 > 한식", latitude=35.180, longitude=129.200),
    Place(11, "중간식당", category="음식점 > 한식", latitude=35.150, longitude=129.120),
    Place(12, "먼식당", category="음식점 > 한식", latitude=35.300, longitude=129.400),
)
PLACES = {p.place_id: p for p in (MORNING, AFTERNOON, NEAR, MIDDLE, FAR)}


class Inner:
    def __init__(self, seconds=900):
        self.seconds, self.calls = seconds, 0

    def route(self, *_args):
        self.calls += 1
        return None if self.seconds is None else RouteEstimate(self.seconds, "CAR")


def last_day():
    return GeneratedPlanDraft([PlanDraftDay(DAY, [
        PlanDraftItem(1, "PLACE", MORNING.name, 1, "09:00", "11:30", "r"),
        PlanDraftItem(2, "FREE_TIME", "자유 시간", None, "12:00", "13:00", "r"),
        PlanDraftItem(3, "PLACE", AFTERNOON.name, 2, "14:00", "16:00", "r"),
    ])])


def spent_routes(inner):
    """A request whose candidate budget was used by earlier days, as in trip 85."""
    routes = CachedRouteProvider(inner, max_calls=40, max_candidate_calls=16)
    routes.calls = routes.candidate_calls = 16
    return routes


def fill(generator, routes, start=8):
    generator.route_provider = routes
    generator._quality_rules = PlanQualityRules()
    plan = last_day()
    generator._repair_missing_meals(plan, dict(PLACES), set(), [], {1, 2}, TRIP, {}, meal_route_start=start)
    return plan.days[0].items


def test_trip85_last_day_lunch_is_measured_from_the_reserve_when_the_budget_is_spent(service, caplog):
    generator, *_ = service
    inner = Inner()
    with caplog.at_level(logging.INFO):
        items = fill(generator, spent_routes(inner))
    lunch = items[1]
    assert (lunch.item_type, lunch.start_time, lunch.end_time) == ("MEAL", "12:00", "13:00")
    assert lunch.place_id in {10, 11}  # one of the two nearest, never the far one
    assert inner.calls <= 4  # two candidates x two legs at most
    assert any("selection=verified_route_reserve" in record.getMessage() for record in caplog.records)


def test_reserve_never_accepts_a_restaurant_without_a_verified_route(service):
    generator, *_ = service
    items = fill(generator, spent_routes(Inner(seconds=None)))
    assert items[1].item_type == "FREE_TIME" and items[1].place_id is None  # final check still reports it


def test_reserve_is_not_used_while_the_comparison_budget_lasts(service, caplog):
    generator, *_ = service
    routes = CachedRouteProvider(Inner(), max_calls=40, max_candidate_calls=16)
    with caplog.at_level(logging.INFO):
        items = fill(generator, routes, start=0)
    assert items[1].item_type == "MEAL"
    assert routes.candidate_calls > 0
    assert any("selection=verified_route " in record.getMessage() for record in caplog.records)


def test_error_detail_accepts_finding_code_lists_and_keeps_scalar_details():
    assert ErrorDetail(code="X", message="m", details={"codes": ["MISSING_LUNCH"]}).details == {"codes": ["MISSING_LUNCH"]}
    assert ErrorDetail(code="X", message="m", details={"plan_id": 7, "visit_date": "2026-10-29"}).details == {
        "plan_id": 7, "visit_date": "2026-10-29",
    }


def test_generate_api_returns_the_intended_422_with_meal_codes():
    app = create_app(Settings(_env_file=None))

    class Failing:
        def generate(self, *_args):
            raise AppError(
                "MEAL_SCHEDULE_INCOMPLETE",
                "Required meal slots could not be scheduled safely with verified restaurant candidates",
                422,
                {"codes": ["MISSING_LUNCH"]},
            )

    app.dependency_overrides[get_service] = Failing
    app.dependency_overrides[get_current_user] = lambda: type("User", (), {"user_id": 7})()
    with TestClient(app) as client:
        response = client.post("/api/v1/trips/85/plans/generate", json={"selected_place_ids": []})
    assert response.status_code == 422
    assert response.json() == {"error": {
        "code": "MEAL_SCHEDULE_INCOMPLETE",
        "message": "Required meal slots could not be scheduled safely with verified restaurant candidates",
        "details": {"codes": ["MISSING_LUNCH"]},
    }}


def test_generate_api_saves_a_validated_plan_through_the_real_service(service):
    """POST -> PlanGenerationService (generate, validate, save) on the fake session."""
    generator, session, _, _ = service
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_service] = lambda: generator
    app.dependency_overrides[get_current_user] = lambda: type("User", (), {"user_id": 1})()
    with TestClient(app) as client:
        response = client.post("/api/v1/trips/1/plans/generate", json={"selected_place_ids": [101]})
    assert response.status_code == 200, response.json()
    assert response.json()["days"] and session.commits == 1


def test_reserve_is_skipped_when_it_would_starve_itinerary_validation(service):
    generator, *_ = service
    inner = Inner()
    routes = CachedRouteProvider(inner, max_calls=20, max_candidate_calls=16)
    routes.calls = routes.candidate_calls = 16  # 4 left: 2 reserve candidates x 2 legs + 1 leg > 4
    items = fill(generator, routes)
    assert items[1].item_type == "FREE_TIME" and inner.calls == 0
