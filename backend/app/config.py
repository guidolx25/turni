"""Application configuration (spec §11: config via env)."""

from __future__ import annotations

import enum

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(enum.StrEnum):
    """Deployment environment. Only `dev` may fall back to insecure defaults."""

    DEV = "dev"
    PROD = "prod"


# Publicly known, therefore usable only when ENV=dev. Prod refuses to boot
# without a real SECRET_KEY rather than signing real sessions with this.
DEV_INSECURE_SECRET_KEY = "dev-insecure-change-me"

# Below this a HMAC key is not worth signing with; `secrets.token_urlsafe(32)`
# produces 43 chars and is the intended way to generate one.
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    """Env-driven settings (spec §11)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Environment = Environment.DEV

    # Empty means "unset": resolved below to the dev fallback, or fatal in prod.
    secret_key: str = ""
    # spec §11: SQLite on a persistent volume in production; a local file in dev.
    database_url: str = "sqlite:///./turni.db"
    # spec §4: ships false in v1; the state machine exists behind it.
    require_admin_approval: bool = False
    # spec §3: Europe/Rome for ALL scheduling logic. Store UTC, convert at edges.
    tz: str = "Europe/Rome"

    # --- session cookie (§7) ---
    session_cookie_name: str = "turni_session"
    # Spec is silent on session lifetime. Two weeks: the app's rhythm is weekly
    # (§3), so a shorter TTL would log everyone out between the submissions they
    # actually come here to make.
    session_ttl_hours: int = 24 * 14

    # --- login rate limit (§7 "simple rate-limit on login") ---
    login_max_attempts: int = 10
    login_window_seconds: int = 15 * 60

    @model_validator(mode="after")
    def _resolve_secret_key(self) -> Settings:
        """Fail loudly in prod; stay ergonomic in dev.

        A missing key used to silently resolve to a published constant, which
        meant a misconfigured prod deploy would sign real session cookies with a
        value anyone can read out of this repo. Prod now refuses to start.
        """
        if self.env is Environment.PROD:
            if not self.secret_key:
                raise ValueError("SECRET_KEY is required when ENV=prod")
            if self.secret_key == DEV_INSECURE_SECRET_KEY:
                raise ValueError("SECRET_KEY must not be the development default when ENV=prod")
            if len(self.secret_key) < MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters when ENV=prod"
                )
        elif not self.secret_key:
            self.secret_key = DEV_INSECURE_SECRET_KEY
        return self

    @property
    def cookie_secure(self) -> bool:
        """§7: the session cookie is `Secure` everywhere except local dev, where
        there is no TLS to carry it."""
        return self.env is not Environment.DEV


settings = Settings()
