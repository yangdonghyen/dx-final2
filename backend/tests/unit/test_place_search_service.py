from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.core.exceptions import AppError
from app.services.external.place.provider import PlaceCandidate


@dataclass
class Place:
    place_id: int
    name: str
    category: str | None
    region: str | None
    address: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    kakao_place_id: str | None
    phone: str | None
    website: str | None
    details_updated_at: object = None


class Session:
    def __init__(self): self.places={}; self.commits=self.rollbacks=self.flushes=0
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1
    def flush(self): self.flushes+=1


class Places:
    def __init__(self,session): self.session=session
    def get_by_kakao_place_id(self,external_id): return next((place for place in self.session.places.values() if place.kakao_place_id==external_id),None)
    def create(self,**fields):
        place=Place(place_id=len(self.session.places)+101,**fields); self.session.places[place.place_id]=place; return place
    def update(self,place,**fields):
        for key,value in fields.items(): setattr(place,key,value)
        return place


class Provider:
    def __init__(self,candidates): self.candidates=candidates; self.calls=[]
    def search(self,query,region=None): self.calls.append((query,region)); return self.candidates


def candidate(external_id="mock-place-101",latitude=37.5796,longitude=126.9770):
    return PlaceCandidate("KAKAO",external_id,"Gyeongbokgung Mock","CULTURE","Mock Seoul Jongno",latitude,longitude,None,"mock://places/101")


@pytest.fixture
def place_service(monkeypatch):
    import app.services.place_search_service as module
    monkeypatch.setattr(module,"PlaceRepository",Places)
    session=Session(); provider=Provider([candidate(),candidate("mock-place-102",37.5,126.9)])
    return module.PlaceSearchService(session,provider),session,provider


def test_place_search_converts_provider_candidates_to_internal_places(place_service):
    service,session,provider=place_service
    results=service.search("gyeongbokgung","Mock Seoul")
    assert provider.calls==[("gyeongbokgung","Mock Seoul")]
    assert [item.place_id for item in results]==[101,102]
    assert results[0].name=="Gyeongbokgung Mock" and results[0].latitude==Decimal("37.5796")
    assert all(item.region=="Mock Seoul" for item in results) and session.commits==1


def test_place_search_upserts_existing_place_instead_of_creating_duplicate(place_service):
    service,session,provider=place_service
    provider.candidates=[candidate()]
    first=service.search("gyeongbokgung")[0]
    provider.candidates=[candidate("mock-place-101",37.6,126.98)]
    second=service.search("gyeongbokgung")[0]
    assert first.place_id==second.place_id and len(session.places)==1
    assert second.latitude==Decimal("37.6")


def test_place_search_deduplicates_provider_external_ids_in_order(place_service):
    service,session,provider=place_service
    provider.candidates=[candidate(),candidate(),candidate("mock-place-102",37.5,126.9)]
    results=service.search("mock")
    assert [item.place_id for item in results]==[101,102] and len(session.places)==2


def test_empty_place_search_returns_empty_list(place_service):
    service,session,provider=place_service; provider.candidates=[]
    assert service.search("nothing")==[] and session.commits==1


def test_plan_owned_place_upsert_flushes_without_committing(place_service):
    _, session, provider = place_service
    import app.services.place_search_service as module

    service = module.PlaceSearchService(session, provider, commit=False)
    service.search("gyeongbokgung", "Mock Seoul")

    assert session.commits == 0
    assert session.flushes == 1


def test_invalid_provider_result_is_rejected_and_rolls_back(place_service):
    service,session,provider=place_service; provider.candidates=[candidate(latitude=120)]
    with pytest.raises(AppError) as error: service.search("bad")
    assert error.value.code=="EXTERNAL_PROVIDER_ERROR" and session.rollbacks==1 and not session.places


def test_mock_place_provider_supports_region_and_deterministic_empty_result():
    from app.services.external.place.mock_provider import MockPlaceProvider
    provider=MockPlaceProvider()
    assert provider.search("mock seoul","seoul")==provider.search("mock seoul","seoul")
    assert provider.search("mock seoul","busan")==[]


def test_place_search_is_registered_in_openapi(client):
    schema=client.get("/openapi.json").json()
    assert "/api/v1/places/search" in schema["paths"]
