"""Environment configuration; no credentials or network access at import time."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ProviderMode = Literal["mock", "real"]
SocialAuthProviderMode = Literal["fake", "real"]
RouteProviderMode = Literal["unavailable", "kakao"]
KakaoWalkRouteMode = Literal["BROAD_FIRST", "SHORTEST", "ACCESSIBLE"]


class DatabaseNotConfiguredError(RuntimeError):
    """Raised before any connection when required MySQL settings are absent."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    mysql_host: str = ""
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = ""
    mysql_user: str = ""
    mysql_password: SecretStr = SecretStr("")
    cors_allowed_origins: str = ""

    jwt_secret_key: SecretStr = SecretStr("")
    jwt_access_expire_minutes: int = Field(default=30, gt=0)
    jwt_refresh_expire_days: int = Field(default=14, gt=0)

    content_provider: ProviderMode = "mock"
    place_provider: ProviderMode = "mock"
    plan_provider: ProviderMode = "mock"
    preference_provider: ProviderMode = "mock"
    scene_recognition_provider: ProviderMode = "mock"
    social_auth_provider: SocialAuthProviderMode = "fake"
    route_provider: RouteProviderMode = "unavailable"

    kakao_rest_api_key: SecretStr = SecretStr("")
    kakao_client_secret: SecretStr = SecretStr("")
    kakao_mobility_base_url: str = "https://apis-navi.kakaomobility.com"
    kakao_map_base_url: str = "https://dapi.kakao.com"
    kakao_map_walking_route_mode: KakaoWalkRouteMode = "BROAD_FIRST"
    # Real route lookups per HTTP request; candidate filtering gets the smaller share.
    route_max_calls_per_request: int = Field(default=40, ge=0)
    route_max_candidate_calls_per_request: int = Field(default=16, ge=0)
    naver_client_id: str = ""
    naver_client_secret: SecretStr = SecretStr("")
    naver_redirect_uri: str = ""
    # Deliberately separate from NAVER Login OAuth credentials above.
    naver_api_hub_client_id: str = ""
    naver_api_hub_client_secret: SecretStr = SecretStr("")
    youtube_api_key: SecretStr = SecretStr("")
    tour_api_key: SecretStr = SecretStr("")
    tour_api_base_url: str = ""
    kma_api_key: SecretStr = SecretStr("")
    kma_api_base_url: str = ""
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = ""
    gemini_fallback_model: str = ""
    exaone_api_key: SecretStr = SecretStr("")
    exaone_base_url: str = ""
    exaone_model: str = ""
    exaone_num_ctx: int = Field(default=8192, ge=2048)
    external_api_timeout_seconds: float = Field(default=10, gt=0)
    # A Tour hours lookup issues detailCommon2 + detailIntro2; image data is not fetched.
    tour_hours_max_places_per_request: int = Field(default=8, ge=0, le=30)
    # Real EXAONE 7.8B plans measured 133--144 seconds for successful
    # multi-day runs.  The provider still bounds output and retries only once;
    # 180 seconds prevents the old 60-second default from rejecting normal
    # responses before those safeguards can work.
    ai_api_timeout_seconds: float = Field(default=180, gt=0)
    # Preview regeneration has a separate, conservative ceiling because it
    # carries the existing itinerary and can be slower than a fresh plan.
    # It must not change the timeout of other EXAONE-backed features.
    plan_regeneration_preview_ai_timeout_seconds: float = Field(default=240, gt=0)
    # Opt-in: a folder for sanitised EXAONE plan answers used by replay tests
    # (plan_ai_fixture). Unset means nothing is ever written.
    plan_ai_fixture_dir: str | None = None
    plan_regeneration_preview_ttl_minutes: int = Field(default=30, gt=0, le=1440)
    # Meal start-time windows (HH:MM-HH:MM) the server checks plans against.
    plan_breakfast_window: str = "07:00-09:30"
    plan_lunch_window: str = "11:00-14:00"
    plan_dinner_window: str = "17:00-20:00"
    # Optional public origin for share links; the request's own origin is used when empty.
    public_share_base_url: str = ""

    @field_validator("mysql_host", "mysql_database", "mysql_user")
    @classmethod
    def strip_mysql_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("plan_breakfast_window", "plan_lunch_window", "plan_dinner_window")
    @classmethod
    def validate_meal_window(cls, value: str) -> str:
        from app.services.plan_quality_rules import parse_window

        parse_window(value)
        return value.strip()

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_origins(cls, value: str) -> str:
        for origin in value.split(","):
            origin = origin.strip()
            if not origin:
                continue
            parsed = urlsplit(origin)
            if (
                "*" in origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
            # Also reject malformed ports before the application starts.
            if parsed.port is not None and parsed.port < 1:
                raise ValueError("CORS origin port must be positive")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return list(dict.fromkeys(
            origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()
        ))

    def require_mysql_url(self) -> URL:
        """Build a URL object without guessing values or opening a connection."""
        values = {
            "MYSQL_HOST": self.mysql_host,
            "MYSQL_DATABASE": self.mysql_database,
            "MYSQL_USER": self.mysql_user,
            "MYSQL_PASSWORD": self.mysql_password.get_secret_value(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise DatabaseNotConfiguredError(
                "MySQL configuration required: " + ", ".join(missing)
            )
        return URL.create(
            drivername="mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password.get_secret_value(),
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
