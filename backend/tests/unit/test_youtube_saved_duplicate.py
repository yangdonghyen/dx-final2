"""Demo bug: 저장하기 then 여행 계획하기 on the same video saved twice at once -> 500."""

from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.services.youtube_saved_discovery_service import YouTubeSavedDiscoveryService


def test_a_concurrent_duplicate_save_returns_the_first_row():
    first = SimpleNamespace(saved_discovery_id=11, destination_name="강릉", representative_image_url="x")
    lookups = [None, first]  # not there yet when checked, there after the race

    class Repo:
        def get_by_user_video_position(self, **_): return lookups.pop(0)
        def create(self, **_): raise IntegrityError("INSERT", {}, Exception("Duplicate entry"))

    class Session:
        rollbacks = 0
        def rollback(self): Session.rollbacks += 1

    service = YouTubeSavedDiscoveryService.__new__(YouTubeSavedDiscoveryService)
    service.session, service.saved_discoveries = Session(), Repo()
    service._enriched_destination_fields = lambda *args, **kwargs: ("강릉", "x")
    request = SimpleNamespace(title="강릉 여행", video_id="MyuuRCaiB8A", position_sec=23, page_url=None, channel_title=None, thumbnail_url=None)

    assert service.save(19, request) is first and Session.rollbacks == 1
