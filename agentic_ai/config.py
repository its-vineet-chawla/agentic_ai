from typing import Literal

from pydantic import AnyHttpUrl, Field, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_api_key: SecretStr | None = None
    google_model: str = "gemini-3.8-flash"
    github_mcp_url: AnyHttpUrl | None = None
    github_mcp_token: SecretStr | None = None
    github_allowed_repositories: set[str] = Field(default_factory=set)
    github_web_url: AnyHttpUrl | None = None
    database_url: SecretStr | None = None
    memory_retention_days: PositiveInt = 90
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator(
        "google_api_key",
        "github_mcp_url",
        "github_mcp_token",
        "github_web_url",
        "database_url",
        mode="before",
    )
    @classmethod
    def normalize_optional_settings(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("google_model")
    @classmethod
    def validate_google_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("GOOGLE_MODEL must not be blank")
        return model

    @field_validator("github_allowed_repositories", mode="before")
    @classmethod
    def normalize_github_repository_allowlist(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",") if value.strip() else []
        if isinstance(value, (list, set, tuple, frozenset)):
            repositories = set()
            for repository in value:
                if not isinstance(repository, str):
                    return value
                repository = repository.strip().casefold()
                if repository.count("/") != 1 or not all(repository.split("/")):
                    raise ValueError("Repositories must use the owner/repository format")
                repositories.add(repository)
            return repositories
        return value