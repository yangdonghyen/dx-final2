"""Initial-generation repair of verified travel-time conflicts (trip 81 422).

Real case: EXAONE put lunch at 13:30 (the end of the lunch window) right after
a 12:00-13:00 REST; the verified 35-minute drive pushed it to 13:35 and the
whole generation failed with ROUTE_TIME_CONFLICT.
"""

from datetime import date, time

import pytest

from app.core.exceptions import AppError
from app.services.external.ai.provider import PlanDraftItem
from app.services.external.routing.cached_provider import CachedRouteProvider
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_quality_rules import PlanQualityRules
from tests.unit.test_plan_generation_service import Place, Provider, draft, service  # noqa: F401  (pytest fixture)

DAY = date(2026, 10, 27)
TRIP = type("Trip", (), {"transport_mode": "CAR"})()


def place(place_id, name, category="관광명소"):
    # Each place gets its own coordinates so routes can be looked up per pair.
    return Place(place_id, name, category=category, latitude=35.0 + place_id / 1000, longitude=129.0)


SIGHT_A, SIGHT_B, SIGHT_C = place(1, "해운대해수욕장"), place(2, "송정해수욕장"), place(3, "감천문화마을")
MEAL, NEAR_MEAL, FAR_MEAL = place(10, "신선식당", "음식점 > 한식"), place(11, "가까운식당", "음식점 > 한식"), place(12, "먼식당", "음식점 > 한식")
PLACES = {p.place_id: p for p in (SIGHT_A, SIGHT_B, SIGHT_C, MEAL, NEAR_MEAL, FAR_MEAL)}


class Routes:
    """Verified seconds per directed place pair; anything else has no route fact."""

    def __init__(self, minutes):
        self.minutes = minutes
        self.requests = []

    def route(self, lat1, lon1, lat2, lon2, _mode):
        ids = {(p.latitude, p.longitude): p.place_id for p in PLACES.values()}
        key = (ids[(lat1, lon1)], ids[(lat2, lon2)])
        self.requests.append(key)
        minutes = self.minutes.get(key)
        return None if minutes is None else RouteEstimate(minutes * 60, "CAR")


def row(sequence, item_type, place_id, start, end):
    title = PLACES[place_id].name if place_id else ("휴식" if item_type == "REST" else "자유 시간")
    return PlanDraftItem(sequence, item_type, title, place_id, start, end, "r"), time.fromisoformat(start), time.fromisoformat(end)


def trip81_day():
    """The rows that reached the travel shift for 2026-10-27 in the real run."""
    return [
        row(1, "PLACE", 1, "09:00", "12:00"),
        row(2, "REST", None, "12:00", "13:00"),
        row(3, "MEAL", 10, "13:30", "15:00"),
        row(4, "PLACE", 2, "15:30", "17:30"),
        row(5, "PLACE", 3, "17:30", "19:30"),
    ]


def hhmm(rows):
    return [(item.place_id, start.strftime("%H:%M"), end.strftime("%H:%M")) for item, start, end in rows]


# The repair scenarios below were written against the strict 11:30-13:30 /
# 17:30-19:30 meal windows, so they pin those windows explicitly.  The shift
# now uses the meal windows the rules are configured with (see
# test_route_time_meal_windows.py for the default 11:00-14:00 / 17:00-20:00).
STRICT_RULES = PlanQualityRules.from_windows("07:00-09:30", "11:30-13:30", "17:30-19:30")


def adjust(generator, routes, rows, anchors=(), preferences=None, repair=True, rules=STRICT_RULES):
    generator.route_provider = routes
    generator._quality_rules = rules
    return generator._adjust_route_timing([(DAY, rows)], dict(PLACES), TRIP, set(anchors), preferences or {}, repair=repair)[0][1]


# Routes for the trip-81 day: sight A -> lunch 35 min, later legs fit.
BASE = {(1, 10): 35, (10, 2): 25, (2, 3): 50, (1, 2): 20, (2, 10): 30, (10, 1): 35, (1, 3): 60, (3, 10): 40, (10, 3): 40}


def test_trip81_conflict_still_fails_without_repair_for_preview_callers(service):
    generator, *_ = service
    with pytest.raises(AppError) as error:
        adjust(generator, Routes(BASE), trip81_day(), repair=False)
    assert error.value.code == "ROUTE_TIME_CONFLICT" and "신선식당" in error.value.message


def test_trimming_rest_keeps_lunch_in_window_with_full_verified_travel(service):
    generator, *_ = service
    # No reorder helps (swapping A with B/C would lengthen the day's drive).
    routes = Routes({**BASE, (2, 10): 90, (3, 10): 90, (10, 1): 90})
    fixed = adjust(generator, routes, trip81_day())

    rest, meal = fixed[1], fixed[2]
    assert meal[1] <= time(13, 30)  # inside the lunch window
    # The verified 35-minute drive is fully kept after the shortened rest.
    assert (meal[1].hour * 60 + meal[1].minute) - (rest[2].hour * 60 + rest[2].minute) >= 35
    assert hhmm(fixed)[0] == (1, "09:00", "12:00")  # the sight before is untouched
    assert generator.last_route_time_repairs[0]["strategy"] == "TRIM"


def test_rest_keeps_a_real_break_for_slow_travellers(service):
    generator, *_ = service
    routes = Routes({**BASE, (1, 10): 70, (2, 10): 200, (3, 10): 200, (10, 1): 200})
    fixed = adjust(generator, routes, trip81_day(), preferences={"travel_style": "SLOW"})

    rest = fixed[1]
    assert (rest[2].hour * 60 + rest[2].minute) - (rest[1].hour * 60 + rest[1].minute) >= 30
    meal = fixed[2]
    assert meal[1] <= time(13, 30)


def test_reorder_resolves_conflict_only_when_day_travel_does_not_grow(service):
    generator, *_ = service
    # Lunch is far from A but close to B; B<->A swap also shortens the day.
    routes = Routes({(1, 10): 95, (2, 10): 20, (10, 1): 20, (1, 3): 30, (2, 3): 70, (10, 2): 25, (3, 10): 60, (10, 3): 60})
    rows = [
        row(1, "PLACE", 2, "09:00", "12:00"),
        row(2, "MEAL", 10, "12:30", "13:30"),
        row(3, "PLACE", 1, "14:00", "15:30"),
        row(4, "PLACE", 3, "16:00", "17:30"),
    ]
    rows[0] = row(1, "PLACE", 1, "09:00", "12:00")
    rows[2] = row(3, "PLACE", 2, "14:00", "15:30")
    fixed = adjust(generator, routes, rows)

    assert generator.last_route_time_repairs[0]["strategy"] == "REORDER"
    assert [item.place_id for item, _, _ in fixed] == [2, 10, 1, 3]
    assert fixed[1][1] <= time(13, 30)


def test_restaurant_is_replaced_by_a_verified_one_that_fits(service):
    generator, *_ = service
    routes = Routes({(1, 10): 120, (1, 11): 20, (11, 2): 25, (10, 2): 25, (2, 3): 50, (1, 2): 200, (2, 1): 200, (3, 1): 200, (1, 3): 200})
    fixed = adjust(generator, routes, trip81_day(), preferences={"travel_style": "SLOW"})

    assert fixed[2][0].place_id == 11 and fixed[2][0].title == "가까운식당"
    assert fixed[2][1] <= time(13, 30)
    assert generator.last_route_time_repairs[0]["strategy"] == "REPLACE_RESTAURANT"


def test_replacement_without_a_route_fact_is_never_treated_as_fitting(service):
    generator, *_ = service
    # The alternatives have no verified legs (provider failure / unknown).
    routes = Routes({(1, 10): 120, (10, 2): 25, (2, 3): 50, (1, 2): 200, (2, 1): 200, (3, 1): 200, (1, 3): 200})
    with pytest.raises(AppError) as error:
        adjust(generator, routes, trip81_day(), anchors={1, 2, 3}, preferences={"travel_style": "SLOW"})
    assert error.value.code == "ROUTE_TIME_CONFLICT" and error.value.status_code == 422
    assert "REPLACE_RESTAURANT" in error.value.details["tried"]
    assert not generator.last_route_time_repairs


def test_all_alternatives_failing_returns_actionable_details(service):
    generator, *_ = service
    routes = Routes({(1, 10): 180, (1, 11): 180, (1, 12): 180, (10, 2): 25, (11, 2): 25, (12, 2): 25, (2, 3): 50,
                     (1, 2): 200, (2, 1): 200, (3, 1): 200, (1, 3): 200})
    with pytest.raises(AppError) as error:
        adjust(generator, routes, trip81_day(), anchors={1, 2, 3}, preferences={"travel_style": "SLOW"})

    details = error.value.details
    assert details["visit_date"] == "2026-10-27" and details["conflict"] == "MEAL_WINDOW"
    assert details["place_name"] == "신선식당"
    assert details["tried"] == "REORDER,TRIM,REPLACE_RESTAURANT,DROP_OPTIONAL"


def test_anchor_is_never_dropped_shortened_or_moved(service):
    generator, *_ = service
    routes = Routes({(1, 10): 180, (10, 2): 25, (2, 3): 50, (1, 2): 200, (2, 1): 200, (3, 1): 200, (1, 3): 200})
    rows = trip81_day()
    with pytest.raises(AppError):
        adjust(generator, routes, rows, anchors={1}, preferences={"travel_style": "SLOW"})
    assert hhmm(rows)[0] == (1, "09:00", "12:00")


def test_optional_sight_is_dropped_only_as_last_resort(service):
    generator, *_ = service
    rows = [
        row(1, "PLACE", 3, "09:00", "10:00"),
        row(2, "PLACE", 1, "10:30", "12:30"),
        row(3, "MEAL", 10, "13:00", "14:00"),
        row(4, "PLACE", 2, "14:30", "16:00"),
    ]
    routes = Routes({(3, 1): 30, (1, 10): 100, (3, 10): 20, (10, 2): 25, (1, 2): 200, (2, 1): 200, (3, 2): 200, (2, 3): 200})
    fixed = adjust(generator, routes, rows, anchors={3, 2})

    assert generator.last_route_time_repairs[0]["strategy"] == "DROP_OPTIONAL"
    assert [item.place_id for item, _, _ in fixed] == [3, 10, 2]


def test_trimming_never_shortens_travel_or_leaves_useless_gaps(service):
    generator, *_ = service
    rows = [
        row(1, "PLACE", 3, "09:00", "11:00"),   # earlier sight: trimming it cannot help
        row(2, "PLACE", 1, "11:00", "12:00"),
        row(3, "FREE_TIME", None, "12:00", "12:40"),
        row(4, "MEAL", 10, "13:20", "14:20"),
    ]
    routes = Routes({(1, 10): 60, (3, 10): 200, (10, 3): 200, (1, 3): 200})
    fixed = adjust(generator, routes, rows, anchors={1})

    assert hhmm(fixed)[0] == (3, "09:00", "11:00")
    free, meal = fixed[2], fixed[3]
    assert (meal[1].hour * 60 + meal[1].minute) - (free[2].hour * 60 + free[2].minute) >= 60
    assert meal[1] <= time(13, 30)


def test_day_without_conflict_is_returned_unchanged(service):
    generator, *_ = service
    rows = [row(1, "PLACE", 1, "09:00", "11:00"), row(2, "MEAL", 10, "12:00", "13:00"), row(3, "PLACE", 2, "14:00", "15:00")]
    assert adjust(generator, Routes({(1, 10): 30, (10, 2): 30}), rows) == rows
    assert generator.last_route_time_repairs == []


def test_failed_generation_persists_no_plan(service):
    generator, session, provider, module = service

    class Far:
        def route(self, *_args):
            return RouteEstimate(11 * 3600 + 40 * 60, "PUBLIC_TRANSIT", walking_seconds=60, transfer_count=0)

    generator.route_provider = Far()
    generator.provider = Provider(draft(101, 104))  # two places -> one verified leg
    # Keep the far candidate so the conflict reaches the route-timing repair
    # (the real mobility filter would already exclude it).
    generator._mobility_candidates = lambda candidates, *_args: candidates
    with pytest.raises(AppError) as error:
        generator.generate(1, 1, [101])
    assert error.value.code == "ROUTE_TIME_CONFLICT" and error.value.status_code == 422
    assert session.plans == {} and session.items == []


def test_rest_cafe_checks_keep_their_own_route_allowance():
    class Inner:
        def __init__(self): self.calls = 0
        def route(self, *_args):
            self.calls += 1
            return RouteEstimate(600, "CAR")

    cached = CachedRouteProvider(Inner(), max_calls=40, max_candidate_calls=2)
    with cached.candidate_phase():
        assert cached.route(1, 1, 2, 2, "CAR") and cached.route(1, 1, 3, 3, "CAR")
        assert cached.route(1, 1, 4, 4, "CAR") is None  # candidate cap reached
        with cached.limited_phase(2):
            assert cached.route(1, 1, 5, 5, "CAR") and cached.route(1, 1, 6, 6, "CAR")
            assert cached.route(1, 1, 7, 7, "CAR") is None  # cafe allowance reached
    assert cached.denied == 2 and cached.calls == 4 and cached.candidate_calls == 2
