import logging

import pytest
from pydantic import ValidationError

from agentic_ai.config import Settings
from agentic_ai.logging_config import configure_logging


def test_settings_load_and_mask_google_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-secret")

    settings = Settings(_env_file=None)

    assert settings.google_api_key is not None
    assert settings.google_api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)
    assert settings.google_model == "gemini-3.8-flash"


def test_settings_reject_blank_google_model():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, google_model=" ")


def test_settings_reject_invalid_log_level(monkeypatch):
    monkeypatch.setenv("APP_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_blank_optional_integration_settings_are_unset():
    settings = Settings(
        _env_file=None,
        google_api_key=" ",
        github_mcp_url="",
        database_url="",
    )

    assert settings.google_api_key is None
    assert settings.github_mcp_url is None
    assert settings.database_url is None


def test_settings_reject_invalid_github_mcp_url():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, github_mcp_url="not-a-url")


def test_github_settings_mask_token_and_normalize_allowlist():
    settings = Settings(
        _env_file=None,
        github_mcp_token="test-github-token",
        github_allowed_repositories=[" Octo/Project "],
    )

    assert "test-github-token" not in repr(settings)
    assert settings.github_allowed_repositories == {"octo/project"}


def test_github_settings_reject_invalid_allowlist_entry():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, github_allowed_repositories=["project"])


def test_configure_logging_uses_configured_level(monkeypatch):
    captured = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: captured.update(kwargs))

    configure_logging(Settings(app_log_level="DEBUG", _env_file=None))

    assert captured["level"] == "DEBUG"