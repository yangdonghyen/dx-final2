"""A missing meal is a saved WARNING, not a 422; data constraints still block."""

from datetime import date, time
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.cached_provider import CachedRouteProvider
from tests.unit.test_plan_generation_service import Provider, service  # noqa: F401  (pytest fixture)
from tests.unit.test_plan_validation_service import validation  # noqa: F401  (pytest fixture)


class NoRoutes:
    def route(self, *_args):
        return None


def full_day_without_lunch(day):
    return GeneratedPlanDraft([PlanDraftDay(day, [
        PlanDraftItem(1, "PLACE", "a", 101, "09:00", "12:00", "r"),
        PlanDraftItem(2, "REST", "휴식", None, "12:00", "13:00", "r"),
        PlanDraftItem(3, "PLACE", "b", 104, "13:00", "16:00", "r"),
    ])])


def test_plan_without_a_lunch_is_generated_and_saved(service):
    generator, session, _, _ = service
    generator.route_provider = CachedRouteProvider(NoRoutes())
    generator.provider = Provider(full_day_without_lunch(session.trips[1].start_date))
    response = generator.generate(1, 1, [101])
    assert session.commits == 1 and response.plan_id
    types = [item.item_type for day in response.days for item in day.items]
    assert "MEAL" not in types and "REST" in types  # nothing invented, rest stays rest


def test_unverified_place_still_blocks_generation(service):
    generator, session, _, _ = service
    generator.route_provider = CachedRouteProvider(NoRoutes())
    generator.provider = Provider(GeneratedPlanDraft([PlanDraftDay(session.trips[1].start_date, [
        PlanDraftItem(1, "PLACE", "모르는 장소", 999, "09:00", "12:00", "r"),
    ])]))
    with pytest.raises(AppError) as error:
        generator.generate(1, 1, [101])
    assert error.value.code == "AI_SCHEMA_VALIDATION_FAILED" and session.commits == 0


def test_validation_stores_and_returns_the_missing_lunch_as_a_warning(validation):
    svc, s = validation
    s.places[1] = SimpleNamespace(name="Museum", category="여행 > 관광,명소", verification_status="UNKNOWN", opening_hours=None)
    s.items = [
        SimpleNamespace(item_id=1, visit_date=date(2026, 1, 1), sequence_no=1, place_id=1, item_type="PLACE",
                        start_time=time(9), end_time=time(12), validation_status="UNKNOWN"),
        SimpleNamespace(item_id=2, visit_date=date(2026, 1, 1), sequence_no=2, place_id=None, item_type="REST",
                        start_time=time(12), end_time=time(13), validation_status="UNKNOWN"),
        SimpleNamespace(item_id=3, visit_date=date(2026, 1, 1), sequence_no=3, place_id=1, item_type="PLACE",
                        start_time=time(13), end_time=time(16), validation_status="UNKNOWN"),
    ]
    findings = svc.validate(SimpleNamespace(plan_id=1, last_validated_at=None),
                            SimpleNamespace(start_date=date(2026, 1, 1), end_date=date(2026, 1, 1)))
    lunch = [row for row in findings if "점심" in row[3]]
    assert lunch and all(severity == "WARNING" for _, _, severity, _ in lunch)
    assert any("점심" in issue.message and issue.severity == "WARNING" for issue in s.issues)
    assert not any(severity == "CRITICAL" for _, _, severity, _ in findings)
