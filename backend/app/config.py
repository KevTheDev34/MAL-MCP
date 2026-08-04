"""Application configuration via environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str = "replace_me"
    database_url: str = "sqlite:///./mal_assistant.db"
    log_level: str = "INFO"

    mal_client_id: str = ""
    mal_client_secret: str = ""
    mal_redirect_uri: str = "http://localhost:8000/auth/mal/callback"

    token_encryption_key: str = ""

    openai_api_key: str = ""
    openai_model: str = ""

    session_cookie_secure: bool = False
    session_cookie_name: str = "mal_assistant_session"

    plan_expiration_minutes: int = 30
    request_timeout_seconds: int = 15


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
