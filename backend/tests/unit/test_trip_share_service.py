from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.v1.trips import render_shared_trip_page
from app.core.exceptions import AppError
from app.services import trip_share_service
from app.services.trip_share_service import TripShareService, hash_token

NOW = datetime(2026, 10, 8, 10, 0, 0)


class Session:
    def __init__(self): self.commits = self.rollbacks = 0
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


class Trips:
    def __init__(self, trips): self.trips = trips
    def get(self, trip_id): return self.trips.get(trip_id)


class Links:
    def __init__(self): self.rows = []
    def get_by_token_hash(self, token_hash): return next((row for row in self.rows if row.token_hash == token_hash), None)
    def create(self, **fields):
        row = SimpleNamespace(revoked_at=None, **fields); self.rows.append(row); return row


class TripCompanions:
    def __init__(self, rows): self.rows = rows
    def list(self, trip_id): return [row for row in self.rows if row.trip_id == trip_id]
    def get_member(self, trip_id, member_user_id): return next((row for row in self.list(trip_id) if getattr(row, "member_user_id", None) == member_user_id), None)
    def create(self, trip_id, **fields):
        row = SimpleNamespace(trip_id=trip_id, **fields); self.rows.append(row); return row


class SelectedPlaces:
    def list(self, trip_id): return [SimpleNamespace(place=SimpleNamespace(name="안목해변")), SimpleNamespace(place=None)]


class Users:
    def __init__(self, users): self.users = users
    def get(self, user_id): return self.users.get(user_id)


@pytest.fixture
def service():
    owner = SimpleNamespace(user_id=1, nickname="순지", age_group="30S")
    friend = SimpleNamespace(user_id=2, nickname="민지", age_group="60S")
    service = TripShareService(Session(), now=lambda: NOW)
    service.trips = Trips({10: SimpleNamespace(trip_id=10, user_id=1, status="PLANNED", title=None, destination="강릉", start_date=None, end_date=None), 11: SimpleNamespace(trip_id=11, user_id=1, status="ARCHIVED")})
    service.links = Links()
    service.trip_companions = TripCompanions([SimpleNamespace(trip_id=10, member_user_id=None, name_snapshot="어머니", relation_snapshot="MOTHER")])
    service.selected_places = SelectedPlaces()
    service.users = Users({1: owner, 2: friend})
    service.plans = SimpleNamespace(get_by_trip_id=lambda trip_id: None)  # no itinerary unless a test adds one
    service.plan_items = SimpleNamespace(list=lambda plan_id: [])
    service.owner, service.friend = owner, friend
    return service


def token_of(url): return url.rsplit("/", 1)[1]


def test_create_link_stores_only_token_hash_and_builds_url(service):
    created = service.create_link(1, 10, "VIEW", "http://192.168.0.5:8000/")
    token = token_of(created.url)
    assert created.url == f"http://192.168.0.5:8000/api/v1/shared-trips/{token}"
    assert created.expires_at is None
    row = service.links.rows[0]
    assert row.token_hash == hash_token(token) and token not in vars(row).values()
    assert service.session.commits == 1


def test_invite_link_expires_after_seven_days(service):
    created = service.create_link(1, 10, "INVITE", "http://host")
    assert created.expires_at == NOW + timedelta(days=7)


@pytest.mark.parametrize("user_id,trip_id,code", [(2, 10, "FORBIDDEN"), (1, 11, "TRIP_NOT_FOUND"), (1, 99, "TRIP_NOT_FOUND")])
def test_only_owner_of_active_trip_can_create_links(service, user_id, trip_id, code):
    with pytest.raises(AppError) as error: service.create_link(user_id, trip_id, "VIEW", "http://host")
    assert error.value.code == code
    assert service.links.rows == []


def test_shared_trip_returns_real_companions_and_places(service):
    token = token_of(service.create_link(1, 10, "VIEW", "http://host").url)
    shared = service.shared_trip(token)
    assert shared.destination == "강릉" and shared.owner_nickname == "순지"
    assert [(row.name, row.relation) for row in shared.companions] == [("어머니", "MOTHER")]
    assert shared.selected_places == ["안목해변"]


def test_unknown_revoked_and_expired_links_are_rejected(service):
    with pytest.raises(AppError) as error: service.shared_trip("missing")
    assert error.value.code == "SHARE_LINK_NOT_FOUND"
    token = token_of(service.create_link(1, 10, "INVITE", "http://host").url)
    service.now = lambda: NOW + timedelta(days=7)
    with pytest.raises(AppError) as error: service.shared_trip(token)
    assert error.value.code == "SHARE_LINK_EXPIRED" and error.value.status_code == 410
    service.now = lambda: NOW
    service.links.rows[0].revoked_at = NOW
    with pytest.raises(AppError) as error: service.shared_trip(token)
    assert error.value.code == "SHARE_LINK_NOT_FOUND"


def test_join_adds_member_once(service):
    token = token_of(service.create_link(1, 10, "INVITE", "http://host").url)
    first = service.join(service.friend, token)
    second = service.join(service.friend, token)
    assert (first.already_joined, second.already_joined) == (False, True)
    members = [row for row in service.trip_companions.rows if getattr(row, "member_user_id", None) == 2]
    assert len(members) == 1
    assert (members[0].name_snapshot, members[0].relation_snapshot, members[0].age_group_snapshot) == ("민지", "FRIEND", "60S")


def test_join_uses_label_instead_of_guessing_missing_nickname(service):
    token = token_of(service.create_link(1, 10, "INVITE", "http://host").url)
    service.join(SimpleNamespace(user_id=3, nickname=None, age_group=None), token)
    assert service.trip_companions.rows[-1].name_snapshot == trip_share_service.UNNAMED_MEMBER_LABEL


def test_view_link_and_owner_cannot_join(service):
    view = token_of(service.create_link(1, 10, "VIEW", "http://host").url)
    with pytest.raises(AppError) as error: service.join(service.friend, view)
    assert error.value.code == "SHARE_LINK_NOT_INVITE"
    invite = token_of(service.create_link(1, 10, "INVITE", "http://host").url)
    with pytest.raises(AppError) as error: service.join(service.owner, invite)
    assert error.value.code == "OWNER_CANNOT_JOIN"


def test_shared_page_escapes_user_text(service):
    service.trip_companions.rows[0].name_snapshot = "<script>x</script>"
    token = token_of(service.create_link(1, 10, "VIEW", "http://host").url)
    page = render_shared_trip_page(service.shared_trip(token))
    assert "<script>x" not in page and "&lt;script&gt;" in page
    assert "강릉 여행" in page


def test_invite_page_has_app_join_button(service):
    token = token_of(service.create_link(1, 10, "INVITE", "http://host").url)
    page = render_shared_trip_page(service.shared_trip(token), token)
    assert f'href="bogogago://invite?token={token}"' in page
    assert "보고가고 앱에서 참여하기" in page


def test_view_page_has_no_app_join_button(service):
    token = token_of(service.create_link(1, 10, "VIEW", "http://host").url)
    page = render_shared_trip_page(service.shared_trip(token), token)
    assert "bogogago://" not in page


def test_shared_link_shows_the_saved_itinerary(service):
    from datetime import date, time
    from app.api.v1.trips import render_shared_trip_page

    service.trips.trips[10].start_date = date(2026, 9, 19)
    service.plans = SimpleNamespace(get_by_trip_id=lambda trip_id: SimpleNamespace(plan_id=46))
    service.plan_items = SimpleNamespace(list=lambda plan_id: [
        SimpleNamespace(visit_date=date(2026, 9, 19), start_time=time(9), title="정동진 해변", item_type="PLACE", user_note=None),
        SimpleNamespace(visit_date=date(2026, 9, 19), start_time=time(14, 30), title="하슬라아트월드", item_type="PLACE", user_note="노을 사진"),
    ])
    token = token_of(service.create_link(1, 10, "VIEW", "http://host").url)
    shared = service.shared_trip(token)
    assert [(stop.start_time, stop.title) for stop in shared.days[0].stops] == [("09:00", "정동진 해변"), ("14:30", "하슬라아트월드")]
    page = render_shared_trip_page(shared, token)
    assert "DAY 1 · 9월 19일" in page and "하슬라아트월드" in page and "노을 사진" in page

