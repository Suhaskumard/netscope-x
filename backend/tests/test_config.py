"""Phase 08 configuration and secrets tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings, _INSECURE_DEFAULT_SECRET, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_load() -> None:
    settings = Settings()
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 8000
    assert settings.udp_session_idle_timeout_seconds == 30.0


def test_invalid_udp_session_idle_timeout_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(udp_session_idle_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(udp_session_idle_timeout_seconds=-1)


def test_udp_session_idle_timeout_env_var_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETSCOPE_UDP_SESSION_IDLE_TIMEOUT_SECONDS", "45.5")
    settings = get_settings()
    assert settings.udp_session_idle_timeout_seconds == 45.5


def test_invalid_log_level_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="NOT_A_LEVEL")


def test_invalid_port_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(api_port=0)
    with pytest.raises(ValidationError):
        Settings(api_port=70000)


def test_env_var_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETSCOPE_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("NETSCOPE_API_PORT", "9000")
    settings = get_settings()
    assert settings.log_level == "DEBUG"
    assert settings.api_port == 9000


def test_production_rejects_placeholder_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")  # secret_key defaults to the placeholder


def test_production_accepts_real_secret() -> None:
    settings = Settings(environment="production", secret_key="a-real-rotated-secret")
    assert settings.environment == "production"
    assert settings.secret_key.get_secret_value() == "a-real-rotated-secret"


def test_secret_never_appears_in_repr_or_str() -> None:
    settings = Settings(secret_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)


def test_default_placeholder_secret_is_the_documented_value() -> None:
    # Sanity check that the "insecure by design" placeholder used throughout
    # (.env.example, this test suite) is the same constant the production
    # guard checks against -- if these drift apart, the guard is silently
    # weakened.
    settings = Settings()
    assert settings.secret_key.get_secret_value() == _INSECURE_DEFAULT_SECRET


def test_env_test_file_is_picked_up_for_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NETSCOPE_LOG_LEVEL", raising=False)
    monkeypatch.delenv("NETSCOPE_API_PORT", raising=False)
    settings = get_settings(environment_override="test")
    assert settings.environment == "test"
    assert settings.log_level == "WARNING"  # from .env.test, not the development default
    assert settings.api_port == 8001
