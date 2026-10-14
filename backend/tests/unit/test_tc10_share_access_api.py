"""TC-10 / FR-AD-405, NFR-DV-006: direct API calls without a valid owner are refused."""

from fastapi.testclient import TestClient

from app.api.v1.plans import get_edit_service
from app.api.v1.trips import get_share_service
from app.core.config import Settings
from app.core.exceptions import AppError
from app.dependencies import get_current_user
from app.main import create_app

EDIT = {"operation": "DELETE_PLACE", "item_id": 1}


def test_plan_edit_without_a_token_is_rejected():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.post("/api/v1/plans/32/edit", json=EDIT)
    assert response.status_code == 401


def test_plan_edit_by_a_non_owner_returns_403_through_the_api():
    app = create_app(Settings(_env_file=None))

    class NotOwner:
        def edit(self, user_id, plan_id, request):
            raise AppError("FORBIDDEN", "You do not own this trip", 403)

    app.dependency_overrides[get_edit_service] = NotOwner
    app.dependency_overrides[get_current_user] = lambda: type("User", (), {"user_id": 999})()
    with TestClient(app) as client:
        response = client.post("/api/v1/plans/32/edit", json=EDIT)
    assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN"


def test_expired_share_link_is_refused_through_the_api():
    app = create_app(Settings(_env_file=None))

    class Expired:
        def shared_trip(self, token):
            raise AppError("SHARE_LINK_EXPIRED", "Share link expired", 410)

    app.dependency_overrides[get_share_service] = Expired
    with TestClient(app) as client:
        response = client.get("/api/v1/shared-trips/old-token", headers={"accept": "application/json"})
    assert response.status_code == 410 and response.json()["error"]["code"] == "SHARE_LINK_EXPIRED"


def test_expired_share_link_shows_a_readable_page_in_a_browser():
    app = create_app(Settings(_env_file=None))

    class Expired:
        def shared_trip(self, token):
            raise AppError("SHARE_LINK_EXPIRED", "Share link expired", 410)

    app.dependency_overrides[get_share_service] = Expired
    with TestClient(app) as client:
        response = client.get("/api/v1/shared-trips/old-token", headers={"accept": "text/html"})
    assert response.status_code == 410 and "만료된 공유 링크예요" in response.text


def test_destination_image_is_looked_up_once_per_region():
    from app.api.v1 import trips

    trips._DESTINATION_IMAGES.clear()
    asked = []

    class Images:
        def search_destination_image(self, name):
            asked.append(name)
            return f"https://img.test/{name}.jpg"

    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[trips.get_destination_images] = Images
    app.dependency_overrides[get_current_user] = lambda: type("User", (), {"user_id": 7})()
    with TestClient(app) as client:
        first = client.get("/api/v1/destination-image", params={"destination": "강릉"}).json()
        client.get("/api/v1/destination-image", params={"destination": " 강릉 "})
    assert first == {"destination": "강릉", "image_url": "https://img.test/강릉.jpg"} and asked == ["강릉"]
    trips._DESTINATION_IMAGES.clear()


def test_tour_representative_image_prefers_the_regions_own_landmark():
    from app.services.external.place.tour_destination_image_provider import TourDestinationImageProvider

    provider = TourDestinationImageProvider("key", "http://tour.test", 3)
    provider._get_json = lambda endpoint, params: {"response": {"body": {"items": {"item": [
        {"title": "남부산교회", "firstimage": "http://tong.visitkorea.or.kr/a.jpg"},
        {"title": "부산 감천문화마을", "firstimage": ""},
        {"title": "부산 송도해상케이블카", "firstimage": "http://tong.visitkorea.or.kr/b.jpg"},
    ]}}}}
    assert provider.search_destination_image("부산") == "https://tong.visitkorea.or.kr/b.jpg"
