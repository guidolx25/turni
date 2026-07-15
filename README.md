# Turni

Bilingual (IT/EN) shift-scheduling platform for a beach establishment. Each day
is split into two slots (morning/afternoon), each requiring one lifeguard
(bagnino) and one beach worker (spiaggino). Workers submit availability
constraints during a weekly window; a CP-SAT solver generates the schedule at
the deadline; the schedule then locks, and changes happen only through
peer-approved swaps or admin override.

Full design document: [`docs/shift-scheduler-spec.md`](docs/shift-scheduler-spec.md).

## Features

- Weekly constraint submission (hard/soft, multi-week), closing Sunday 17:00
  Europe/Rome
- Automatic schedule generation via constraint optimization (Google OR-Tools
  CP-SAT), with continuous morning/afternoon alternation across weeks
- Infeasibility resolution flow with explicit worker confirmation
- Locked schedules with peer-to-peer swap requests (role-validated)
- Per-user accounts with worker/admin permission levels, no public signup
- In-app and email notifications; per-user language (IT/EN) and preferences
- ICS calendar export per worker

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x, SQLite, APScheduler,
  OR-Tools
- **Frontend:** React, Vite, Tailwind CSS v4, TypeScript (strict)
- **Email:** Resend

## Development

Backend (uses [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload   # dev server
uv run pytest -q                       # tests
uv run ruff check .                    # lint
```

Frontend:

```bash
cd frontend
npm install
npm run dev                            # dev server
npm run lint && npm run typecheck
npm test
```

## Configuration

Environment variables (see `docs/shift-scheduler-spec.md` §11):

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | session signing |
| `RESEND_API_KEY` | transactional email |
| `REQUIRE_ADMIN_APPROVAL` | swap approval mode (default `false`) |
| `TZ` | must be `Europe/Rome` |

## License

Private project — all rights reserved.
