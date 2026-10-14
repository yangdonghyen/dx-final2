import logging

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.services.external.ai.mock_provider import MockPlanGenerationProvider, MockPreferenceAnalysisProvider
from app.services.external.ai.exaone_plan_provider import ExaonePlanGenerationProvider
from app.services.external.ai.exaone_preference_provider import ExaonePreferenceAnalysisProvider
from app.services.external.content.mock_provider import MockContentProvider
from app.services.external.content.youtube_provider import YouTubeContentProvider
from app.services.external.place.mock_provider import MockPlaceProvider
from app.services.external.place.kakao_provider import KakaoPlaceProvider
from app.services.external.place.kakao_image_provider import KakaoImageProvider
from app.services.external.place.tour_destination_image_provider import (
    TourDestinationImageProvider,
)
from app.services.external.scene.gemini_provider import GeminiSceneProvider
from app.services.external.scene.mock_provider import MockSceneRecognitionProvider
from app.services.external.weather.kma_provider import KmaProvider
from app.services.external.routing import CachedRouteProvider, KakaoMobilityRouteProvider, UnavailableRouteProvider
from app.services.external.naver_api_hub_provider import NaverApiHubProvider, UnavailableNaverCafeEvidenceProvider
from app.services.youtube_representative_selector import YouTubeRepresentativeSelector
from app.services.youtube_destination_recommendation_selector import (
    YouTubeDestinationRecommendationSelector,
)

logger = logging.getLogger("uvicorn.error")


def _select(mode: str, name: str, mock_provider):
    if mode == "mock":
        return mock_provider()
    # Real implementations are intentionally deferred to Task 11.
    raise AppError("REAL_PROVIDER_NOT_IMPLEMENTED", f"Real {name} provider is not implemented", 501)


def get_content_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.content_provider == "mock":
        return MockContentProvider()
    return YouTubeContentProvider(settings.youtube_api_key.get_secret_value(), settings.external_api_timeout_seconds)


def get_preference_analysis_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.preference_provider == "mock":
        return MockPreferenceAnalysisProvider()
    return ExaonePreferenceAnalysisProvider(settings.exaone_base_url, settings.exaone_model, settings.ai_api_timeout_seconds)


def get_destination_image_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    return KakaoImageProvider(
        settings.kakao_rest_api_key.get_secret_value(),
        settings.external_api_timeout_seconds,
    )


def get_tour_destination_image_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    return TourDestinationImageProvider(
        settings.tour_api_key.get_secret_value(),
        settings.tour_api_base_url,
        settings.external_api_timeout_seconds,
    )


def provide_tour_destination_image_provider():
    """Plan generation uses it only for already-linked Tour content IDs."""
    return get_tour_destination_image_provider()


def get_youtube_representative_selector(settings: Settings | None = None):
    settings = settings or get_settings()
    return YouTubeRepresentativeSelector(
        settings.exaone_base_url,
        settings.exaone_model,
        settings.ai_api_timeout_seconds,
    )


def get_youtube_destination_recommendation_selector(
    settings: Settings | None = None,
):
    settings = settings or get_settings()
    return YouTubeDestinationRecommendationSelector(
        settings.exaone_base_url,
        settings.exaone_model,
        settings.ai_api_timeout_seconds,
    )


def get_place_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.place_provider == "mock":
        return MockPlaceProvider()
    return KakaoPlaceProvider(settings.kakao_rest_api_key.get_secret_value(), settings.external_api_timeout_seconds)


def get_route_provider(settings: Settings | None = None):
    """Select an opt-in route adapter; missing credentials remain UNKNOWN."""
    settings = settings or get_settings()
    if settings.route_provider != "kakao":
        return UnavailableRouteProvider()
    return KakaoMobilityRouteProvider(
        settings.kakao_rest_api_key.get_secret_value(),
        settings.external_api_timeout_seconds,
        mobility_base_url=settings.kakao_mobility_base_url,
        map_base_url=settings.kakao_map_base_url,
        walking_route_mode=settings.kakao_map_walking_route_mode,
    )


def get_naver_cafe_evidence_provider(settings: Settings | None = None):
    """API-HUB Search adapter, intentionally independent from NAVER OAuth."""
    settings = settings or get_settings()
    client_id = settings.naver_api_hub_client_id.strip()
    client_secret = settings.naver_api_hub_client_secret.get_secret_value()
    if not client_id or not client_secret:
        logger.info("naver_cafe_evidence_provider provider=UnavailableNaverCafeEvidenceProvider configured=false")
        return UnavailableNaverCafeEvidenceProvider()
    logger.info("naver_cafe_evidence_provider provider=NaverApiHubProvider configured=true")
    return NaverApiHubProvider(client_id, client_secret, settings.external_api_timeout_seconds)


def get_kakao_region_geocoder(settings: Settings | None = None):
    settings = settings or get_settings()
    return KakaoPlaceProvider(
        settings.kakao_rest_api_key.get_secret_value(),
        settings.external_api_timeout_seconds,
    )


def get_plan_generation_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.plan_provider == "mock":
        return MockPlanGenerationProvider()
    return ExaonePlanGenerationProvider(settings.exaone_base_url, settings.exaone_model, settings.ai_api_timeout_seconds, num_ctx=settings.exaone_num_ctx, fixture_dir=settings.plan_ai_fixture_dir)


def get_plan_regeneration_preview_provider(settings: Settings | None = None):
    """The preview endpoint alone gets its own Ollama request ceiling."""
    settings = settings or get_settings()
    if settings.plan_provider == "mock":
        return MockPlanGenerationProvider()
    return ExaonePlanGenerationProvider(
        settings.exaone_base_url,
        settings.exaone_model,
        settings.plan_regeneration_preview_ai_timeout_seconds,
        num_ctx=settings.exaone_num_ctx,
        fixture_dir=settings.plan_ai_fixture_dir,
    )


def get_scene_recognition_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.scene_recognition_provider == "mock":
        return MockSceneRecognitionProvider()
    return GeminiSceneProvider(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.ai_api_timeout_seconds,
        fallback_model=settings.gemini_fallback_model,
    )


def get_weather_provider(settings: Settings | None = None):
    settings = settings or get_settings()
    return KmaProvider(
        settings.kma_api_key.get_secret_value(),
        settings.kma_api_base_url,
        settings.external_api_timeout_seconds,
    )


# FastAPI dependencies deliberately have no Settings parameter.  The pure
# factories above remain directly callable with explicit Settings in tests.
def provide_content_provider():
    return get_content_provider()


def provide_preference_analysis_provider():
    return get_preference_analysis_provider()


def provide_plan_regeneration_preview_provider():
    return get_plan_regeneration_preview_provider()


def provide_place_provider():
    return get_place_provider()


def provide_route_provider():
    """Resolved once per HTTP request, so the route cache never outlives it."""
    settings = get_settings()
    provider = get_route_provider(settings)
    if isinstance(provider, UnavailableRouteProvider):
        return provider
    return CachedRouteProvider(
        provider,
        max_calls=settings.route_max_calls_per_request,
        max_candidate_calls=settings.route_max_candidate_calls_per_request,
    )


def provide_naver_cafe_evidence_provider():
    return get_naver_cafe_evidence_provider()


def provide_plan_generation_provider():
    return get_plan_generation_provider()


def provide_scene_recognition_provider():
    return get_scene_recognition_provider()
