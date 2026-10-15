"""Bell notifications: an invited companion joined / someone edited the plan."""

from types import SimpleNamespace

from app.services.notification_service import NotificationService


class Session:
    def __init__(self): self.added = []
    def add(self, row): self.added.append(row)


def service(monkeypatch, members=(), users=None):
    import app.services.notification_service as module
    monkeypatch.setattr(module, "TripCompanionRepository", lambda session: SimpleNamespace(list=lambda trip_id: [SimpleNamespace(member_user_id=m) for m in members]))
    monkeypatch.setattr(module, "UserRepository", lambda session: SimpleNamespace(get=lambda user_id: (users or {}).get(user_id)))
    return NotificationService(Session())


TRIP = SimpleNamespace(trip_id=96, user_id=19, title=None, destination="강릉")


def test_the_owner_hears_that_a_companion_joined(monkeypatch):
    svc = service(monkeypatch)
    svc.member_joined(TRIP, SimpleNamespace(user_id=20, nickname="민지"))
    (row,) = svc.session.added
    assert (row.user_id, row.kind, row.body) == (19, "MEMBER_JOINED", "민지님이 '강릉 여행'에 참여했어요.")


def test_an_edit_reaches_everyone_on_the_trip_but_the_editor(monkeypatch):
    svc = service(monkeypatch, members=(20, 21), users={20: SimpleNamespace(nickname="민지")})
    svc.plan_edited(TRIP, 20, "시간이나 설명을 바꿨어요.")
    assert sorted(row.user_id for row in svc.session.added) == [19, 21]
    assert svc.session.added[0].body == "민지님이 '강릉 여행' 일정을 수정했어요. 시간이나 설명을 바꿨어요."


def test_a_notification_failure_never_breaks_the_action(monkeypatch):
    svc = service(monkeypatch)
    svc.session.add = lambda row: (_ for _ in ()).throw(RuntimeError("db down"))
    svc.member_joined(TRIP, SimpleNamespace(user_id=20, nickname=None))  # no exception
