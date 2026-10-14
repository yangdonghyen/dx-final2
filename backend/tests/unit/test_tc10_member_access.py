"""TC-10: an invited member may read the plan and edit its items, nothing more.

Expiry is checked with an injected clock; no stored link is changed.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from tests.unit.test_plan_edit_service import edit, request  # noqa: F401  (fixture)
from tests.unit.test_trip_share_service import NOW, service as share_service, token_of  # noqa: F401  (fixture)

OWNER, MEMBER, STRANGER = 1, 2, 3


class Members:
    def get_member(self, trip_id, user_id): return SimpleNamespace() if (trip_id, user_id) == (1, MEMBER) else None


@pytest.fixture
def members(edit):
    edit[0].members = Members()


def test_member_can_edit_items_and_stranger_cannot(edit, members):
    service, s = edit
    result = service.edit(MEMBER, 10, request("DELETE_PLACE", item_id=101))
    assert result.current_version == 2 and s.revisions[0].revision_type == "USER_EDIT"
    with pytest.raises(AppError) as error: service.edit(STRANGER, 10, request("DELETE_PLACE", item_id=102))
    assert error.value.status_code == 403 and s.plan.current_version == 2


def test_member_cannot_manage_sharing(share_service):
    with pytest.raises(AppError) as error: share_service.create_link(MEMBER, 10, "INVITE", "http://host")
    assert error.value.code == "FORBIDDEN" and share_service.links.rows == []


def test_owner_only_actions_keep_the_owner_check():
    """Regenerate, confirm, previews and trip changes never accept members."""
    import inspect
    from app.services import plan_regeneration_approval_service, plan_regeneration_preview_service, plan_revision_service, trip_service

    assert "require_plan_member" not in inspect.getsource(plan_regeneration_preview_service)
    assert "require_plan_member" not in inspect.getsource(plan_regeneration_approval_service)
    assert "require_plan_member" not in inspect.getsource(trip_service)
    revision = inspect.getsource(plan_revision_service.PlanRevisionService)
    assert "self._owned_plan(user_id, plan_id)\n" in inspect.getsource(plan_revision_service.PlanRevisionService.regenerate)
    assert "members=True" not in inspect.getsource(plan_revision_service.PlanRevisionService.confirm) and revision


def test_expired_invite_cannot_be_joined(share_service):
    token = token_of(share_service.create_link(OWNER, 10, "INVITE", "http://host").url)
    share_service.now = lambda: NOW + timedelta(days=7)
    with pytest.raises(AppError) as error: share_service.join(share_service.friend, token)
    assert error.value.code == "SHARE_LINK_EXPIRED" and error.value.status_code == 410
    assert [row for row in share_service.trip_companions.rows if getattr(row, "member_user_id", None) == MEMBER] == []
