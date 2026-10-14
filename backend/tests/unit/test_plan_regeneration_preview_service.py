from datetime import date, datetime, time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import plans as plans_api
from app.core.exceptions import AppError
from app.core.exceptions import register_exception_handlers
from app.dependencies import get_current_user
from app.schemas.plan import PlanRegenerateRequest
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_regeneration_preview_service import PlanRegenerationPreviewService


class Session:
    def __init__(self): self.commits = self.rollbacks = 0
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


def row(item_id, place_id, sequence, item_type, start, end, title):
    return SimpleNamespace(item_id=item_id, plan_id=10, place_id=place_id, sequence_no=sequence, item_type=item_type, visit_date=date(2026, 1, 1), start_time=start, end_time=end, title=title, validation_status="VALID")


def service():
    svc = PlanRegenerationPreviewService.__new__(PlanRegenerationPreviewService)
    svc.session = Session()
    plan = SimpleNamespace(plan_id=10, trip_id=1, status="DRAFT", current_version=4)
    trip = SimpleNamespace(trip_id=1, user_id=1, status="DRAFT", start_date=date(2026, 1, 1), end_date=date(2026, 1, 1))
    items = [row(100, 1, 1, "PLACE", time(10), time(11), "Museum"), row(101, None, 2, "REST", time(12), time(12, 30), "Rest")]
    revisions = [SimpleNamespace(revision_id=7)]
    saved = []
    svc.plans = SimpleNamespace(get=lambda plan_id: plan if plan_id == 10 else None)
    svc.trips = SimpleNamespace(get=lambda trip_id: trip if trip_id == 1 else None)
    svc.items = SimpleNamespace(list=lambda plan_id: list(items))
    svc.previews = SimpleNamespace(create=lambda **fields: saved.append(fields) or SimpleNamespace(preview_id=len(saved), status="PENDING", **fields))
    candidate_places = {
        1: SimpleNamespace(place_id=1, name="Museum", latitude=37.5, longitude=127.0),
        2: SimpleNamespace(place_id=2, name="Gallery", latitude=37.6, longitude=127.1),
    }
    draft = GeneratedPlanDraft([PlanDraftDay(date(2026, 1, 1), [
        PlanDraftItem(1, "PLACE", "Museum", 1, "11:00", "12:00", "moved"),
        PlanDraftItem(2, "REST", "Rest", None, "13:00", "14:00", "rest"),
        PlanDraftItem(3, "PLACE", "Gallery", 2, "14:00", "15:00", "added"),
    ])])
    received = []
    svc.provider = SimpleNamespace(regenerate_plan=lambda *args: received.append(args) or draft)
    svc.generation = SimpleNamespace(
        _input=lambda trip: ({}, {}, [], ["CULTURE"], {"raw_interest_codes": ["CULTURE"]}, [], {1}, candidate_places),
        _normalize_draft_dates=lambda value, trip: value,
        _prepare_draft=lambda value, places, anchors, trip, preferences=None: value,
        _validate_draft=lambda value, ids: [(date(2026, 1, 1), [(item, time.fromisoformat(item.start_time), time.fromisoformat(item.end_time)) for item in value.days[0].items]) if all(item.place_id is None or item.place_id in ids for item in value.days[0].items) else (_ for _ in ()).throw(AppError("AI_SCHEMA_VALIDATION_FAILED", "invalid", 502))],
        _validate_temporal_draft=lambda days, places: None,
        _validate_route_timing=lambda days, places, trip: None,
        _validate_activity_diversity=lambda days, places, trip: None,
        _provider_error=lambda: AppError("AI_SCHEMA_VALIDATION_FAILED", "invalid", 502),
    )
    return svc, plan, trip, items, revisions, saved, received, draft


def test_preview_saves_pending_and_keeps_existing_plan_immutable():
    svc, plan, _, items, revisions, saved, received, _ = service()
    response = svc.create(1, 10, PlanRegenerateRequest(reason="USER_FATIGUE", instruction="Less walking", feedback_codes=["walking", "rest"]))
    assert response.status == "PENDING" and response.base_version == 4 and response.validation_status == "UNKNOWN"
    assert received[0][8][0]["item_id"] == 100 and received[0][9] == ["walking", "rest"]
    assert saved[0]["feedback_codes"] == ["walking", "rest"]
    assert svc._rest_minutes(saved[0]["proposed_itinerary"]["items"]) > svc._rest_minutes(saved[0]["current_itinerary_snapshot"]["items"])
    assert [entry["change_type"] for entry in response.diff] == ["RESCHEDULED", "REST_CHANGED", "ADDED"]
    assert plan.current_version == 4 and [item.item_id for item in items] == [100, 101] and len(revisions) == 1
    assert svc.session.commits == 1 and svc.session.rollbacks == 0
    svc.create(1, 10, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Move indoors"))
    assert received[-1][6] == "WEATHER_CHANGE"


def test_preview_diff_includes_unchanged_and_removed_items():
    svc, _, _, _, _, _, _, _ = service()
    current = [{"item_id": 1, "place_id": 1, "item_type": "PLACE", "visit_date": "2026-01-01", "sequence_no": 1, "start_time": "10:00:00", "end_time": "11:00:00"}, {"item_id": 2, "place_id": 2, "item_type": "PLACE", "visit_date": "2026-01-01", "sequence_no": 2, "start_time": "12:00:00", "end_time": "13:00:00"}]
    proposed = [{"place_id": 1, "item_type": "PLACE", "visit_date": "2026-01-01", "sequence_no": 1, "start_time": "10:00:00", "end_time": "11:00:00"}]
    assert [entry["change_type"] for entry in svc._diff(current, proposed)] == ["UNCHANGED", "REMOVED"]


def test_preview_diff_identifies_places_by_id_not_matching_title():
    svc, _, _, _, _, _, _, _ = service()
    current = [
        {"item_id": 1, "place_id": 10, "item_type": "PLACE", "title": "같은 이름", "visit_date": "2026-01-01", "sequence_no": 1, "start_time": "10:00:00", "end_time": "11:00:00"},
        {"item_id": 2, "place_id": 20, "item_type": "PLACE", "title": "감천문화마을", "visit_date": "2026-01-01", "sequence_no": 2, "start_time": "12:00:00", "end_time": "13:00:00"},
    ]
    proposed = [
        {"place_id": 10, "item_type": "PLACE", "title": "같은 이름", "visit_date": "2026-01-01", "sequence_no": 1, "start_time": "10:00:00", "end_time": "11:00:00"},
        {"place_id": 30, "item_type": "PLACE", "title": "같은 이름", "visit_date": "2026-01-01", "sequence_no": 2, "start_time": "12:00:00", "end_time": "13:00:00"},
    ]

    diff = svc._diff(current, proposed)

    assert [(entry["change_type"], entry["before"] and entry["before"].get("place_id"), entry["after"] and entry["after"].get("place_id")) for entry in diff] == [
        ("UNCHANGED", 10, 10), ("ADDED", None, 30), ("REMOVED", 20, None),
    ]


def test_preview_blocks_other_user_invalid_draft_provider_error_and_storage_failure():
    svc, plan, _, items, _, _, _, draft = service()
    with pytest.raises(AppError, match="own this trip"): svc.create(2, 10, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Indoors"))
    draft.days[0].items[0] = PlanDraftItem(1, "PLACE", "Fake", 999, "10:00", "11:00", "bad")
    with pytest.raises(AppError) as invalid: svc.create(1, 10, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Indoors"))
    assert invalid.value.code == "AI_SCHEMA_VALIDATION_FAILED" and plan.current_version == 4 and len(items) == 2
    svc, plan, _, items, _, _, _, _ = service()
    svc.provider.regenerate_plan = lambda *args: (_ for _ in ()).throw(RuntimeError("provider down"))
    with pytest.raises(RuntimeError): svc.create(1, 10, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Indoors"))
    assert svc.session.rollbacks == 1 and plan.current_version == 4 and len(items) == 2
    svc, plan, _, items, _, _, _, _ = service()
    svc.previews.create = lambda **fields: (_ for _ in ()).throw(RuntimeError("write failed"))
    with pytest.raises(RuntimeError): svc.create(1, 10, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Indoors"))
    assert svc.session.rollbacks == 1 and plan.current_version == 4 and len(items) == 2


def test_preview_rejects_overlapping_times_without_persisting():
    svc, plan, _, items, _, saved, _, draft = service()
    draft.days[0].items[1] = PlanDraftItem(2, "REST", "Rest", None, "11:30", "12:30", "overlap")
    with pytest.raises(AppError) as error: svc.create(1, 10, PlanRegenerateRequest(reason="USER_FATIGUE", instruction="Less walking"))
    assert error.value.code == "TIME_CONFLICT" and saved == [] and plan.current_version == 4 and len(items) == 2


def test_preview_uses_overlap_aware_provider_then_revalidates_before_saving():
    svc, plan, _, items, _, saved, _, draft = service()
    draft.days[0].items[1] = PlanDraftItem(2, "REST", "Rest", None, "11:30", "12:30", "overlap")
    calls = []
    svc.provider = SimpleNamespace(regenerate_preview_plan=lambda *args: calls.append(args) or draft)
    from app.services.plan_travel_time import shift_day_for_travel
    svc.generation._adjust_route_timing = lambda days, *_args, **_kwargs: [
        (visit_date, shift_day_for_travel(rows, lambda _previous, _current: None))
        for visit_date, rows in days
    ]

    response = svc.create(1, 10, PlanRegenerateRequest(reason="USER_FATIGUE", instruction="More rest", feedback_codes=["rest"]))

    assert response.status == "PENDING" and len(calls) == 1 and len(saved) == 1
    assert saved[0]["proposed_itinerary"]["items"][1]["start_time"] == "12:00:00"
    assert plan.current_version == 4 and [item.item_id for item in items] == [100, 101]


def test_preview_api_path_accepts_flutter_feedback_and_rejects_invalid_json():
    preview_service, _, _, _, _, _, _, _ = service()
    expected = preview_service.create(1, 10, PlanRegenerateRequest(reason="USER_FATIGUE", instruction="Less walking"))
    app = FastAPI(); register_exception_handlers(app); app.include_router(plans_api.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id=1)
    app.dependency_overrides[plans_api.get_preview_service] = lambda: SimpleNamespace(create=lambda *args: expected)
    with TestClient(app) as client:
        response = client.post("/plans/10/regeneration-previews", json={"reason": "USER_FATIGUE", "instruction": "Less walking", "feedback_codes": ["walking", "places"]})
        assert response.status_code == 200 and response.json()["status"] == "PENDING"
        invalid = client.post("/plans/10/regeneration-previews", json={"reason": "USER_FATIGUE", "instruction": "Less walking", "feedback_codes": ["not-a-flutter-code"]})
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"

def test_preview_rejects_unmet_rest_goal_without_saving():
    svc, plan, _, items, revisions, saved, _, draft = service()

    draft.days[0].items[1] = PlanDraftItem(
        2, "REST", "Rest", None, "13:00", "13:30", "rest"
    )

    with pytest.raises(AppError) as error:
        svc.create(
            1, 10,
            PlanRegenerateRequest(
                reason="USER_FATIGUE",
                instruction="More rest",
                feedback_codes=["rest"],
            ),
        )

    assert error.value.code == "FEEDBACK_GOAL_NOT_MET"
    assert saved == []
    assert svc.session.commits == 0
    assert svc.session.rollbacks == 1
    assert plan.current_version == 4
    assert [item.item_id for item in items] == [100, 101]
    assert len(revisions) == 1


def test_preview_rejects_unmet_places_goal_without_saving():
    svc, plan, _, items, _, saved, _, _ = service()

    items.append(
        row(102, 2, 3, "PLACE", time(16), time(17), "Gallery")
    )

    with pytest.raises(AppError) as error:
        svc.create(
            1, 10,
            PlanRegenerateRequest(
                reason="USER_FATIGUE",
                instruction="Fewer places",
                feedback_codes=["places"],
            ),
        )

    assert error.value.code == "FEEDBACK_GOAL_NOT_MET"
    assert saved == []
    assert svc.session.commits == 0
    assert svc.session.rollbacks == 1
    assert plan.current_version == 4
    assert len(items) == 3


def test_preview_retries_once_when_verified_feedback_goal_is_not_met():
    svc, plan, _, items, _, saved, received, draft = service()
    items.append(row(102, 2, 3, "PLACE", time(16), time(17), "Gallery"))
    corrected = GeneratedPlanDraft([PlanDraftDay(date(2026, 1, 1), [
        PlanDraftItem(1, "PLACE", "Museum", 1, "11:00", "12:00", "moved"),
        PlanDraftItem(2, "REST", "Rest", None, "13:00", "14:00", "rest"),
    ])])
    drafts = [draft, corrected]
    svc.provider.regenerate_plan = lambda *args: received.append(args) or drafts.pop(0)

    response = svc.create(
        1, 10,
        PlanRegenerateRequest(
            reason="USER_FATIGUE", instruction="Fewer places and more rest",
            feedback_codes=["places", "rest"],
        ),
    )

    assert response.status == "PENDING"
    assert len(received) == 2
    assert "before=1, latest_draft=1" in received[1][7]
    assert "before=30, latest_draft=60" in received[1][7]
    assert len(saved) == 1 and plan.current_version == 4


def test_preview_rejects_after_one_feedback_goal_retry_without_saving():
    svc, plan, _, items, _, saved, received, draft = service()
    items.append(row(102, 2, 3, "PLACE", time(16), time(17), "Gallery"))
    svc.provider.regenerate_plan = lambda *args: received.append(args) or draft

    with pytest.raises(AppError) as error:
        svc.create(
            1, 10,
            PlanRegenerateRequest(
                reason="USER_FATIGUE", instruction="Fewer places",
                feedback_codes=["places"],
            ),
        )

    assert error.value.code == "FEEDBACK_GOAL_NOT_MET"
    assert len(received) == 2
    assert saved == [] and svc.session.commits == 0 and svc.session.rollbacks == 1
    assert plan.current_version == 4


def test_preview_does_not_retry_when_the_first_feedback_draft_succeeds():
    svc, _, _, _, _, saved, received, _ = service()

    response = svc.create(
        1, 10,
        PlanRegenerateRequest(
            reason="USER_FATIGUE", instruction="More rest", feedback_codes=["rest"],
        ),
    )

    assert response.status == "PENDING"
    assert len(received) == 1 and len(saved) == 1


def test_preview_does_not_retry_anchor_loss_or_provider_failure():
    svc, _, _, _, _, saved, received, _ = service()
    missing_anchor = GeneratedPlanDraft([PlanDraftDay(date(2026, 1, 1), [
        PlanDraftItem(1, "REST", "Rest", None, "11:00", "12:00", "rest"),
    ])])
    svc.provider.regenerate_plan = lambda *args: received.append(args) or missing_anchor
    with pytest.raises(AppError):
        svc.create(1, 10, PlanRegenerateRequest(reason="USER_FATIGUE", instruction="More rest", feedback_codes=["rest"]))
    assert len(received) == 1 and saved == []

    svc, _, _, _, _, saved, received, _ = service()
    svc.provider.regenerate_plan = lambda *args: received.append(args) or (_ for _ in ()).throw(AppError("EXAONE_TIMEOUT", "timeout", 503))
    with pytest.raises(AppError) as error:
        svc.create(1, 10, PlanRegenerateRequest(reason="USER_FATIGUE", instruction="More rest", feedback_codes=["rest"]))
    assert error.value.code == "EXAONE_TIMEOUT"
    assert len(received) == 1 and saved == []


def test_preview_rejects_partial_feedback_success():
    svc, plan, _, items, _, saved, _, draft = service()

    items.append(
        row(102, 2, 3, "PLACE", time(16), time(17), "Gallery")
    )

    # Reduce optional activities, but do not increase REST duration.
    draft.days[0].items.pop()
    draft.days[0].items[1] = PlanDraftItem(
        2, "REST", "Rest", None, "13:00", "13:30", "rest"
    )

    with pytest.raises(AppError) as error:
        svc.create(
            1, 10,
            PlanRegenerateRequest(
                reason="USER_FATIGUE",
                instruction="Fewer places and more rest",
                feedback_codes=["places", "rest"],
            ),
        )

    assert error.value.code == "FEEDBACK_GOAL_NOT_MET"
    assert saved == []
    assert svc.session.commits == 0
    assert svc.session.rollbacks == 1
    assert plan.current_version == 4


def test_preview_saves_when_places_and_rest_both_improve():
    svc, plan, _, items, _, saved, _, draft = service()

    items.append(
        row(102, 2, 3, "PLACE", time(16), time(17), "Gallery")
    )

    # Remove the optional Gallery and retain the increased REST.
    draft.days[0].items.pop()

    response = svc.create(
        1, 10,
        PlanRegenerateRequest(
            reason="USER_FATIGUE",
            instruction="Fewer places and more rest",
            feedback_codes=["places", "rest"],
        ),
    )

    assert response.status == "PENDING"
    assert len(saved) == 1
    assert svc.session.commits == 1
    assert svc.session.rollbacks == 0
    assert plan.current_version == 4

    assert (
        svc._rest_minutes(saved[0]["proposed_itinerary"]["items"])
        >
        svc._rest_minutes(saved[0]["current_itinerary_snapshot"]["items"])
    )

    assert any(
        change["change_type"] == "REMOVED"
        and change["before"]["place_id"] == 2
        for change in response.diff
    )


class Routes:
    def __init__(self, estimates):
        self.estimates = list(estimates)
        self.calls = []

    def route(self, *args):
        self.calls.append(args)
        return self.estimates.pop(0) if self.estimates else None


@pytest.mark.parametrize(
    ("feedback_code", "before", "after"),
    [
        ("walking", RouteEstimate(900, "PUBLIC_TRANSIT", walking_seconds=600), RouteEstimate(800, "PUBLIC_TRANSIT", walking_seconds=600)),
        ("travel", RouteEstimate(900, "CAR", walking_seconds=20), RouteEstimate(900, "CAR", walking_seconds=10)),
    ],
)
def test_preview_rejects_unimproved_verified_walking_or_travel_without_saving(
    feedback_code, before, after
):
    svc, plan, _, items, _, saved, _, _ = service()
    items.append(row(102, 2, 3, "PLACE", time(16), time(17), "Gallery"))
    svc.generation.route_provider = Routes([before, after])

    with pytest.raises(AppError) as error:
        svc.create(
            1, 10,
            PlanRegenerateRequest(
                reason="USER_FATIGUE",
                instruction="Reduce route burden",
                feedback_codes=[feedback_code],
            ),
        )

    assert error.value.code == "FEEDBACK_GOAL_NOT_MET"
    assert saved == []
    assert svc.session.commits == 0
    assert svc.session.rollbacks == 1
    assert plan.current_version == 4


@pytest.mark.parametrize(
    ("feedback_code", "before", "after"),
    [
        ("walking", RouteEstimate(900, "PUBLIC_TRANSIT", walking_seconds=600), RouteEstimate(900, "PUBLIC_TRANSIT", walking_seconds=300)),
        ("travel", RouteEstimate(900, "CAR", walking_seconds=60), RouteEstimate(600, "CAR", walking_seconds=60)),
    ],
)
def test_preview_saves_when_verified_walking_or_travel_improves(
    feedback_code, before, after
):
    svc, plan, _, items, _, saved, _, _ = service()
    items.append(row(102, 2, 3, "PLACE", time(16), time(17), "Gallery"))
    svc.generation.route_provider = Routes([before, after])

    response = svc.create(
        1, 10,
        PlanRegenerateRequest(
            reason="USER_FATIGUE",
            instruction="Reduce route burden",
            feedback_codes=[feedback_code],
        ),
    )

    assert response.status == "PENDING"
    assert len(saved) == 1
    assert svc.session.commits == 1
    assert svc.session.rollbacks == 0
    assert plan.current_version == 4


def test_preview_keeps_walking_and_travel_unknown_when_route_facts_are_missing():
    svc, plan, _, items, _, saved, _, _ = service()
    items.append(row(102, 2, 3, "PLACE", time(16), time(17), "Gallery"))
    svc.generation.route_provider = Routes([None])

    response = svc.create(
        1, 10,
        PlanRegenerateRequest(
            reason="USER_FATIGUE",
            instruction="Reduce every route burden",
            feedback_codes=["walking", "travel"],
        ),
    )

    assert response.status == "PENDING"
    assert response.validation_status == "UNKNOWN"
    assert len(saved) == 1
    assert svc.session.commits == 1
    assert plan.current_version == 4
