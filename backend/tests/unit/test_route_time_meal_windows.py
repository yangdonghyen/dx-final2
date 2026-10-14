"""Verified travel vs meal windows (trip 82, 2026-10-27 ROUTE_TIME_CONFLICT).

Real case: the missing-lunch repair filled a 13:30 slot (inside the 11:00-14:00
lunch rule) after a 12:00-13:00 cafe.  The travel shift checked its own fixed
11:30-13:30 window, so any drive longer than 30 minutes rejected a lunch the
meal rules and the final meal check accept.  Shortening a visit also never
moved the stops after it earlier, so time freed before the cafe was wasted.
"""

import logging
from dataclasses import replace
from datetime import date, time, timedelta

import pytest

from app.core.exceptions import AppError
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.cached_provider import CachedRouteProvider
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_quality_rules import PlanQualityRules
from tests.unit.test_plan_generation_service import Place, Provider, draft, service  # noqa: F401  (pytest fixture)

DAY = date(2026, 10, 27)  # a Tuesday
TRIP = type("Trip", (), {"transport_mode": "CAR", "trip_id": 82})()
TUESDAY_FROM_NOON = {"tuesday": {"open": "12:00", "close": "18:00"}}


def place(place_id, name, category="관광명소", hours=None):
    return Place(
        place_id, name, category=category, latitude=35.0 + place_id / 1000, longitude=129.0,
        opening_hours=hours, verification_status="VERIFIED" if hours else "UNKNOWN",
    )


HAEUNDAE, SONGJEONG, GAMCHEON = place(1, "해운대해수욕장"), place(2, "송정해수욕장"), place(3, "감천문화마을")
NOON_MUSEUM = place(4, "정오개관박물관", hours=TUESDAY_FROM_NOON)
CAFE = place(20, "홉슈크림", "음식점 > 카페")
SINSEON, NEAR_MEAL = place(10, "신선식당", "음식점 > 한식"), place(11, "가까운식당", "음식점 > 한식")
PLACES = {p.place_id: p for p in (HAEUNDAE, SONGJEONG, GAMCHEON, NOON_MUSEUM, CAFE, SINSEON, NEAR_MEAL)}


class Routes:
    """Verified minutes per directed place pair; anything else has no route fact."""

    def __init__(self, minutes):
        self.minutes = minutes

    def route(self, lat1, lon1, lat2, lon2, _mode):
        ids = {(p.latitude, p.longitude): p.place_id for p in PLACES.values()}
        minutes = self.minutes.get((ids[(lat1, lon1)], ids[(lat2, lon2)]))
        return None if minutes is None else RouteEstimate(minutes * 60, "CAR")


def row(sequence, item_type, place_id, start, end):
    title = PLACES[place_id].name if place_id else "휴식"
    return PlanDraftItem(sequence, item_type, title, place_id, start, end, "r"), time.fromisoformat(start), time.fromisoformat(end)


def hhmm(rows):
    return [(item.place_id, start.strftime("%H:%M"), end.strftime("%H:%M")) for item, start, end in rows]


DEFAULT_RULES = PlanQualityRules()  # lunch 11:00-14:00, dinner 17:00-20:00
STRICT_RULES = PlanQualityRules.from_windows("07:00-09:30", "11:30-13:30", "17:30-19:30")


def adjust_days(generator, routes, days, anchors=(), preferences=None, repair=True, rules=DEFAULT_RULES):
    generator.route_provider = routes
    generator._quality_rules = rules
    return generator._adjust_route_timing(days, dict(PLACES), TRIP, set(anchors), preferences or {}, repair=repair)


def adjust(generator, routes, rows, **kwargs):
    return adjust_days(generator, routes, [(DAY, rows)], **kwargs)[0][1]


def trip82_day():
    """The 2026-10-27 rows that reached the travel shift in the real run."""
    return [
        row(1, "PLACE", 1, "09:00", "12:00"),
        row(2, "PLACE", 20, "12:00", "13:00"),
        row(3, "MEAL", 10, "13:30", "15:00"),
        row(4, "PLACE", 2, "15:30", "17:30"),
    ]


TRIP82_ROUTES = {(20, 10): 40, (10, 2): 25}  # sight -> cafe has no route fact


def test_trip82_lunch_after_verified_travel_stays_inside_the_configured_window(service):
    generator, *_ = service
    fixed = adjust(generator, Routes(TRIP82_ROUTES), trip82_day())
    # 13:00 + 40 min drive = 13:40, inside lunch 11:00-14:00; later stops follow.
    assert hhmm(fixed) == [(1, "09:00", "12:00"), (20, "12:00", "13:00"), (10, "13:40", "15:10"), (2, "15:35", "17:35")]


def test_lunch_pushed_past_the_window_is_repaired_by_trimming_the_cafe(service):
    generator, *_ = service
    fixed = adjust(generator, Routes(TRIP82_ROUTES), trip82_day(), rules=STRICT_RULES)
    # Strict 13:30 limit: the cafe gives 10 minutes (keeps >= 40), lunch starts 13:30.
    assert hhmm(fixed)[1:3] == [(20, "12:00", "12:50"), (10, "13:30", "15:00")]


def test_dinner_pushed_past_the_window_is_repaired_and_later_times_recomputed(service):
    generator, *_ = service
    rows = [
        row(1, "PLACE", 2, "14:00", "17:00"),
        row(2, "PLACE", 3, "17:00", "19:00"),
        row(3, "MEAL", 10, "19:30", "20:30"),
    ]
    fixed = adjust(generator, Routes({(2, 3): 0, (3, 10): 70}), rows)
    # 19:00 + 70 = 20:10 > 20:00: the sight before dinner gives 10 minutes.
    assert hhmm(fixed) == [(2, "14:00", "17:00"), (3, "17:00", "18:50"), (10, "20:00", "21:00")]


def test_shortening_an_earlier_visit_moves_the_stops_after_it_earlier(service):
    generator, *_ = service
    rows = [
        row(1, "PLACE", 1, "09:00", "12:00"),
        row(2, "PLACE", 20, "12:00", "12:40"),  # cafe already at its 40-minute floor
        row(3, "MEAL", 10, "13:00", "14:00"),
    ]
    fixed = adjust(generator, Routes({(20, 10): 90}), rows)
    # 12:40 + 90 = 14:10.  Only the sight can give time; the cafe moves with it.
    assert hhmm(fixed) == [(1, "09:00", "11:50"), (20, "11:50", "12:30"), (10, "14:00", "15:00")]


def test_compaction_never_moves_a_stop_before_its_verified_opening(service):
    generator, *_ = service
    rows = [
        row(1, "PLACE", 1, "09:00", "12:00"),
        row(2, "PLACE", 4, "12:00", "13:00"),  # opens 12:00 on Tuesdays
        row(3, "MEAL", 10, "13:30", "14:30"),
    ]
    fixed = adjust(generator, Routes({(1, 4): 0, (4, 10): 70, (1, 10): 20}), rows)
    assert all(not (item.place_id == 4 and start < time(12, 0)) for item, start, _ in fixed)
    meal = next((start, end) for item, start, end in fixed if item.item_type == "MEAL")
    assert time(11, 0) <= meal[0] <= time(14, 0)


def test_anchor_is_never_moved_earlier_or_shortened(service):
    generator, *_ = service
    rows = [
        row(1, "PLACE", 1, "09:00", "12:00"),
        row(2, "PLACE", 3, "12:00", "13:00"),
        row(3, "MEAL", 10, "13:30", "14:30"),
    ]
    routes = Routes({(1, 3): 0, (3, 10): 70, (3, 11): 20, (1, 11): 30})
    fixed = adjust(generator, routes, rows, anchors={3})
    assert (3, "12:00", "13:00") in hhmm(fixed)
    meal = next((item.place_id, start) for item, start, _ in fixed if item.item_type == "MEAL")
    assert meal == (11, time(13, 30))  # the nearer verified restaurant fits instead


def test_unrecoverable_conflict_returns_422_with_structured_log(service, caplog):
    generator, *_ = service
    rows = [
        row(1, "PLACE", 1, "09:00", "12:00"),
        row(2, "PLACE", 2, "12:00", "13:00"),
        row(3, "MEAL", 10, "13:30", "15:00"),
    ]
    with caplog.at_level(logging.INFO), pytest.raises(AppError) as error:
        adjust(generator, Routes({(1, 2): 0, (2, 10): 120}), rows, anchors={1, 2}, preferences={"travel_style": "SLOW"})
    assert error.value.code == "ROUTE_TIME_CONFLICT"
    assert error.value.details["conflict"] == "MEAL_WINDOW" and error.value.details["visit_date"] == "2026-10-27"
    failed = next(record.getMessage() for record in caplog.records if "route_time_repair_failed" in record.getMessage())
    for fact in ("'place_id': 10", "'original_start': '13:30'", "'travel_minutes': 120",
                 "'computed_arrival': '15:00'", "'meal_window': '11:00-14:00'", "'overflow_minutes': 60"):
        assert fact in failed


def test_preview_callers_still_reject_without_repair(service):
    generator, *_ = service
    with pytest.raises(AppError) as error:
        adjust(generator, Routes({**TRIP82_ROUTES, (20, 10): 70}), trip82_day(), repair=False)
    assert error.value.code == "ROUTE_TIME_CONFLICT"


def test_three_day_trip_repairs_only_the_conflicting_day(service):
    generator, *_ = service
    days = [(DAY + timedelta(days=offset), trip82_day()) for offset in range(3)]
    routes = Routes({(20, 10): 20, (10, 2): 25})
    plain = adjust_days(generator, routes, days)
    assert all(hhmm(rows) == hhmm(trip82_day()) for _, rows in plain)
    days[1] = (days[1][0], [replace_row(r, 10, "13:50") if r[0].place_id == 10 else r for r in trip82_day()])
    fixed = adjust_days(generator, Routes({(20, 10): 70, (10, 2): 25}), days)
    assert [visit_date for visit_date, _ in fixed] == [day for day, _ in days]
    for _, rows in fixed:
        meal = next(start for item, start, _ in rows if item.item_type == "MEAL")
        assert time(11, 0) <= meal <= time(14, 0)


def replace_row(day_row, _place_id, start):
    item, old_start, old_end = day_row
    length = (old_end.hour * 60 + old_end.minute) - (old_start.hour * 60 + old_start.minute)
    new_start = time.fromisoformat(start)
    end_minutes = new_start.hour * 60 + new_start.minute + length
    new_end = time(end_minutes // 60, end_minutes % 60)
    return replace(item, start_time=start, end_time=new_end.strftime("%H:%M")), new_start, new_end


def test_day_running_into_dinner_without_a_slot_gets_a_verified_restaurant(service):
    generator, *_ = service
    generator.route_provider = Routes({(2, 10): 10, (2, 11): 25})
    generator._quality_rules = DEFAULT_RULES
    plan = GeneratedPlanDraft([PlanDraftDay(DAY, [
        PlanDraftItem(1, "PLACE", "해운대해수욕장", 1, "09:00", "12:00", "r"),
        PlanDraftItem(2, "MEAL", "신선식당", 11, "12:00", "13:00", "r"),
        PlanDraftItem(3, "PLACE", "송정해수욕장", 2, "15:30", "17:30", "r"),
    ])])
    used = {1, 2, 11}
    generator._repair_missing_meals(plan, dict(PLACES), set(), [], used, TRIP, {})
    dinner = plan.days[0].items[-1]
    assert (dinner.sequence, dinner.item_type, dinner.place_id, dinner.start_time, dinner.end_time) == (4, "MEAL", 10, "17:30", "18:30")


def dinner_day(last_place=2):
    return GeneratedPlanDraft([PlanDraftDay(DAY, [
        PlanDraftItem(1, "PLACE", "해운대해수욕장", 1, "09:00", "12:00", "r"),
        PlanDraftItem(2, "PLACE", PLACES[last_place].name, last_place, "15:30", "17:30", "r"),
    ])])


def test_without_a_restaurant_the_last_sight_ends_as_dinner_opens(service):
    generator, *_ = service
    generator.route_provider = Routes({})  # no verified route for any restaurant
    generator._quality_rules = DEFAULT_RULES
    plan = dinner_day()
    generator._repair_missing_meals(plan, dict(PLACES), set(), [], {1, 2}, TRIP, {})
    assert [(item.place_id, item.start_time, item.end_time) for item in plan.days[0].items] == [
        (1, "09:00", "12:00"), (2, "15:30", "17:00"),
    ]


def test_an_anchor_at_the_end_of_the_day_is_never_shortened(service):
    generator, *_ = service
    generator.route_provider = Routes({})
    generator._quality_rules = DEFAULT_RULES
    plan = dinner_day()
    before = list(plan.days[0].items)
    generator._repair_missing_meals(plan, dict(PLACES), {2}, [], {1, 2}, TRIP, {})
    assert plan.days[0].items == before  # the final meal check still rejects it


def test_exhausted_route_budget_measures_the_nearest_restaurant_from_the_reserve(service):
    generator, *_ = service
    calls = []
    inner = type("Inner", (), {"route": lambda self, *args: calls.append(args) or RouteEstimate(600, "CAR")})()
    generator.route_provider = CachedRouteProvider(inner, max_candidate_calls=16)
    generator.route_provider.calls = generator.route_provider.candidate_calls = 16  # spent by earlier steps
    generator._quality_rules = DEFAULT_RULES
    plan = dinner_day()
    generator._repair_missing_meals(plan, dict(PLACES), set(), [], {1, 2}, TRIP, {}, meal_route_start=8)
    dinner = plan.days[0].items[-1]
    assert (dinner.item_type, dinner.place_id, dinner.start_time) == ("MEAL", 10, "17:30")
    assert 1 <= len(calls) <= 2  # verified, one leg per measured candidate
