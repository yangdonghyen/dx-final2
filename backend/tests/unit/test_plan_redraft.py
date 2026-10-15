"""AI 코스 초안 "다시 만들기": a new AI plan for the same trip, same plan id."""

import pytest

from app.core.exceptions import AppError
from tests.unit.test_plan_generation_service import service  # noqa: F401  (fixture)


@pytest.fixture
def redraft_ready(service, monkeypatch):
    generator, session, provider, module = service
    revisions = []
    monkeypatch.setattr(module, "PlanRevisionRepository", lambda _session: type("R", (), {"create": lambda self, plan_id, **f: revisions.append((plan_id, f))})())
    generator.generate(1, 1, [101])
    plan = session.plans[1]
    plan.current_version = 1
    generator.plans.get = lambda plan_id: plan if plan_id == plan.plan_id else None
    generator.items.list = lambda plan_id: [item for item in session.items if item.plan_id == plan_id]
    generator.items.delete = lambda item: session.items.remove(item)
    return generator, session, provider, plan, revisions


def test_redraft_replaces_the_draft_items_and_keeps_the_old_ones_as_a_revision(redraft_ready):
    generator, session, provider, plan, revisions = redraft_ready
    before = list(session.items)

    response = generator.redraft(1, plan.plan_id)

    assert response.plan_id == plan.plan_id and plan.current_version == 2
    assert len(provider.calls) == 2  # the AI ran again
    assert not {id(item) for item in before} & {id(item) for item in session.items}  # old items gone
    assert revisions[0][1]["revision_type"] == "AI_REGENERATE" and len(revisions[0][1]["snapshot"]["items"]) == len(before)


def test_a_confirmed_plan_or_another_users_plan_is_not_redrawn(redraft_ready):
    generator, session, provider, plan, _ = redraft_ready
    with pytest.raises(AppError) as error:
        generator.redraft(2, plan.plan_id)
    assert error.value.status_code in (403, 404)
    plan.status = "CONFIRMED"
    with pytest.raises(AppError) as error:
        generator.redraft(1, plan.plan_id)
    assert error.value.code == "PLAN_NOT_DRAFT" and len(provider.calls) == 1


def test_redraft_moves_only_the_previous_sights_last_and_keeps_the_whole_pool():
    from types import SimpleNamespace
    from app.services.plan_generation_service import PlanGenerationService

    sight = lambda pid: SimpleNamespace(place_id=pid, name=f"s{pid}", category="여행 > 관광,명소")
    meal = lambda pid: SimpleNamespace(place_id=pid, name=f"m{pid}", category="음식점 > 한식")
    places = {1: sight(1), 2: sight(2), 3: sight(3), 11: meal(11), 12: meal(12)}
    svc = PlanGenerationService.__new__(PlanGenerationService)
    svc.items = SimpleNamespace(list=lambda plan_id: [SimpleNamespace(place_id=1), SimpleNamespace(place_id=11), SimpleNamespace(place_id=None)])
    rows = [{"place_id": pid} for pid in (1, 2, 3, 11, 12)]

    shown = svc._fresh_draft_candidates(SimpleNamespace(plan_id=5), rows, places, set(), SimpleNamespace(trip_id=1))

    assert [row["place_id"] for row in shown] == [2, 3, 11, 12, 1]  # ranking kept, the used sight last
