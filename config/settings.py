"""Application settings from environment variables."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://postgres:postgres@localhost:5433/appdb"
    vllm_base_url: str = "http://localhost:8080/v1"
    vllm_model: str = "Qwen/Qwen3-4B-Instruct"
    cors_origins: list[str] = [
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
    ]
    # Google Calendar OAuth (optional - set in .env for calendar features)
    google_client_id: str = Field(default="", validation_alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", validation_alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/calendar/callback",
        validation_alias="GOOGLE_REDIRECT_URI",
    )
    frontend_url: str = Field(default="http://localhost:3001", validation_alias="FRONTEND_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
