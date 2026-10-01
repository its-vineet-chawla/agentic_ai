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


def test_settings_reject_invalid_log_level(monkeypatch):
    monkeypatch.setenv("APP_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_configure_logging_uses_configured_level(monkeypatch):
    captured = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: captured.update(kwargs))

    configure_logging(Settings(app_log_level="DEBUG", _env_file=None))

    assert captured["level"] == "DEBUG"