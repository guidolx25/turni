# Deploying Turni

The app is one container: FastAPI serves the API *and* the built frontend, with
APScheduler running the §3 crons in-process (spec §9, §11). There is nothing
else to run — no separate worker, no external database.

## What the host must provide (spec §11)

Any platform meeting these works. The spec deliberately states requirements
rather than naming a vendor.

| Requirement | Why it is not optional |
|---|---|
| Builds the repo `Dockerfile` | Multi-stage: the frontend is built and copied into the image |
| A **persistent volume** at `/data` | SQLite *is* the database — container-local storage loses every schedule on redeploy |
| **Exactly one instance, never autoscaled** | SQLite has one writer, and APScheduler runs in-process: a second instance means two Sunday solves, two nightly backups, and two processes writing one file |
| Secret injection | `SECRET_KEY`, `RESEND_API_KEY` |
| HTTP health check on `/healthz` | Returns 503 when the database is unreachable — which is what catches a volume that failed to mount |
| A **known proxy peer address** | See the rate-limit warning below. This is the one setting you must verify per host |

## Configuration

Set as secrets:

| Variable | Notes |
|---|---|
| `SECRET_KEY` | Required. The app refuses to start in production without it. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `RESEND_API_KEY` | Optional. Unset ⇒ email is silently skipped and only in-app notifications fire (§10). Nothing breaks |

Set as plain env:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `sqlite:////data/turni.db` |
| `BACKUP_DIR` | `/data/backups` |
| `STATIC_DIR` | `/app/static` |
| `TZ` | `Europe/Rome` |
| `RESEND_FROM` | A verified sender on your Resend domain |
| `FORWARDED_ALLOW_IPS` | **The proxy's address — never `*`.** See below |
| `ICS_AM_START` / `ICS_AM_END` / `ICS_PM_START` / `ICS_PM_END` | The establishment's real opening hours, `HH:MM` Europe/Rome. **The defaults (09:00–14:00 / 14:00–19:00) are placeholders** and are what appears in every worker's phone calendar |

### `FORWARDED_ALLOW_IPS` — read this one

The §7 login rate limit is per-IP, read from `request.client.host`. Behind a
proxy that address is *the proxy*, for every request — so the limit collapses
into a single global bucket and one attacker locks out everybody. `--proxy-headers`
fixes that by reading `X-Forwarded-For` instead.

But `X-Forwarded-For` is a client-supplied header. Trusting it from *any* peer
(`FORWARDED_ALLOW_IPS=*`) means an attacker forges a new IP per request and the
limit stops existing. So it must name the proxy and nothing else.

The correct value is host-specific. After the first deploy, check the logs for
the peer address the app actually sees and pin it. Until you have verified it,
leaving the variable unset is the safe failure: uvicorn trusts nobody, the limit
stays global (annoying) rather than spoofable (dangerous).

## Northflank

1. **Create a service** → *Build from Git* → point at this repo, Dockerfile at
   the repo root.
2. **Port**: `8000`, HTTP, public.
3. **Volume**: create one and mount it at `/data`. Small is fine — this is a
   five-person schedule; 1 GB is generous.
4. **Instances**: exactly 1. Disable any autoscaling.
5. **Env & secrets**: as in the tables above.
6. **Health check**: HTTP `GET /healthz`, expect 200, with a grace period of
   ~20 s so first-boot migrations finish before the first probe.
7. Deploy, then run the smoke test below.

Northflank fronts services with its own proxy, so `FORWARDED_ALLOW_IPS` needs
the internal peer address — take it from the logs after the first request rather
than guessing.

## Fly.io

`fly.toml` in the repo root is a ready-made config for this shape (single
machine, `turni_data` volume at `/data`, health check, autoscaling off).

```bash
fly launch --no-deploy          # claims the app name, keeps the committed fly.toml
fly volumes create turni_data --size 1 --region fra
fly secrets set SECRET_KEY="…" RESEND_API_KEY="…"
fly deploy
```

## First run

Migrations run automatically at container start (`alembic upgrade head` in the
`CMD`) — deliberately at boot rather than at build, because the volume only
exists at runtime.

Then seed the accounts (§5: no public signup; root seeds them):

```bash
# Northflank: use the service shell. Fly: fly ssh console.
cd /app && uv run python -m app.seed
```

The seed prints generated passwords **once**. Save them, distribute them, and
have each person change theirs in Settings.

## Smoke test (§12 Phase 6 gate)

```bash
scripts/smoke-test.sh https://your-url worker_username 'their-password'
```

Read-only and re-runnable. It asserts the app is up, the SPA is served from the
same origin, anonymous access is refused, login works, and — the two that would
be worst to get wrong in production — that root stays invisible to a non-root
caller and that no response leaks `is_root` or another user's calendar token.

## Backups

The nightly job writes `turni-YYYYMMDD-HHMMSS.db` into `BACKUP_DIR` using
SQLite's online backup API (not a file copy, which can tear under a concurrent
write) and prunes to the 14 most recent (§11).

They live on the same volume as the database, which protects against corruption
and bad writes but **not** against losing the volume. If this data matters,
periodically copy one off-host — the whole database is a single small file.
