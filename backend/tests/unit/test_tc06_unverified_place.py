"""TC-06 / FR-AD-305: a place outside the verified candidates is never saved."""

import json

import pytest

from app.core.exceptions import AppError
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from tests.unit.test_exaone_plan_provider import _inputs, _provider
from tests.unit.test_plan_generation_service import Provider, service  # noqa: F401  (pytest fixture)


def _plan_with(place_id):
    return json.dumps({"days": [{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "PLACE", "title": "모르는 장소", "place_id": place_id, "start_time": "10:00", "end_time": "11:00"},
    ]}]}, ensure_ascii=False)


def test_unknown_place_id_is_retried_once_then_rejected():
    provider, client = _provider(_plan_with(999))
    with pytest.raises(AppError) as error:
        provider.generate_plan(*_inputs())
    assert error.value.code == "EXAONE_INVALID_RESPONSE" and error.value.status_code == 502
    assert len(client.calls) == 2  # one automatic regeneration, then a clear error


def test_service_never_saves_a_draft_with_an_unverified_place(service):
    generator, session, _, _ = service
    day = session.trips[1].start_date
    generator.provider = Provider(GeneratedPlanDraft([PlanDraftDay(day, [
        PlanDraftItem(1, "PLACE", "모르는 장소", 999, "10:00", "11:00", "r"),
    ])]))
    with pytest.raises(AppError) as error:
        generator.generate(1, 1, [101])
    assert error.value.code == "AI_SCHEMA_VALIDATION_FAILED"
    assert session.plans == {} and session.items == [] and session.commits == 0
