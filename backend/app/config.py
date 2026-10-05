"""Application configuration, loaded from environment variables / .env.

Nothing secret is hard-coded. The token-encryption key and OAuth client
credentials all come from the environment.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project base dir (…/backend)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", str(BASE_DIR.parent / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Google OAuth ---
    google_client_id: str = ""
    google_client_secret: str = ""
    # Public URL of THIS backend's callback. Must match the redirect URI
    # registered in the Google Cloud console exactly.
    oauth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Where to bounce the browser back to after a successful connect.
    frontend_url: str = "http://localhost:5173"

    # --- Storage of sync state ---
    # Default: a local SQLite file (no server). Override with a Postgres URL
    # (e.g. postgresql+psycopg2://…) and nothing else changes.
    database_url: str = ""
    sqlite_path: str = str(BASE_DIR / "data" / "sync_state.db")

    # --- Token encryption ---
    # Fernet key (urlsafe base64, 32 bytes). If empty, one is generated and
    # written to data/.fernet_key so restarts keep working in dev. In
    # production you MUST set this explicitly so tokens survive redeploys.
    fernet_key: str = ""

    # --- Router / storage safety ---
    # Never fill an account to the brim. Keep this much free (bytes).
    safety_buffer_bytes: int = 512 * 1024 * 1024  # 512 MB
    # Warn in the UI once an account passes this fraction of its quota.
    near_full_threshold: float = 0.90

    # --- Sync worker ---
    worker_poll_seconds: float = 2.0
    max_upload_attempts: int = 3

    # --- AI notes (optional, OFF by default; never blocks sync) ---
    ai_notes_enabled: bool = False
    ai_provider: str = "openai"  # "openai" | "gemini"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://localhost:8000"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.sqlite_path}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
