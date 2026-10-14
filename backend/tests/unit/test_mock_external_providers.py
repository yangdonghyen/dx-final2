import json

import pytest

from app.core.exceptions import AppError
from app.core.config import Settings
from app.services.external.ai.mock_provider import MockPlanGenerationProvider, MockPreferenceAnalysisProvider
from app.services.external.ai.exaone_preference_provider import ExaonePreferenceAnalysisProvider
from app.services.external.ai.exaone_plan_provider import ExaonePlanGenerationProvider
from app.services.external.content.mock_provider import MockContentProvider
from app.services.external.content.youtube_provider import YouTubeContentProvider
from app.services.external.factory import get_content_provider, get_place_provider, get_plan_generation_provider, get_plan_regeneration_preview_provider, get_preference_analysis_provider, get_naver_cafe_evidence_provider
from app.services.external.naver_api_hub_provider import NaverApiHubProvider, UnavailableNaverCafeEvidenceProvider
from app.services.external.place.mock_provider import MockPlaceProvider
from app.services.external.place.kakao_provider import KakaoPlaceProvider


def test_mock_json_fixtures_are_utf8_and_have_required_shapes():
    from app.services.external.mock_data import DEFAULT_MOCK_DATA_DIR
    expected = {"youtube.json": "videos", "places.json": "places", "plans.json": "item_templates"}
    for filename, key in expected.items():
        with (DEFAULT_MOCK_DATA_DIR / filename).open(encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        assert isinstance(payload[key], list) and payload[key]


def test_mock_content_provider_returns_deterministic_unicode_metadata():
    provider = MockContentProvider()
    first = provider.get_video("mock-seoul-trip")
    second = provider.get_video("mock-seoul-trip")
    assert first == second
    assert first.video_id == "mock-seoul-trip" and first.title and "�" not in first.title
    assert first.tags == ["CULTURE", "CAFE"]


def test_mock_content_provider_handles_no_tags_and_not_found():
    provider = MockContentProvider()
    assert provider.get_video("mock-no-tags").tags == []
    with pytest.raises(AppError) as error: provider.get_video("missing")
    assert error.value.code == "PROVIDER_NOT_FOUND"


def test_mock_preference_analysis_is_deterministic_and_uses_only_master_codes():
    provider = MockPreferenceAnalysisProvider()
    result = provider.analyze_preferences("culture cafe food")
    assert result == provider.analyze_preferences("culture cafe food")
    assert result.interest_codes == ["CAFE", "FOOD", "CULTURE"]
    assert set(result.interest_codes) <= {"FOOD", "CAFE", "NATURE", "CULTURE", "HISTORY", "SHOPPING", "EXHIBITION", "ACTIVITY"}
    assert provider.analyze_preferences("").interest_codes == []


def test_mock_place_search_is_deterministic_and_returns_empty_for_unknown_query():
    provider = MockPlaceProvider()
    first = provider.search("mock seoul")
    assert first == provider.search("mock seoul")
    assert len(first) == 6
    assert first[0].external_id == "mock-place-101" and isinstance(first[0].latitude, float)
    assert provider.search("no-such-place") == []


def test_mock_plan_generation_is_deterministic_and_only_references_input_places():
    provider = MockPlanGenerationProvider()
    trip = {"start_date": "2026-10-10", "destination": "Mock Seoul"}
    places = [{"place_id": 101, "name": "Gyeongbokgung Mock"}]
    first = provider.generate_plan(trip, {}, [], ["CULTURE"], {"raw_interest_codes": []}, places)
    assert first == provider.generate_plan(trip, {}, [], ["CULTURE"], {"raw_interest_codes": []}, places)
    assert first.days[0].visit_date.isoformat() == "2026-10-10"
    assert [item.sequence for item in first.days[0].items] == [1, 2]
    assert {item.place_id for item in first.days[0].items if item.place_id is not None} <= {101}
    assert first.days[0].items[1].item_type == "FREE_TIME"


def test_factory_returns_mock_providers_without_network_clients():
    assert isinstance(get_content_provider(), MockContentProvider)
    assert isinstance(get_preference_analysis_provider(), MockPreferenceAnalysisProvider)
    assert isinstance(get_place_provider(), MockPlaceProvider)
    assert isinstance(get_plan_generation_provider(), MockPlanGenerationProvider)
    assert isinstance(get_naver_cafe_evidence_provider(Settings()), UnavailableNaverCafeEvidenceProvider)


def test_factory_keeps_api_hub_search_credentials_separate_from_naver_login():
    settings = Settings(naver_client_id="oauth-id", naver_client_secret="oauth-secret", naver_api_hub_client_id="search-id", naver_api_hub_client_secret="search-secret")
    assert isinstance(get_naver_cafe_evidence_provider(settings), NaverApiHubProvider)


def test_naver_cafe_evidence_factory_logs_provider_state_without_credentials(caplog):
    with caplog.at_level("INFO"):
        get_naver_cafe_evidence_provider(Settings())
        get_naver_cafe_evidence_provider(Settings(naver_api_hub_client_id="search-id", naver_api_hub_client_secret="search-secret"))
    assert "provider=UnavailableNaverCafeEvidenceProvider configured=false" in caplog.text
    assert "provider=NaverApiHubProvider configured=true" in caplog.text
    assert "search-secret" not in caplog.text


def test_plan_factory_selects_exaone_real_provider():
    settings = Settings(plan_provider="real", exaone_base_url="http://127.0.0.1:11434", exaone_model="exaone-test")
    assert isinstance(get_plan_generation_provider(settings), ExaonePlanGenerationProvider)
    assert get_plan_generation_provider(settings).timeout == 180
    assert get_plan_regeneration_preview_provider(settings).timeout == 240


def test_place_factory_selects_kakao_real_provider():
    assert isinstance(get_place_provider(Settings(place_provider="real", kakao_rest_api_key="test-key")), KakaoPlaceProvider)


def test_content_factory_selects_youtube_real_provider():
    assert isinstance(get_content_provider(Settings(content_provider="real", youtube_api_key="test-key")), YouTubeContentProvider)


def test_preference_factory_selects_exaone_real_provider():
    settings = Settings(preference_provider="real", exaone_base_url="http://127.0.0.1:11434", exaone_model="exaone-test")
    assert isinstance(get_preference_analysis_provider(settings), ExaonePreferenceAnalysisProvider)


def test_mock_providers_do_not_open_network_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Mock providers must not use the network")
    monkeypatch.setattr("socket.create_connection", forbidden)
    assert MockContentProvider().get_video("mock-seoul-trip").channel_id
    assert MockPlaceProvider().search("cafe")
    assert MockPreferenceAnalysisProvider().analyze_preferences("food").interest_codes == ["FOOD"]
