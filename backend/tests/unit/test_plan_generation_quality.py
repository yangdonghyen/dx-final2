"""Candidate balance and restaurant-slot repair in plan generation (mock model)."""

import logging
from datetime import time

import pytest

from app.core.exceptions import AppError
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.place.provider import PlaceCandidate
from app.services.external.routing.cached_provider import CachedRouteProvider
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_quality_rules import DayStop, PlanQualityRules, review_plan
from tests.unit.test_plan_generation_service import NearbyProvider, Place, service  # noqa: F401  (fixture)


def restaurant(place_id, name, address=None):
    return Place(place_id, name, "음식점 > 한식", address=address or f"Seoul Jongno-gu {place_id}", kakao_place_id=f"food-{place_id}")


def sight(place_id, name):
    return Place(place_id, name, "여행 > 관광,명소", address=f"Seoul Jongno-gu {place_id}", kakao_place_id=f"sight-{place_id}")


def day(trip, *items):
    return GeneratedPlanDraft([PlanDraftDay(trip.start_date, list(items))])


def test_restaurant_at_10am_is_swapped_for_an_unused_sight_in_the_same_slot(service, caplog):
    generator, session, _, _ = service
    trip = session.trips[1]
    places = {105: restaurant(105, "교촌치킨"), 106: restaurant(106, "점심 식당"), 107: sight(107, "고궁")}
    draft = day(trip,
                PlanDraftItem(1, "MEAL", "교촌치킨", 105, "10:00", "11:00", "model"),
                PlanDraftItem(2, "MEAL", "점심 식당", 106, "12:00", "13:00", "model"))

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        repaired = generator._prepare_draft(draft, places, set(), trip)

    first, second = repaired.days[0].items
    assert (first.place_id, first.item_type, first.start_time) == (107, "PLACE", "10:00")
    assert (second.place_id, second.item_type) == (106, "MEAL")
    assert "plan_draft_repaired" in caplog.text and "MEAL_OUTSIDE_WINDOW" in caplog.text
    assert "model_place_id=105 server_place_id=107" in caplog.text


def test_second_lunch_becomes_free_time_when_no_sight_is_left(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    places = {105: restaurant(105, "국수"), 106: restaurant(106, "김밥"), 107: sight(107, "고궁")}
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "고궁", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "MEAL", "국수", 105, "11:30", "12:30", "model"),
                PlanDraftItem(3, "MEAL", "김밥", 106, "13:00", "14:00", "model"))

    items = generator._prepare_draft(draft, places, set(), trip).days[0].items

    assert [(item.item_type, item.place_id) for item in items] == [("PLACE", 107), ("MEAL", 105), ("FREE_TIME", None)]


def test_off_hours_meal_without_alternative_is_kept_for_validation_to_warn(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    places = {105: restaurant(105, "국수"), 107: sight(107, "고궁")}
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "고궁", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "MEAL", "국수", 105, "15:00", "16:00", "model"))

    items = generator._prepare_draft(draft, places, set(), trip).days[0].items

    assert [(item.item_type, item.place_id, item.start_time) for item in items] == [("PLACE", 107, "09:00"), ("MEAL", 105, "15:00")]


def test_restaurant_just_before_dinner_is_shifted_into_the_real_dinner_window(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    museum, dinner = sight(107, "Museum"), restaurant(105, "Dinner")
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Museum", 107, "13:42", "16:12", "model"),
                PlanDraftItem(2, "MEAL", "Dinner", 105, "16:42", "18:12", "model"))

    items = generator._prepare_draft(draft, {107: museum, 105: dinner}, set(), trip).days[0].items

    assert (items[1].item_type, items[1].place_id, items[1].start_time, items[1].end_time) == (
        "MEAL", 105, "17:00", "18:30",
    )


def test_off_window_restaurant_is_not_shifted_when_the_delay_is_not_bounded(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    museum, dinner = sight(107, "Museum"), restaurant(105, "Dinner")
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Museum", 107, "12:00", "14:00", "model"),
                PlanDraftItem(2, "MEAL", "Dinner", 105, "16:00", "17:00", "model"))

    items = generator._prepare_draft(draft, {107: museum, 105: dinner}, set(), trip).days[0].items

    assert (items[1].start_time, items[1].end_time) == ("16:00", "17:00")


def test_selected_anchor_restaurant_is_never_replaced(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    places = {105: restaurant(105, "꼭 갈 식당"), 107: sight(107, "고궁")}
    draft = day(trip, PlanDraftItem(1, "MEAL", "꼭 갈 식당", 105, "16:00", "17:00", "model"))

    items = generator._prepare_draft(draft, places, {105}, trip).days[0].items

    assert items[0].place_id == 105


def test_meals_at_meal_times_are_left_alone(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    places = {105: restaurant(105, "국수"), 106: restaurant(106, "저녁 식당"), 107: sight(107, "고궁"), 108: sight(108, "공원")}
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "고궁", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "MEAL", "국수", 105, "12:00", "13:00", "model"),
                PlanDraftItem(3, "PLACE", "공원", 108, "14:00", "16:00", "model"),
                PlanDraftItem(4, "MEAL", "저녁 식당", 106, "18:00", "19:00", "model"))

    items = generator._prepare_draft(draft, places, set(), trip).days[0].items

    assert [item.place_id for item in items] == [107, 105, 108, 106]


def test_unanchored_cafe_is_limited_to_a_normal_rest_visit(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    cafe = Place(104, "Cafe", category="CE7", kakao_place_id="cafe")
    places = {107: sight(107, "Museum"), 104: cafe}
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Museum", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "PLACE", "Cafe", 104, "18:10", "19:40", "model"))

    items = generator._prepare_draft(draft, places, set(), trip).days[0].items

    assert (items[1].item_type, items[1].start_time, items[1].end_time) == ("PLACE", "18:10", "19:10")


def test_anchor_cafe_duration_is_not_changed_without_a_stay_preference(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    cafe = Place(104, "Cafe", category="CE7", kakao_place_id="cafe")
    draft = day(trip, PlanDraftItem(1, "PLACE", "Cafe", 104, "14:00", "15:30", "model"))

    item = generator._prepare_draft(draft, {104: cafe}, {104}, trip).days[0].items[0]

    assert (item.item_type, item.start_time, item.end_time) == ("PLACE", "14:00", "15:30")


def test_dinner_time_cafe_is_replaced_only_when_an_unused_restaurant_exists(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    cafe = Place(104, "Cafe", category="CE7", kakao_place_id="cafe")
    places = {107: sight(107, "Museum"), 104: cafe, 105: restaurant(105, "Dinner")}
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Museum", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "PLACE", "Cafe", 104, "18:10", "19:40", "model"))

    items = generator._prepare_draft(draft, places, set(), trip).days[0].items

    assert (items[1].item_type, items[1].place_id, items[1].start_time) == ("MEAL", 105, "18:10")


def test_dinner_time_cafe_stays_a_cafe_and_missing_dinner_is_reported_when_supply_is_short(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    cafe = Place(104, "Cafe", category="CE7", kakao_place_id="cafe")
    lunch = restaurant(105, "Lunch")
    places = {107: sight(107, "Museum"), 104: cafe, 105: lunch}
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Museum", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "MEAL", "Lunch", 105, "12:00", "13:00", "model"),
                PlanDraftItem(3, "PLACE", "Cafe", 104, "18:10", "19:40", "model"))

    prepared = generator._prepare_draft(draft, places, set(), trip)
    cafe_item = prepared.days[0].items[2]
    findings = generator._quality_findings(prepared, places)

    assert (cafe_item.item_type, cafe_item.end_time) == ("PLACE", "19:10")
    assert "MISSING_DINNER" in [finding.code for finding in findings]


def test_early_finish_does_not_require_dinner():
    museum = Place(107, "Museum")
    day_stops = [DayStop(1, "PLACE", time(9), time(16), museum)]

    assert "MISSING_DINNER" not in [finding.code for finding in review_plan([("day", day_stops)], PlanQualityRules())]


def test_seventeen_nineteen_finish_does_not_overreport_missing_dinner():
    museum = Place(107, "Museum")
    day_stops = [DayStop(1, "PLACE", time(9), time(17, 19), museum)]

    assert "MISSING_DINNER" not in [finding.code for finding in review_plan([("day", day_stops)], PlanQualityRules())]


def test_evening_schedule_with_room_for_a_meal_reports_missing_dinner():
    museum = Place(107, "Museum")
    day_stops = [DayStop(1, "PLACE", time(9), time(18), museum)]

    assert "MISSING_DINNER" in [finding.code for finding in review_plan([("day", day_stops)], PlanQualityRules())]


def test_missing_required_lunch_is_reported_without_blocking_the_plan(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    museum = sight(107, "Museum")
    rows = [
        (PlanDraftItem(1, "PLACE", "Museum", 107, "09:00", "12:00", "model"), time(9), time(12)),
        (PlanDraftItem(2, "REST", "Rest", None, "12:00", "13:00", "model"), time(12), time(13)),
    ]

    codes = generator._require_complete_meal_schedule([(trip.start_date, rows)], {107: museum})

    assert codes == ["MISSING_LUNCH"]
    assert rows[1][0].item_type == "REST"  # the rest is never relabelled as a meal


def test_short_day_does_not_block_for_a_meal_that_is_not_required(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    museum = sight(107, "Museum")
    rows = [(PlanDraftItem(1, "PLACE", "Museum", 107, "09:00", "10:00", "model"), time(9), time(10))]

    generator._require_complete_meal_schedule([(trip.start_date, rows)], {107: museum})


def test_slow_trip_does_not_replace_its_only_rest_with_lunch(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    before, after, lunch = sight(107, "Before"), sight(108, "After"), restaurant(105, "Lunch")
    before.latitude, before.longitude = 37.0, 127.0
    after.latitude, after.longitude = 37.2, 127.2
    lunch.latitude, lunch.longitude = 37.1, 127.1
    generator.route_provider = CachedRouteProvider(RouteMap({
        (37.0, 127.0, 37.1, 127.1, "CAR"): 180,
        (37.1, 127.1, 37.2, 127.2, "CAR"): 180,
    }), max_calls=40, max_candidate_calls=16)
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Before", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "REST", "Rest", None, "12:00", "13:00", "model"),
                PlanDraftItem(3, "PLACE", "After", 108, "14:00", "15:00", "model"))

    prepared = generator._prepare_draft(
        draft, {107: before, 108: after, 105: lunch}, set(), trip, {"travel_style": "SLOW"},
    )

    assert prepared.days[0].items[1].item_type == "REST"


class RouteMap:
    def __init__(self, seconds):
        self.seconds = seconds
        self.calls = []

    def route(self, origin_latitude, origin_longitude, destination_latitude, destination_longitude, mode):
        key = (origin_latitude, origin_longitude, destination_latitude, destination_longitude, mode)
        self.calls.append(key)
        seconds = self.seconds.get(key)
        return RouteEstimate(seconds, mode, distance_meters=100) if seconds else None


def _slow_rest_gap_draft(trip):
    return day(trip,
               PlanDraftItem(1, "PLACE", "Before", 107, "09:00", "12:00", "model"),
               PlanDraftItem(2, "REST", "Rest", None, "12:00", "13:00", "model"),
               PlanDraftItem(3, "PLACE", "After", 108, "13:42", "16:12", "model"),
               PlanDraftItem(4, "MEAL", "Dinner", 109, "16:42", "18:12", "model"))


def _slow_rest_gap_places():
    before, after = sight(107, "Before"), sight(108, "After")
    lunch, dinner = restaurant(105, "Lunch"), restaurant(109, "Dinner")
    for place, latitude, longitude in (
        (before, 37.0, 127.0), (lunch, 37.1, 127.1),
        (after, 37.2, 127.2), (dinner, 37.3, 127.3),
    ):
        place.latitude, place.longitude = latitude, longitude
    return {107: before, 108: after, 105: lunch, 109: dinner}


def test_slow_rest_gap_recovers_lunch_with_verified_routes_and_preserves_rest(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    places = _slow_rest_gap_places()
    generator.route_provider = CachedRouteProvider(RouteMap({
        (37.0, 127.0, 37.1, 127.1, "CAR"): 900,
        (37.1, 127.1, 37.2, 127.2, "CAR"): 720,
    }), max_calls=40, max_candidate_calls=16)

    prepared = generator._prepare_draft(
        _slow_rest_gap_draft(trip), places, set(), trip, {"travel_style": "SLOW"},
    )

    assert [(item.item_type, item.place_id, item.start_time, item.end_time) for item in prepared.days[0].items] == [
        ("PLACE", 107, "09:00", "11:15"),
        ("REST", None, "11:15", "12:15"),
        ("MEAL", 105, "12:30", "13:30"),
        ("PLACE", 108, "13:42", "16:12"),
        ("MEAL", 109, "17:00", "18:30"),
    ]
    assert generator.route_provider.candidate_calls <= 8
    assert generator.route_provider.calls <= 40


def test_slow_rest_gap_keeps_incomplete_schedule_when_a_route_fact_is_unknown(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    places = _slow_rest_gap_places()
    generator.route_provider = CachedRouteProvider(RouteMap({
        (37.0, 127.0, 37.1, 127.1, "CAR"): 900,
    }), max_calls=40, max_candidate_calls=16)

    prepared = generator._prepare_draft(
        _slow_rest_gap_draft(trip), places, set(), trip, {"travel_style": "SLOW"},
    )
    rows = [(item, time.fromisoformat(item.start_time), time.fromisoformat(item.end_time)) for item in prepared.days[0].items]

    assert all(item.place_id != 105 for item in prepared.days[0].items)
    assert generator._require_complete_meal_schedule([(trip.start_date, rows)], places) == ["MISSING_LUNCH"]


def test_slow_rest_gap_does_not_use_a_restaurant_closed_for_recovered_lunch(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    places = _slow_rest_gap_places()
    places[105].verification_status = "VERIFIED"
    places[105].opening_hours = {"saturday": {"open": "09:00", "close": "12:00"}}
    generator.route_provider = CachedRouteProvider(RouteMap({
        (37.0, 127.0, 37.1, 127.1, "CAR"): 900,
        (37.1, 127.1, 37.2, 127.2, "CAR"): 720,
    }), max_calls=40, max_candidate_calls=16)

    prepared = generator._prepare_draft(
        _slow_rest_gap_draft(trip), places, set(), trip, {"travel_style": "SLOW"},
    )

    assert all(item.place_id != 105 for item in prepared.days[0].items)
    assert (prepared.days[0].items[1].item_type, prepared.days[0].items[1].start_time) == ("REST", "12:00")


def test_slow_rest_gap_does_not_shorten_an_anchor_to_insert_lunch(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    places = _slow_rest_gap_places()
    generator.route_provider = CachedRouteProvider(RouteMap({
        (37.0, 127.0, 37.1, 127.1, "CAR"): 900,
        (37.1, 127.1, 37.2, 127.2, "CAR"): 720,
    }), max_calls=40, max_candidate_calls=16)

    prepared = generator._prepare_draft(
        _slow_rest_gap_draft(trip), places, {107}, trip, {"travel_style": "SLOW"},
    )

    assert all(item.place_id != 105 for item in prepared.days[0].items)
    assert prepared.days[0].items[0].end_time == "12:00"


def test_complete_slow_schedule_is_not_changed_by_rest_gap_recovery(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    places = _slow_rest_gap_places()
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Before", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "MEAL", "Lunch", 105, "12:00", "13:00", "model"),
                PlanDraftItem(3, "REST", "Rest", None, "13:00", "14:00", "model"),
                PlanDraftItem(4, "PLACE", "After", 108, "14:30", "16:00", "model"))

    prepared = generator._prepare_draft(draft, places, set(), trip, {"travel_style": "SLOW"})

    assert [(item.item_type, item.place_id, item.start_time, item.end_time) for item in prepared.days[0].items] == [
        ("PLACE", 107, "09:00", "11:00"),
        ("MEAL", 105, "12:00", "13:00"),
        ("REST", None, "13:00", "14:00"),
        ("PLACE", 108, "14:30", "16:00"),
    ]


def test_missing_lunch_uses_verified_previous_and_next_route_time_not_candidate_order(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    before, after = sight(107, "Before"), sight(108, "After")
    before.latitude, before.longitude = 37.0, 127.0
    after.latitude, after.longitude = 37.2, 127.2
    near_but_slow, route_better = restaurant(105, "Near but slow"), restaurant(106, "Route better")
    near_but_slow.latitude, near_but_slow.longitude = 37.01, 127.01
    route_better.latitude, route_better.longitude = 37.10, 127.10
    seconds = {
        (37.0, 127.0, 37.01, 127.01, "CAR"): 1_200,
        (37.01, 127.01, 37.2, 127.2, "CAR"): 1_200,
        (37.0, 127.0, 37.10, 127.10, "CAR"): 180,
        (37.10, 127.10, 37.2, 127.2, "CAR"): 180,
    }
    routes = RouteMap(seconds)
    generator.route_provider = CachedRouteProvider(routes, max_calls=40, max_candidate_calls=16)
    places = {107: before, 108: after, 105: near_but_slow, 106: route_better}
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Before", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "FREE_TIME", "Free", None, "12:00", "13:00", "model"),
                PlanDraftItem(3, "PLACE", "After", 108, "14:00", "15:00", "model"))

    prepared = generator._prepare_draft(draft, places, set(), trip)

    assert (prepared.days[0].items[1].item_type, prepared.days[0].items[1].place_id) == ("MEAL", 106)
    assert generator.route_provider.candidate_calls == 4
    assert generator.route_provider.calls <= 40


def test_missing_lunch_does_not_insert_an_unverified_restaurant_when_route_budget_has_no_fact(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    before, after, lunch = sight(107, "Before"), sight(108, "After"), restaurant(105, "Lunch")
    before.latitude, before.longitude = 37.0, 127.0
    after.latitude, after.longitude = 37.2, 127.2
    lunch.latitude, lunch.longitude = 37.1, 127.1
    generator.route_provider = CachedRouteProvider(RouteMap({}), max_calls=40, max_candidate_calls=16)
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Before", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "FREE_TIME", "Free", None, "12:00", "13:00", "model"),
                PlanDraftItem(3, "PLACE", "After", 108, "14:00", "15:00", "model"))

    prepared = generator._prepare_draft(draft, {107: before, 108: after, 105: lunch}, set(), trip)

    assert prepared.days[0].items[1].item_type == "FREE_TIME"


def test_missing_lunch_does_not_spend_the_reserved_candidate_route_budget(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    before, after, lunch = sight(107, "Before"), sight(108, "After"), restaurant(105, "Lunch")
    before.latitude, before.longitude = 37.0, 127.0
    after.latitude, after.longitude = 37.2, 127.2
    lunch.latitude, lunch.longitude = 37.1, 127.1
    routes = RouteMap({
        (37.0, 127.0, 37.1, 127.1, "CAR"): 180,
        (37.1, 127.1, 37.2, 127.2, "CAR"): 180,
    })
    generator.route_provider = CachedRouteProvider(routes, max_calls=40, max_candidate_calls=0)
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Before", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "FREE_TIME", "Free", None, "12:00", "13:00", "model"),
                PlanDraftItem(3, "PLACE", "After", 108, "14:00", "15:00", "model"))

    prepared = generator._prepare_draft(draft, {107: before, 108: after, 105: lunch}, set(), trip)

    assert prepared.days[0].items[1].item_type == "FREE_TIME"
    assert generator.route_provider.calls == 0
    assert generator.route_provider.candidate_calls == 0


def test_missing_lunch_route_budget_is_shared_by_two_travel_days(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    trip.end_date = trip.start_date.replace(day=trip.start_date.day + 1)
    first_before, first_after = sight(101, "First before"), sight(102, "First after")
    second_before, second_after = sight(103, "Second before"), sight(104, "Second after")
    first_lunch, second_lunch = restaurant(105, "First lunch"), restaurant(106, "Second lunch")
    for place, latitude, longitude in (
        (first_before, 37.0, 127.0), (first_after, 37.2, 127.2), (first_lunch, 37.1, 127.1),
        (second_before, 38.0, 128.0), (second_after, 38.2, 128.2), (second_lunch, 38.1, 128.1),
    ):
        place.latitude, place.longitude = latitude, longitude
    generator.route_provider = CachedRouteProvider(RouteMap({
        (37.0, 127.0, 37.1, 127.1, "CAR"): 180,
        (37.1, 127.1, 37.2, 127.2, "CAR"): 180,
        (38.0, 128.0, 38.1, 128.1, "CAR"): 180,
        (38.1, 128.1, 38.2, 128.2, "CAR"): 180,
    }), max_calls=40, max_candidate_calls=16)
    draft = GeneratedPlanDraft([
        PlanDraftDay(trip.start_date, [
            PlanDraftItem(1, "PLACE", "First before", 101, "09:00", "11:00", "model"),
            PlanDraftItem(2, "REST", "Rest", None, "12:00", "13:00", "model"),
            PlanDraftItem(3, "PLACE", "First after", 102, "14:00", "15:00", "model"),
        ]),
        PlanDraftDay(trip.end_date, [
            PlanDraftItem(1, "PLACE", "Second before", 103, "09:00", "11:00", "model"),
            PlanDraftItem(2, "REST", "Rest", None, "12:00", "13:00", "model"),
            PlanDraftItem(3, "PLACE", "Second after", 104, "14:00", "15:00", "model"),
        ]),
    ])
    places = {101: first_before, 102: first_after, 103: second_before, 104: second_after, 105: first_lunch, 106: second_lunch}

    prepared = generator._prepare_draft(draft, places, set(), trip)

    assert [prepared.days[0].items[1].place_id, prepared.days[1].items[1].place_id] == [105, 106]
    assert generator.route_provider.candidate_calls <= 8
    assert generator.route_provider.calls <= 40


def test_missing_lunch_skips_a_near_restaurant_when_verified_hours_exclude_the_slot(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.transport_mode = "CAR"
    before, after = sight(107, "Before"), sight(108, "After")
    closed, open_lunch = restaurant(105, "Closed at lunch"), restaurant(106, "Open lunch")
    before.latitude, before.longitude = 37.0, 127.0
    after.latitude, after.longitude = 37.2, 127.2
    closed.latitude, closed.longitude = 37.01, 127.01
    open_lunch.latitude, open_lunch.longitude = 37.10, 127.10
    closed.verification_status = "VERIFIED"
    closed.opening_hours = {"saturday": {"open": "09:00", "close": "11:30"}}
    generator.route_provider = CachedRouteProvider(RouteMap({
        (37.0, 127.0, 37.10, 127.10, "CAR"): 180,
        (37.10, 127.10, 37.2, 127.2, "CAR"): 180,
    }), max_calls=40, max_candidate_calls=16)
    draft = day(trip,
                PlanDraftItem(1, "PLACE", "Before", 107, "09:00", "11:00", "model"),
                PlanDraftItem(2, "FREE_TIME", "Free", None, "12:00", "13:00", "model"),
                PlanDraftItem(3, "PLACE", "After", 108, "14:00", "15:00", "model"))

    prepared = generator._prepare_draft(draft, {107: before, 108: after, 105: closed, 106: open_lunch}, set(), trip)

    assert (prepared.days[0].items[1].item_type, prepared.days[0].items[1].place_id) == ("MEAL", 106)


class SightSearchProvider(NearbyProvider):
    def __init__(self):
        super().__init__()
        self.searches = []

    def search(self, query, region):
        self.searches.append(query)
        return [
            PlaceCandidate("KAKAO", f"sight-{query}-{index}", f"{query} {index}", "AT4 여행 > 관광,명소", f"Seoul Jongno-gu {len(self.searches)}{index}", 37.5, 126.9, None, None)
            for index in range(2)
        ]


def test_a_restaurant_heavy_cache_still_searches_for_sights(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.end_date = trip.start_date.replace(day=trip.start_date.day + 2)  # three days
    session.places = [restaurant(300 + index, f"식당 {index}") for index in range(8)] + [sight(299, "해안도로")]
    search = SightSearchProvider()
    generator.place_provider = search

    pool = generator._candidate_places(trip, [], {})

    assert search.searches[0] == "관광지"
    sights = [place for place in pool if "관광" in place.category]
    assert len(sights) >= 6  # two verified sights per day before the model is asked
    assert len(pool) <= 15


def test_two_entries_at_one_address_reach_the_model_once(service):
    generator, session, _, _ = service
    trip = session.trips[1]
    session.places = [
        sight(299, "해안도로"),
        restaurant(217, "사계바다 통갈치조림", "Seoul Jongno-gu 2791-5"),
        restaurant(221, "어랑어랑생선구이", "Seoul Jongno-gu 2791-5"),
    ]

    pool = generator._candidate_places(trip, [], {})

    assert [place.place_id for place in pool if place.place_id in {217, 221}] == [217]


def test_too_few_sights_are_logged_and_generation_still_gets_the_pool(service, caplog):
    generator, session, _, _ = service
    trip = session.trips[1]
    trip.end_date = trip.start_date.replace(day=trip.start_date.day + 1)
    session.places = [sight(299, "해안도로"), restaurant(300, "식당")]

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        pool = generator._candidate_places(trip, [], {})

    # Validation then stores FOOD_ONLY_DAY on the day without a sight.
    assert {place.place_id for place in pool} == {299, 300}
    assert "plan_candidate_activity_shortage" in caplog.text and "days=2 activities=1" in caplog.text
