import pytest

from app.core.config import Settings


def test_defaults_match_docker_compose() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url.endswith("@localhost:5433/echosing")
    assert settings.redis_url == "redis://localhost:6379/0"


def test_env_vars_with_prefix_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECHOSING_REDIS_URL", "redis://example:6380/1")
    monkeypatch.setenv("ECHOSING_HEALTH_CHECK_TIMEOUT_S", "0.25")

    settings = Settings(_env_file=None)

    assert settings.redis_url == "redis://example:6380/1"
    assert settings.health_check_timeout_s == 0.25
