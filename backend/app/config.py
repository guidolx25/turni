"""Application configuration (spec §11: config via env)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-driven settings. Phase 0 carries only what the scaffold needs;
    later phases extend this (RESEND_API_KEY, weights, etc.)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-insecure-change-me"
    # spec §11: SQLite on a persistent volume in production; a local file in dev.
    database_url: str = "sqlite:///./turni.db"
    # spec §4: ships false in v1; the state machine exists behind it.
    require_admin_approval: bool = False
    # spec §3: Europe/Rome for ALL scheduling logic. Store UTC, convert at edges.
    tz: str = "Europe/Rome"


settings = Settings()
