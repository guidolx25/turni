"""Application configuration (spec §11: config via env)."""

from __future__ import annotations

import datetime as dt
import enum
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# §7 (v1.11): every API route is mounted under this prefix, and nothing else is.
# Structural, not configurable — the frontend, the vite dev proxy and the SPA
# fallback all encode the same string, so making it an env var would let a
# deployment desynchronise the two halves of one application.
API_PREFIX = "/api"


class Environment(enum.StrEnum):
    """Deployment environment. Only `dev` and `test` may relax production rules.

    `PROD` is the default and the fallback for anything unrecognised — see
    `_coerce_env`. Relaxed behaviour must be *asked for*; it is never inherited
    from a missing, misspelled or empty variable.
    """

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


# The only two spellings that buy an insecure default. Everything else — unset,
# empty, "production", "Prod ", a typo — resolves to PROD.
_RELAXED_ENVIRONMENTS = {
    Environment.DEV.value: Environment.DEV,
    Environment.TEST.value: Environment.TEST,
}


# Publicly known, therefore usable only when ENV=dev. Prod refuses to boot
# without a real SECRET_KEY rather than signing real sessions with this.
DEV_INSECURE_SECRET_KEY = "dev-insecure-change-me"

# Below this a HMAC key is not worth signing with; `secrets.token_urlsafe(32)`
# produces 43 chars and is the intended way to generate one.
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    """Env-driven settings (spec §11)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Defaults to PROD, deliberately. The insecure-default path is opt-in: a
    # deploy that forgets to set ENV gets the hardened behaviour and, without a
    # SECRET_KEY, refuses to boot. The previous default (DEV) meant the reverse —
    # every rule below was gated on a variable nothing in the deployment set, so
    # production silently signed real cookies with the published dev constant.
    env: Environment = Environment.PROD

    # Empty means "unset": resolved below to the dev fallback, or fatal in prod.
    secret_key: str = ""
    # spec §11: SQLite on a persistent volume in production; a local file in dev.
    database_url: str = "sqlite:///./turni.db"
    # §9/§11: the directory holding the built frontend (`npm run build` output).
    # Unset means "do not serve a frontend", which is the dev and test default:
    # in dev the Vite server serves the SPA and proxies the API here, so mounting
    # a stale `dist/` would shadow it. The Dockerfile sets this to /app/static.
    static_dir: Path | None = None
    # spec §4: ships false in v1; the state machine exists behind it.
    #
    # DO NOT enable in v1. §13 defers the admin-approval SURFACE, so `pending_admin`
    # is reachable but has no exit: turning this on parks every accepted swap
    # permanently — the 48 h expiry only sweeps `pending`, and no endpoint approves.
    # The flag is here so the state machine could be built and tested (§4), not so
    # it could be switched on. `app.main` warns loudly at startup if it is.
    require_admin_approval: bool = False
    # spec §3: Europe/Rome for ALL scheduling logic. Store UTC, convert at edges.
    tz: str = "Europe/Rome"

    # --- session cookie (§7) ---
    session_cookie_name: str = "turni_session"
    # Spec is silent on session lifetime. Two weeks: the app's rhythm is weekly
    # (§3), so a shorter TTL would log everyone out between the submissions they
    # actually come here to make.
    session_ttl_hours: int = 24 * 14

    # --- email channel (§10 Channel 2, §11 RESEND_API_KEY) ---
    # Empty means "no email transport": every send is collected in-process by the
    # null transport instead of reaching the network. That is the dev and test
    # default ON PURPOSE — a missing key must degrade to "no email", never to a
    # failed request, because §10 makes email a side effect of a domain event.
    resend_api_key: str = ""
    # Resend requires an RFC 5322 From on every send; §11 does not name it, so it
    # is config with a sandbox default. Deployments must set it to a verified
    # domain or Resend rejects the send (which is logged and swallowed, §10).
    resend_from: str = "Turni <onboarding@resend.dev>"
    # Bounded so a hung Resend call cannot pin a request thread; the send is
    # fire-and-forget from the caller's point of view.
    resend_timeout_seconds: float = 10.0

    # --- login rate limit (§7 "simple rate-limit on login") ---
    login_max_attempts: int = 10
    login_window_seconds: int = 15 * 60

    # --- logging (§11 "structured logs") ---
    log_level: str = "INFO"
    # JSON on by default: §11 asks for structured logs, and the deployment ships
    # them to a collector. A developer at a terminal sets LOG_JSON=false.
    log_json: bool = True

    # --- nightly SQLite backup (§11: "nightly `sqlite3 .backup` ... keep 14") ---
    # Relative to the process CWD by default; §11 puts it on the persistent volume
    # in production, so the deployment sets BACKUP_DIR explicitly.
    backup_dir: Path = Path("backups")
    # §11 names the retention outright.
    backup_keep: int = 14
    # 03:30 Europe/Rome: nowhere near the 17:00 solve/reminder crons (§3), and in
    # the quiet part of a beach establishment's day.
    backup_hour: int = 3
    backup_minute: int = 30

    # --- ICS export slot hours (§7 /export/ics, v1.7) ---
    # Europe/Rome wall-clock bounds of the two §1 slots, used only to give the
    # calendar VEVENTs concrete times. Still deploy-time config per §11 (env
    # ICS_AM_START etc., "HH:MM"), but these are the establishment's REAL hours
    # as of v1.10 — no longer placeholders. They are what appears in each
    # worker's phone calendar, so a wrong value here is wrong for everyone.
    # Nothing in §2 or §8 reads them: changing them moves only what a subscribed
    # calendar displays.
    ics_am_start: dt.time = dt.time(8, 0)
    ics_am_end: dt.time = dt.time(14, 0)
    ics_pm_start: dt.time = dt.time(14, 0)
    ics_pm_end: dt.time = dt.time(20, 0)

    @field_validator("env", mode="before")
    @classmethod
    def _coerce_env(cls, value: object) -> object:
        """Resolve anything that is not an explicit `dev`/`test` to PROD.

        Pydantic's own enum parsing would raise on an unrecognised value. That
        is the wrong failure: `ENV=production` or `ENV=prd` in a host's config UI
        would crash the container with a validation error, and an operator under
        pressure fixes a crash by removing the variable — which, before this
        default was inverted, was the insecure state. Coercing instead means the
        only way to reach a relaxed environment is to name one exactly.
        """
        if value is None:
            return Environment.PROD
        if isinstance(value, Environment):
            return value
        if isinstance(value, str):
            return _RELAXED_ENVIRONMENTS.get(value.strip().lower(), Environment.PROD)
        return Environment.PROD

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
        """§7: the session cookie is `Secure` in production.

        Stated as "is PROD" rather than "is not DEV" so that a new relaxed
        environment cannot inherit `Secure` by accident: `test` drives the app
        over plain http via TestClient, where a `Secure` cookie is set but never
        sent back, and every auth test would fail for a reason unrelated to auth.
        """
        return self.env is Environment.PROD


settings = Settings()
