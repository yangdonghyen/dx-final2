from datetime import date, time

import pytest

from app.core.exceptions import AppError
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.cached_provider import CachedRouteProvider
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_regeneration_approval_service import PlanRegenerationApprovalService
from app.services.plan_regeneration_preview_service import PlanRegenerationPreviewService
from app.services.plan_travel_time import TravelShiftConflict, shift_day_for_travel
from tests.unit.test_plan_generation_service import Place, service  # noqa: F401  (pytest fixture)

DAY = date(2026, 10, 10)


def row(sequence, place_id, start, end, item_type=None):
    kind = item_type or ("PLACE" if place_id is not None else "REST")
    item = PlanDraftItem(sequence, kind, f"item {sequence}", place_id, start, end, "r")
    return item, time.fromisoformat(start), time.fromisoformat(end)


def times(rows):
    return [(item.place_id, start.strftime("%H:%M"), end.strftime("%H:%M")) for item, start, end in rows]


def fixed(minutes):
    return lambda _previous, _current: None if minutes is None else minutes * 60


def test_short_gap_moves_the_next_visit_and_a_later_gap_absorbs_the_delay():
    rows = [row(1, 1, "10:00", "11:00"), row(2, 2, "11:10", "12:00"), row(3, 3, "13:00", "14:00")]

    shifted = shift_day_for_travel(rows, fixed(25))

    # 11:00 + 25 min -> 11:25.  12:15 + 25 min = 12:40 still fits before
    # 13:00, so the third visit keeps its time instead of inheriting +15.
    assert times(shifted) == [(1, "10:00", "11:00"), (2, "11:25", "12:15"), (3, "13:00", "14:00")]


def test_a_delay_still_cascades_when_no_gap_can_absorb_it():
    rows = [row(1, 1, "10:00", "11:00"), row(2, 2, "11:10", "12:00"), row(3, 3, "12:20", "13:00")]

    shifted = shift_day_for_travel(rows, fixed(25))

    assert times(shifted) == [(1, "10:00", "11:00"), (2, "11:25", "12:15"), (3, "12:40", "13:20")]
    assert shifted[1][0].start_time == "11:25" and shifted[1][0].end_time == "12:15"


def test_enough_travel_time_keeps_the_schedule_unchanged():
    rows = [row(1, 1, "10:00", "11:00"), row(2, 2, "11:30", "12:00")]

    assert shift_day_for_travel(rows, fixed(30)) == rows


def test_rest_between_places_is_not_used_as_travel_time():
    rows = [row(1, 1, "10:00", "11:00"), row(2, None, "11:00", "11:30"), row(3, 2, "11:30", "12:30")]

    shifted = shift_day_for_travel(rows, fixed(20))

    # The 30-minute REST stays a rest; travel needs 20 more minutes after it.
    assert times(shifted) == [(1, "10:00", "11:00"), (None, "11:00", "11:30"), (2, "11:50", "12:50")]
    rest_minutes = PlanRegenerationPreviewService._rest_minutes
    proposed = lambda values: [{"item_type": item.item_type, "start_time": start.isoformat(), "end_time": end.isoformat()} for item, start, end in values]
    assert rest_minutes(proposed(shifted)) == rest_minutes(proposed(rows)) == 30


def test_unknown_leg_is_never_estimated():
    rows = [row(1, 1, "10:00", "11:00"), row(2, 2, "11:00", "12:00")]

    assert shift_day_for_travel(rows, fixed(None)) == rows


def test_fixed_anchor_is_never_shifted_to_resolve_an_overlap():
    rows = [row(1, 1, "10:00", "11:00"), row(2, 2, "10:30", "11:30")]

    with pytest.raises(TravelShiftConflict) as error:
        shift_day_for_travel(rows, fixed(None), fixed_place_ids={2})

    assert error.value.kind == "ANCHOR_TIME_CONFLICT"


def test_shift_past_day_end_fails_safely():
    rows = [row(1, 1, "19:00", "21:00"), row(2, 2, "21:05", "21:50")]

    with pytest.raises(TravelShiftConflict, match="22:00"):
        shift_day_for_travel(rows, fixed(30))


def test_meal_is_not_pushed_out_of_its_meal_window():
    rows = [row(1, 1, "11:00", "12:30"), row(2, 2, "12:40", "13:30", "MEAL")]

    with pytest.raises(TravelShiftConflict, match="meal window"):
        shift_day_for_travel(rows, fixed(70))  # 12:30 + 70 min -> 13:40, after lunch ends 13:30
    assert times(shift_day_for_travel(rows, fixed(20))) == [(1, "11:00", "12:30"), (2, "12:50", "13:40")]


def two_place_days(generator, start="11:00", end="11:30"):
    draft = GeneratedPlanDraft(days=[PlanDraftDay(DAY, [
        PlanDraftItem(1, "PLACE", "Museum", 101, "10:00", "10:30", "anchor"),
        PlanDraftItem(2, "REST", "Rest", None, "10:30", "10:45", "rest"),
        PlanDraftItem(3, "PLACE", "Cafe", 104, start, end, "cafe"),
    ])])
    return generator._validate_draft(draft, {101, 104})


class CountingRoutes:
    def __init__(self, seconds): self.seconds = seconds; self.calls = 0
    def route(self, *_args):
        self.calls += 1
        return None if self.seconds is None else RouteEstimate(self.seconds, "PUBLIC_TRANSIT", walking_seconds=60, transfer_count=0)


def test_adjust_keeps_anchor_places_and_day_and_reuses_cached_route(service):
    generator, session, _, _ = service
    inner = CountingRoutes(40 * 60)
    generator.route_provider = CachedRouteProvider(inner)
    places = {place.place_id: place for place in session.places}
    days = two_place_days(generator)

    adjusted = generator._adjust_route_timing(days, places, session.trips[1])
    legs = generator._validate_route_timing(adjusted, places, session.trips[1])

    assert [visit_date for visit_date, _ in adjusted] == [DAY]
    assert [item.place_id for item, _, _ in adjusted[0][1]] == [101, None, 104]
    # 10:30 + 15 min rest + 40 min travel -> 11:25.
    assert times(adjusted[0][1])[2] == (104, "11:25", "11:55")
    assert legs[(DAY, 3)].duration_seconds == 40 * 60
    assert inner.calls == 1  # adjustment and validation share one route lookup


def test_adjust_failure_keeps_route_time_conflict_code_with_diagnosis(service):
    generator, session, _, _ = service
    generator.route_provider = CountingRoutes(11 * 3600 + 40 * 60)
    places = {place.place_id: place for place in session.places}

    with pytest.raises(AppError) as error:
        generator._adjust_route_timing(two_place_days(generator), places, session.trips[1])

    assert error.value.code == "ROUTE_TIME_CONFLICT" and error.value.status_code == 422
    assert "2026-10-10" in error.value.message and "22:00" in error.value.message


def test_preview_adjusted_times_are_exactly_what_approval_revalidates(service):
    generator, session, _, _ = service
    generator.route_provider = CountingRoutes(40 * 60)
    places = {place.place_id: place for place in session.places}
    trip = session.trips[1]
    adjusted = generator._adjust_route_timing(two_place_days(generator), places, trip)
    legs = generator._validate_route_timing(adjusted, places, trip)
    proposed = [
        PlanRegenerationPreviewService._proposed_item(item, DAY, start, end, legs.get((DAY, item.sequence)))
        for item, start, end in adjusted[0][1]
    ]

    approval = PlanRegenerationApprovalService.__new__(PlanRegenerationApprovalService)
    approval.generation = generator
    stored_days = generator._validate_draft(approval._draft({"items": proposed}), set(places))
    generator._validate_route_timing(stored_days, places, trip)  # no conflict on approve

    assert times(stored_days[0][1]) == times(adjusted[0][1])
    assert generator._adjust_route_timing(stored_days, places, trip)[0][1] == stored_days[0][1]  # already fits
    assert approval._proposed_travel({"items": proposed})[(DAY, 3)]["travel_minutes_from_previous"] == 40


def test_unknown_route_keeps_generated_times(service):
    generator, session, _, _ = service
    generator.route_provider = CountingRoutes(None)
    places = {place.place_id: place for place in session.places}
    days = two_place_days(generator, "10:45", "11:15")

    assert generator._adjust_route_timing(days, places, session.trips[1]) == days
