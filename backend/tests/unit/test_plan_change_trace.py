"""Generation change trace: what each stage changed, observation only."""

import logging
from datetime import date, time

from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.plan_generation_service import plan_trace_diff, plan_trace_snapshot
from tests.unit.test_plan_generation_service import Place, service  # noqa: F401  (pytest fixture)

DAY1, DAY2 = date(2026, 10, 27), date(2026, 10, 28)
PLACES = {
    1: Place(1, "올레길", category="여행 > 도보여행"),
    2: Place(2, "카페", category="음식점 > 카페"),
    3: Place(3, "먼식당", category="음식점 > 분식"),
    4: Place(4, "가까운식당", category="음식점 > 한식"),
}


def draft(*days):
    return GeneratedPlanDraft([PlanDraftDay(day, [PlanDraftItem(*row, "r") for row in rows]) for day, rows in days])


BASE = draft((DAY1, [
    (1, "PLACE", "a", 1, "09:00", "12:00"),
    (2, "REST", "휴식", None, "12:00", "12:40"),
    (3, "MEAL", "b", 3, "13:30", "15:00"),
]))


def diff(after, causes=None, before=BASE):
    return plan_trace_diff(plan_trace_snapshot(before, PLACES), plan_trace_snapshot(after, PLACES), causes)


def test_rest_turned_cafe_and_meal_swap_are_replacements_with_rest_and_cafe_totals():
    after = draft((DAY1, [
        (1, "PLACE", "a", 1, "09:00", "12:00"),
        (2, "PLACE", "c", 2, "12:00", "12:40"),
        (3, "MEAL", "d", 4, "13:30", "15:00"),
    ]))
    changes, totals = diff(after, {"2026-10-27": "REPLACED"})
    assert [(c["sequence"], c["change"], c["from_place_id"], c["to_place_id"], c["to_kind"]) for c in changes] == [
        (2, "REPLACED", None, 2, "CAFE"), (3, "REPLACED", 3, 4, "MEAL"),
    ]
    assert {c["cause"] for c in changes} == {"REPLACED"}
    assert totals == {"2026-10-27": {"REST": -40, "CAFE": 40}}


def test_time_change_reports_stay_delta_and_unknown_cause_when_not_given():
    after = draft((DAY1, [
        (1, "PLACE", "a", 1, "09:00", "11:30"),
        (2, "REST", "휴식", None, "11:30", "12:10"),
        (3, "MEAL", "b", 3, "13:30", "15:00"),
    ]))
    changes, totals = diff(after)
    assert changes[0] == {"visit_date": "2026-10-27", "sequence": 1, "change": "TIME_CHANGED", "place_id": 1, "kind": "PLACE",
                          "from": "09:00-12:00", "to": "09:00-11:30", "stay_delta_minutes": -30, "cause": "UNKNOWN"}
    assert changes[1]["stay_delta_minutes"] == 0
    assert totals == {"2026-10-27": {"STAY": -30}}


def test_added_removed_reordered_and_moved_between_days():
    before = draft((DAY1, [(1, "PLACE", "a", 1, "09:00", "12:00"), (2, "PLACE", "c", 2, "12:00", "13:00")]),
                   (DAY2, [(1, "PLACE", "x", 4, "09:00", "10:00")]))
    after = draft((DAY1, [(1, "PLACE", "c", 2, "09:00", "10:00"), (2, "PLACE", "a", 1, "10:00", "13:00")]),
                  (DAY2, [(2, "MEAL", "y", 3, "12:00", "13:00")]))
    changes, _ = diff(after, before=before)
    kinds = [(c["visit_date"], c["change"]) for c in changes]
    assert ("2026-10-28", "REMOVED") in kinds and ("2026-10-28", "ADDED") in kinds
    assert {"visit_date": "2026-10-27", "change": "REORDERED", "from": [1, 2], "to": [2, 1], "cause": "UNKNOWN"} in changes


def test_snapshot_is_a_copy_so_later_in_place_repairs_do_not_change_it():
    plan = draft((DAY1, [(1, "PLACE", "a", 1, "09:00", "12:00")]))
    snapshot = plan_trace_snapshot(plan, PLACES)
    plan.days[0].items[0] = PlanDraftItem(1, "PLACE", "a", 1, "10:00", "12:00", "r")
    assert snapshot[("2026-10-27", 1)] == (1, "PLACE", "09:00", "12:00")


def test_validated_days_rows_are_read_like_draft_rows():
    item = PlanDraftItem(1, "MEAL", "b", 3, "13:30", "15:00", "r")
    assert plan_trace_snapshot([(DAY1, [(item, time(13, 40), time(15, 10))])], PLACES) == {
        ("2026-10-27", 1): (3, "MEAL", "13:40", "15:10"),
    }


def test_generation_logs_every_stage_without_place_names_and_keeps_the_result(service, caplog):
    generator, session, _, _ = service
    with caplog.at_level(logging.INFO):
        response = generator.generate(1, 1, [101])
    traces = [record.getMessage() for record in caplog.records if record.getMessage().startswith("plan_change_trace ")]
    stages = [line.split("stage=")[1].split()[0] for line in traces]
    assert stages == ["ai_generate", "prepare_meals", "route_optimize", "rest_cafes", "far_meals", "route_timing", "opening_hours"]
    names = {getattr(place, "name", None) for place in getattr(session, "places", [])} - {None}
    assert not any(name in line for line in traces for name in names)
    assert response.days and session.commits == 1
