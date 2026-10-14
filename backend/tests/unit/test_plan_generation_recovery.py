"""A plan generated after the client lost its connection can be found again,
and a second generate request never starts a second model call."""

import json
from datetime import date, time
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError, error_response
from app.services.plan_revision_service import PlanRevisionService
from tests.unit.test_plan_generation_service import Place, service  # noqa: F401  (fixture)


def test_existing_plan_conflict_carries_the_plan_id(service):
    generator, session, provider, _ = service
    first = generator.generate(1, 1, [101])

    with pytest.raises(AppError) as error:
        generator.generate(1, 1, [101])

    assert error.value.code == "PLAN_ALREADY_EXISTS"
    assert error.value.status_code == 409
    assert error.value.details == {"plan_id": first.plan_id}
    assert len(provider.calls) == 1


def test_generate_while_the_first_request_still_runs_does_not_call_the_model_again(service):
    generator, session, provider, module = service
    good_draft = provider.draft
    nested = {}

    def slow_model(*args):
        provider.calls.append(args)
        # The client gave up and retried while this model call is running.
        with pytest.raises(AppError) as error:
            generator.generate(1, 1, [101])
        nested["error"] = error.value
        assert module.GENERATIONS_IN_PROGRESS.is_running(1)
        return good_draft

    provider.generate_plan = slow_model
    response = generator.generate(1, 1, [101])

    assert nested["error"].code == "PLAN_GENERATION_IN_PROGRESS"
    assert nested["error"].status_code == 409
    assert nested["error"].details == {"trip_id": 1}
    assert len(provider.calls) == 1
    assert response.plan_id == session.plans[1].plan_id
    assert not module.GENERATIONS_IN_PROGRESS.is_running(1)


def test_a_failed_generation_releases_the_trip_for_a_retry(service):
    generator, session, provider, module = service

    def timeout(*args):
        raise AppError("OLLAMA_TIMEOUT", "Ollama request timed out", 504)

    provider.generate_plan = timeout
    with pytest.raises(AppError):
        generator.generate(1, 1, [101])

    assert not module.GENERATIONS_IN_PROGRESS.is_running(1)
    assert session.plans == {}


def test_rejected_ownership_does_not_mark_the_trip_as_generating(service):
    generator, _, _, module = service
    with pytest.raises(AppError):
        generator.generate(2, 1, [101])
    assert not module.GENERATIONS_IN_PROGRESS.is_running(1)


def _lookup_service(plan=None, place=None, owner=1):
    svc = PlanRevisionService.__new__(PlanRevisionService)
    trip = SimpleNamespace(trip_id=7, user_id=owner, status="DRAFT", start_date=date(2026, 10, 29))
    rows = [
        SimpleNamespace(item_id=1, plan_id=40, place_id=501, visit_date=date(2026, 10, 29), sequence_no=1, item_type="MEAL", title="신선식당", start_time=time(12), end_time=time(13), validation_status="UNKNOWN", transport_mode_from_previous=None, travel_minutes_from_previous=None, travel_distance_meters_from_previous=None),
        SimpleNamespace(item_id=2, plan_id=40, place_id=None, visit_date=date(2026, 10, 29), sequence_no=2, item_type="REST", title="휴식", start_time=time(13), end_time=time(13, 30), validation_status="UNKNOWN", transport_mode_from_previous=None, travel_minutes_from_previous=None, travel_distance_meters_from_previous=None),
    ]
    svc.trips = SimpleNamespace(get=lambda trip_id: trip if trip_id == 7 else None)
    svc.plans = SimpleNamespace(get_by_trip_id=lambda trip_id: plan)
    svc.items = SimpleNamespace(list=lambda plan_id: list(rows))
    svc.issues = SimpleNamespace(list_open=lambda plan_id: [])
    svc.places = SimpleNamespace(get=lambda place_id: place if place_id == 501 else None)
    svc.members = SimpleNamespace(get_member=lambda trip_id, user_id: None)  # no invited members
    return svc


def test_trip_plan_lookup_returns_the_saved_plan_with_place_details():
    plan = SimpleNamespace(plan_id=40, trip_id=7, status="DRAFT", current_version=1)
    place = Place(501, "신선식당", category="음식점 > 한식", region="부산", address="부산 동구", latitude=35.1, longitude=129.0)
    response = _lookup_service(plan, place).get_for_trip(1, 7)

    assert response.plan_id == 40
    meal, rest = response.days[0].items
    assert (meal.item_type, meal.category, meal.address) == ("MEAL", "음식점 > 한식", "부산 동구")
    assert (meal.latitude, meal.longitude) == (35.1, 129.0)
    assert rest.item_type == "REST" and rest.latitude is None


def test_trip_plan_lookup_separates_running_from_never_generated(monkeypatch):
    import app.services.plan_revision_service as module

    svc = _lookup_service(plan=None)
    with pytest.raises(AppError) as missing:
        svc.get_for_trip(1, 7)
    assert (missing.value.code, missing.value.status_code) == ("PLAN_NOT_FOUND", 404)

    assert module.GENERATIONS_IN_PROGRESS.acquire(7)
    try:
        with pytest.raises(AppError) as running:
            svc.get_for_trip(1, 7)
    finally:
        module.GENERATIONS_IN_PROGRESS.release(7)
    assert (running.value.code, running.value.status_code) == ("PLAN_GENERATION_IN_PROGRESS", 409)


def test_trip_plan_lookup_checks_ownership():
    for user_id, trip_id, code in [(2, 7, "FORBIDDEN"), (1, 99, "TRIP_NOT_FOUND")]:
        with pytest.raises(AppError) as error:
            _lookup_service().get_for_trip(user_id, trip_id)
        assert error.value.code == code


def test_error_envelope_adds_details_only_when_present():
    with_details = json.loads(error_response(409, "PLAN_ALREADY_EXISTS", "exists", details={"plan_id": 18}).body)
    plain = json.loads(error_response(404, "PLAN_NOT_FOUND", "missing").body)

    assert with_details == {"error": {"code": "PLAN_ALREADY_EXISTS", "message": "exists", "details": {"plan_id": 18}}}
    assert plain == {"error": {"code": "PLAN_NOT_FOUND", "message": "missing"}}


def test_trip_plan_lookup_endpoint_is_registered_and_authenticated(client):
    schema = client.get("/openapi.json").json()
    assert "get" in schema["paths"]["/api/v1/trips/{trip_id}/plan"]
    assert client.get("/api/v1/trips/1/plan").status_code == 401
