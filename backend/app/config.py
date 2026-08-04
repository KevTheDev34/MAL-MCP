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
    mal_authorize_url: str = "https://myanimelist.net/v1/oauth2/authorize"
    mal_token_url: str = "https://myanimelist.net/v1/oauth2/token"
    mal_api_base_url: str = "https://api.myanimelist.net/v2"

    token_encryption_key: str = ""

    openai_api_key: str = ""
    openai_model: str = ""

    session_cookie_secure: bool = False
    session_cookie_name: str = "mal_assistant_session"

    plan_expiration_minutes: int = 30
    request_timeout_seconds: int = 15
    oauth_state_expiration_minutes: int = 10
    token_refresh_skew_seconds: int = 60

    def require_mal_oauth_settings(self) -> None:
        """Raise ValueError if required MAL OAuth settings are missing."""
        missing: list[str] = []
        if not self.mal_client_id:
            missing.append("MAL_CLIENT_ID")
        if not self.mal_client_secret:
            missing.append("MAL_CLIENT_SECRET")
        if not self.mal_redirect_uri:
            missing.append("MAL_REDIRECT_URI")
        if not self.token_encryption_key:
            missing.append("TOKEN_ENCRYPTION_KEY")
        if missing:
            raise ValueError(
                "Missing required OAuth configuration: " + ", ".join(missing)
            )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
