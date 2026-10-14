import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import DatabaseNotConfiguredError, Settings


def test_defaults_and_example_can_load():
    settings = Settings(_env_file=".env.example")
    assert settings.mysql_port == 3306
    assert settings.jwt_access_expire_minutes == 30
    assert settings.ai_api_timeout_seconds == 180
    assert settings.plan_regeneration_preview_ai_timeout_seconds == 240
    assert settings.jwt_refresh_expire_days == 14
    assert settings.cors_origins == []
    assert settings.jwt_secret_key.get_secret_value() == ""
    assert (settings.content_provider, settings.place_provider, settings.plan_provider, settings.preference_provider) == ("mock", "mock", "mock", "mock")
    assert settings.route_provider == "unavailable"
    assert settings.kakao_map_walking_route_mode == "BROAD_FIRST"
    with pytest.raises(DatabaseNotConfiguredError):
        settings.require_mysql_url()


def test_dotenv_loading_and_environment_precedence(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MYSQL_PORT=3307\nJWT_ACCESS_EXPIRE_MINUTES=45\n"
                        "CORS_ALLOWED_ORIGINS=https://frontend.example,http://localhost:8080\n",
                        encoding="utf-8")
    monkeypatch.setenv("MYSQL_PORT", "3308")
    settings = Settings(_env_file=env_file)
    assert settings.mysql_port == 3308
    assert settings.jwt_access_expire_minutes == 45
    assert settings.cors_origins == ["https://frontend.example", "http://localhost:8080"]


def test_cors_parsing_ignores_empty_entries_and_duplicates():
    settings = Settings(cors_allowed_origins=" https://frontend.example, ,http://localhost:8080,https://frontend.example,")
    assert settings.cors_origins == ["https://frontend.example", "http://localhost:8080"]


@pytest.mark.parametrize("origin", ["*", "https://*.example", "null", "ftp://host",
                                        "https://host/path", "https://user:password@host",
                                        "https://host:invalid", "https://host:0"])
def test_invalid_cors_origin_is_rejected(origin):
    with pytest.raises(ValidationError):
        Settings(cors_allowed_origins=origin)


def test_mysql_url_preserves_special_characters_without_connecting():
    # Synthetic unit-test values only. The connection is blocked by conftest.
    password = "unit-test-only:@/%#?"
    settings = Settings(mysql_host="mysql.invalid", mysql_database="unit_test",
                        mysql_user="unit_test", mysql_password=password)
    url = settings.require_mysql_url()
    assert url.drivername == "mysql+pymysql"
    assert url.query["charset"] == "utf8mb4"
    assert make_url(url.render_as_string(hide_password=False)).password == password
    assert password not in repr(settings)
    assert password not in str(url)


@pytest.mark.parametrize("field", ["mysql_host", "mysql_database", "mysql_user", "mysql_password"])
def test_partial_mysql_configuration_fails_before_connecting(field):
    values = dict(mysql_host="mysql.invalid", mysql_database="unit_test",
                  mysql_user="unit_test", mysql_password="unit-test-only")
    values[field] = ""
    with pytest.raises(DatabaseNotConfiguredError, match=field.upper()):
        Settings(**values).require_mysql_url()


@pytest.mark.parametrize("field,value", [("mysql_port", 0), ("mysql_port", 65536),
    ("jwt_access_expire_minutes", 0), ("jwt_refresh_expire_days", -1),
    ("external_api_timeout_seconds", 0), ("ai_api_timeout_seconds", -1),
    ("plan_regeneration_preview_ai_timeout_seconds", 0)])
def test_invalid_numeric_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize("field", ["content_provider", "place_provider", "plan_provider", "preference_provider", "route_provider"])
def test_invalid_provider_mode_is_rejected(field):
    with pytest.raises(ValidationError):
        Settings(**{field: "unsupported"})


def test_invalid_kakao_walk_route_mode_is_rejected():
    with pytest.raises(ValidationError):
        Settings(kakao_map_walking_route_mode="unsupported")
