"""Trip 89 (2026-10-28): 함덕 09:00-13:00, REST 13:00-14:00, 올레 1코스 14:30.

The SLOW REST is protected, so the only lunch path is _recover_lunch_from_rest.
It pinned lunch to end right before the next visit and required that end to be
inside the lunch window (14:00).  With the next visit at 14:30, every
restaurant less than 30 minutes from it was rejected and the plan failed with
MISSING_LUNCH.  Meal windows apply to a meal's start everywhere else.
"""

import logging
from datetime import date

from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.cached_provider import CachedRouteProvider
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_quality_rules import PlanQualityRules
from tests.unit.test_plan_generation_service import Place, service  # noqa: F401  (pytest fixture)

DAY = date(2026, 10, 28)  # Wednesday
TRIP = type("Trip", (), {"transport_mode": "CAR", "trip_id": 89})()
SLOW = {"travel_style": "SLOW"}

HAMDEOK = Place(600, "함덕해수욕장", category="여행 > 관광,명소 > 해수욕장,해변", latitude=33.543, longitude=126.669)
OLLE = Place(592, "올레길 1코스", category="여행 > 관광,명소 > 도보여행", latitude=33.479, longitude=126.906)
LUNCH = Place(612, "식당", category="음식점 > 한식", latitude=33.50, longitude=126.80)


class Roads:
    def __init__(self, minutes=15):
        self.minutes = minutes

    def route(self, *_args):
        return None if self.minutes is None else RouteEstimate(self.minutes * 60, "CAR")


def day(first_end="13:00", rest=("13:00", "14:00"), next_start="14:30", first_start="09:00"):
    return GeneratedPlanDraft([PlanDraftDay(DAY, [
        PlanDraftItem(1, "PLACE", HAMDEOK.name, 600, first_start, first_end, "r"),
        PlanDraftItem(2, "REST", "휴식", None, rest[0], rest[1], "r"),
        PlanDraftItem(3, "PLACE", OLLE.name, 592, next_start, "16:30", "r"),
    ])])


def recover(generator, plan, roads=None, anchors=(), lunch=LUNCH):
    generator.route_provider = CachedRouteProvider(roads or Roads())
    generator._quality_rules = PlanQualityRules()
    places = {p.place_id: p for p in (HAMDEOK, OLLE, lunch)}
    generator._recover_lunch_from_rest(plan, places, set(anchors), {600, 592}, TRIP, SLOW, 0)
    return [(item.item_type, item.place_id, item.start_time, item.end_time) for item in plan.days[0].items]


def test_trip89_lunch_is_recovered_and_the_rest_keeps_its_hour(service):
    generator, *_ = service
    assert recover(generator, day()) == [
        ("PLACE", 600, "09:00", "12:00"),
        ("REST", None, "12:00", "13:00"),
        ("MEAL", 612, "13:15", "14:15"),
        ("PLACE", 592, "14:30", "16:30"),
    ]


def test_a_lunch_that_would_start_after_the_window_moves_to_its_last_start(service):
    generator, *_ = service
    assert recover(generator, day(next_start="15:30")) == [
        ("PLACE", 600, "09:00", "12:45"),
        ("REST", None, "12:45", "13:45"),
        ("MEAL", 612, "14:00", "15:00"),
        ("PLACE", 592, "15:30", "16:30"),
    ]


def test_an_anchor_before_the_rest_is_never_shortened(service, caplog):
    generator, *_ = service
    plan = day()
    before = list(plan.days[0].items)
    with caplog.at_level(logging.INFO):
        recover(generator, plan, anchors={600})
    assert plan.days[0].items == before
    assert any("reason=PREVIOUS_VISIT_FIXED" in record.getMessage() for record in caplog.records)


def test_unknown_travel_time_is_never_guessed(service, caplog):
    generator, *_ = service
    plan = day()
    before = list(plan.days[0].items)
    with caplog.at_level(logging.INFO):
        recover(generator, plan, roads=Roads(minutes=None))
    assert plan.days[0].items == before
    assert any("reason=NO_FEASIBLE_RESTAURANT" in r.getMessage() and "ROUTE_UNKNOWN" in r.getMessage() for r in caplog.records)


def test_a_restaurant_closed_at_lunch_is_not_used(service, caplog):
    generator, *_ = service
    closed = Place(612, "식당", category="음식점 > 한식", latitude=33.50, longitude=126.80,
                   opening_hours={"wednesday": {"open": "17:00", "close": "22:00"}}, verification_status="VERIFIED")
    plan = day()
    before = list(plan.days[0].items)
    with caplog.at_level(logging.INFO):
        recover(generator, plan, lunch=closed)
    assert plan.days[0].items == before
    assert any("CLOSED" in record.getMessage() for record in caplog.records)


def test_a_visit_that_would_drop_below_an_hour_keeps_the_day_unchanged(service, caplog):
    generator, *_ = service
    plan = day(first_start="10:30", first_end="12:30", rest=("12:30", "14:30"))
    before = list(plan.days[0].items)
    with caplog.at_level(logging.INFO):
        recover(generator, plan)
    assert plan.days[0].items == before
    assert any("PREVIOUS_VISIT_TOO_SHORT" in record.getMessage() for record in caplog.records)
