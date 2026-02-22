# config/settings.py

"""Application settings from environment variables."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://postgres:postgres@localhost:5433/appdb"
    vllm_base_url: str = "http://localhost:8080/v1"
    vllm_model: str = "Qwen/Qwen3-4B-Instruct"
    vllm_api_key: str = "EMPTY"
    vllm_connect_timeout_seconds: float = 10.0
    vllm_read_timeout_seconds: float = 180.0
    vllm_write_timeout_seconds: float = 20.0
    vllm_pool_timeout_seconds: float = 10.0
    vllm_max_connections: int = 100
    vllm_max_keepalive_connections: int = 20
    planner_fallback_enabled: bool = False
    backend_internal_api_key: str = ""
    google_maps_api_key: str = ""
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]

    # ── SMTP settings (shared mailbox for invite emails) ─────────────
    smtp_host: str = ""  # e.g. "smtp.gmail.com"
    smtp_port: int = 587  # 587 = TLS (standard)
    smtp_user: str = ""  # e.g. "ketchup.noreply@gmail.com"
    smtp_password: str = ""  # App password (not regular password)
    smtp_from_email: Optional[str] = None  # Defaults to smtp_user if not set

    # ── Frontend URL (for building email links) ──────────────────────
    frontend_url: str = "http://localhost:3001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
