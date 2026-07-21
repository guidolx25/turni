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
| `SECRET_KEY` | Required, and enforced: the app refuses to start unless `ENV` is explicitly `dev` or `test`. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `RESEND_API_KEY` | Optional. Unset ⇒ email is silently skipped and only in-app notifications fire (§10). Nothing breaks |

Set as plain env:

| Variable | Value |
|---|---|
| `ENV` | `prod`. The image already sets it, and leaving it unset is equally safe — see below |
| `DATABASE_URL` | `sqlite:////data/turni.db` |
| `BACKUP_DIR` | `/data/backups` |
| `STATIC_DIR` | `/app/static` |
| `TZ` | `Europe/Rome` |
| `RESEND_FROM` | A verified sender on your Resend domain |
| `FORWARDED_ALLOW_IPS` | **The proxy's address — never `*`.** See below |
| `ICS_AM_START` / `ICS_AM_END` / `ICS_PM_START` / `ICS_PM_END` | Only if the hours change. The defaults are the real ones — AM `08:00`–`14:00`, PM `14:00`–`20:00` Europe/Rome — so you can leave these unset |

### `ENV` fails closed

`ENV` defaults to `prod`, and anything that is not exactly `dev` or `test` —
unset, empty, `production`, a typo — resolves to `prod` as well. In that state
`SECRET_KEY` is mandatory and the session cookie is marked `Secure`.

This is inverted from the obvious design on purpose. It used to default to `dev`,
which meant every production rule hung off a variable nothing in the deployment
set: the container ran with a non-`Secure` session cookie and signed real cookies
with `DEV_INSECURE_SECRET_KEY`, a constant published in this repository. The
insecure path is now the one you have to ask for by name.

The practical consequence when deploying: a missing or misspelled `SECRET_KEY`
is a **boot failure**, not a silent downgrade. If the container exits
immediately, read the logs — `SECRET_KEY is required when ENV=prod` is the
expected message and the fix is the secret, never setting `ENV=dev`.

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

### URL layout

One origin serves two things, split by prefix (§7 v1.11):

| Path | Served by |
|---|---|
| `/api/*` | The API. Anything unmatched under it is a JSON 404 |
| `/healthz` | The health endpoint — infrastructure, deliberately outside `/api` |
| `/assets/*` | Hashed frontend bundles |
| everything else | The SPA shell; the client router reads the URL |

The prefix is why nothing here needs a rule about `Accept` headers, cookies or
path rewriting: `/swaps` is a page and `/api/swaps` is an endpoint, and no
component in the request path has to infer which was meant. If you put a CDN or
WAF in front, the only requirement is that it forwards paths unchanged.

The calendar feed is API surface and lives under the prefix —
`/api/export/ics?token=…`. It is the one API URL a worker handles directly
(Settings shows it, they paste it into a calendar app), so it is worth knowing it
moved: any feed URL copied before v1.11 is dead and must be re-copied.

## First run

Migrations run automatically at container start (`alembic upgrade head` in the
`CMD`) — deliberately at boot rather than at build, because the volume only
exists at runtime.

Then seed the accounts (§5: no public signup; root seeds them):

```bash
# Northflank: use the service shell.
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

The nightly job writes `turni-YYYYMMDDTHHMMSSZ.db` (UTC, so the names sort
chronologically) into `BACKUP_DIR` using
SQLite's online backup API (not a file copy, which can tear under a concurrent
write) and prunes to the 14 most recent (§11).

They live on the same volume as the database, which protects against corruption
and bad writes but **not** against losing the volume. If this data matters,
periodically copy one off-host — the whole database is a single small file.
