# Turni — Shift Scheduler Specification

**Version:** 1.2 (2026-07-15) · **Status:** Approved for build
**Source of truth for this build. Any deviation requires updating this document first.**

---

## 1. Overview

A bilingual (IT/EN) web platform that schedules weekly shifts for a beach establishment. Each day has two slots (morning `AM`, afternoon `PM`). Every slot requires one **bagnino** (lifeguard) and one **spiaggino** (beach worker). Workers submit availability constraints during an open window; a CP-SAT solver generates the schedule at the deadline; the schedule locks; changes afterward happen only through peer-approved swaps or admin override.

**People:**

| Person | Role(s) | System role |
|---|---|---|
| Matteo | Bagnino | worker + hidden **root** admin |
| Francesco | Bagnino | worker |
| Pasha | Spiaggino | worker |
| Amir | Spiaggino | worker |
| Mattia | Jolly (both roles) | worker + visible **admin** |

---

## 2. Scheduling rules

### 2.1 Hard constraints (never violated; infeasibility triggers the sacrifice flow)

- **H1 — Coverage (Mon–Fri):** every slot has exactly one bagnino ∈ {Matteo, Francesco, Mattia} and exactly one spiaggino ∈ {Pasha, Amir, Mattia}.
- **H2 — One role per slot:** a person occupies at most one role in a given slot (Mattia cannot be bagnino and spiaggino simultaneously).
- **H3 — Free day:** each core worker (Matteo, Francesco, Pasha, Amir) has exactly **one** free day per week, restricted to **Mon–Thu**. On the free day they work zero slots.
- **H4 — One slot per working day:** on non-free weekdays (Mon–Fri), each core worker works exactly one slot (AM xor PM).
- **H5 — Weekend template (fixed, never solved):**
  - Saturday: Matteo AM, Francesco PM (bagnini); Pasha and Amir full-day.
  - Sunday: Francesco AM, Matteo PM (bagnini); Pasha and Amir full-day.
  - Weekend assignments are emitted as locked rows and are modifiable only via post-lock swap (bagnino↔bagnino) or admin override.
- **H6 — Mattia coverage:** Mattia fills every Mon–Fri slot left open by free days. He may work both slots of the same day, in either role (per H2, different roles only across different slots or the same role twice).
- **H7 — Hard personal constraints:** user-submitted hard unavailabilities (slot-level or day-level) must be satisfied. Applies to all five workers including Mattia.

### 2.2 Soft objectives (lexicographic priority, implemented as well-separated weights)

1. **S1 — Soft personal requests** (weight `W1`): satisfy user-submitted soft unavailabilities.
2. **S2 — Alternation + AM/PM fairness** (weight `W2`, one combined tier):
   - *Alternation (continuous flow):* penalty for each pair of consecutive worked days with the same slot, **including the boundary with the previous week** (each worker's last worked slot is persisted in `solver_state`). Note: the fixed weekend seeds Monday — Matteo exits Sunday on PM (prefers Mon AM), Francesco exits on AM (prefers Mon PM).
   - *Fairness:* penalty on |#AM − #PM| per worker per week.
3. **S3 — Mattia free-day clustering** (weight `W3`): **prefer pairing** core workers' free days on the same day(s), so Mattia doubles on fewer days and gets full days off (observed pattern: two pairs → two Mattia full days off, typically Tuesday). Do **not** hardcode a preferred day. `W3` must be an easily editable named constant with a comment noting this tier is expected to change.

Weight separation: `W1 >> W2 >> W3` (e.g., 10 000 / 100 / 1). Document in code.

### 2.3 Sacrifice flow (infeasibility resolution)

1. Solver returns INFEASIBLE → identify the blocking hard constraint set via CP-SAT **assumption literals** (`sufficient_assumptions_for_infeasibility`).
2. If the conflict involves a core worker's hard slot request colliding with free-day placement: propose to **that worker**: *"No feasible schedule. Move your free day to {day}?"* (in-app + email, requires explicit accept/decline).
3. On accept → re-solve with the free day pinned. On decline → escalate to admin (Mattia) with the conflict explanation.
4. Never resolve silently.

---

## 3. Weekly lifecycle

Timezone: **Europe/Rome** everywhere.

1. **Open window:** constraints may be submitted for any future week (multi-week supported), each week's window closes **Sunday 17:00** before that week starts. Submission is an **upsert** on `(user, week, day, slot)`; within a day the `full_day` slot and the `am`/`pm` slots are mutually exclusive — writing `full_day` replaces any `am`/`pm` rows for that day, and writing `am`/`pm` replaces a `full_day` row for that day.
2. **Solve:** scheduled job (APScheduler cron, Sun 17:00) runs the solver for the upcoming week. Admin/root also have a manual **"Generate now"** button (marks window closed early — confirmation required).
3. **Publish + lock:** schedule becomes visible to all, slots lock, notification fan-out.
4. **Post-lock:** changes only via swap requests (§4) or admin override (§5).

---

## 4. Swaps

- Worker A selects one of their locked slots + a target slot of worker B → creates `swap_request`.
- **Role-valid only:** bagnino↔bagnino, spiaggino↔spiaggino. Mattia matches either role. A swap must not violate H2–H4 for either party (validated server-side before creation and again at acceptance).
- B accepts → slots exchange atomically, both parties + admin notified, audit-logged. B rejects or 48 h timeout → request expires.
- `REQUIRE_ADMIN_APPROVAL` config flag, default `false`. When `true`, an accepted swap enters `pending_admin` before applying. Build the state machine now; ship with the flag off.

---

## 5. Roles & permissions

| Capability | Worker | Admin (Mattia) | Root (Matteo) |
|---|---|---|---|
| Submit/edit own constraints (open weeks) | ✅ | ✅ | ✅ |
| View schedule, request/accept swaps | ✅ | ✅ | ✅ |
| Trigger solve / regenerate | — | ✅ | ✅ |
| Override locked slots | — | ✅ | ✅ |
| View all constraint submissions | — | ✅ | ✅ |
| View audit log | — | ✅ | ✅ |
| Create/disable users, reset passwords | — | — | ✅ |
| See the root account anywhere in UI | — | — | ✅ |

Root is a normal user row with `is_root = true`: hidden from user lists, worker pickers, and notification recipients-by-role; visible only to itself. Root inherits all admin capabilities.

No public signup. Root seeds the accounts (5 workers + root; Matteo may be a single account holding worker+root, or a separate root account — **build decision: single account with `is_root` flag**, simpler; that decision makes it **5 account rows**, not 6).

**Users are never hard-deleted.** Deactivation via `users.active = false` is the only removal: the root panel offers deactivate, not delete. Assignments, swaps and audit rows reference users, and a deletion would either destroy history or leave the audit log lying about who acted. Deactivation is immediate — it revokes the user's open sessions, not just their next login.

---

## 6. Data model (SQLite)

```
users(id, username UNIQUE, password_hash, display_name, role ENUM(bagnino,spiaggino,jolly),
      is_admin BOOL, is_root BOOL, email, email_notifications BOOL,
      language ENUM(it,en), active BOOL, created_at)

sessions(id, user_id, created_at, expires_at)
      -- infrastructure, not domain: the server-side session store behind §7's
      -- signed cookie. Logout deletes the row; expired rows are purged by the
      -- nightly job (§11).

weeks(id, monday_date UNIQUE, status ENUM(open,locked), solved_at, locked_at)

constraints(id, user_id, week_id, day ENUM(mon..sun), slot ENUM(am,pm,full_day),
            kind ENUM(hard,soft), note, created_at, updated_at,
            UNIQUE(user_id, week_id, day, slot))
            -- editable while week.status = open; submission is an upsert (§3)

assignments(id, week_id, day, slot ENUM(am,pm), role ENUM(bagnino,spiaggino),
            user_id, source ENUM(solver,weekend_template,swap,override),
            UNIQUE(week_id, day, slot, role))

swap_requests(id, week_id, from_user, to_user, from_assignment, to_assignment,
              status ENUM(pending,accepted,rejected,expired,pending_admin,applied),
              created_at, resolved_at)

sacrifice_proposals(id, week_id, user_id, proposed_free_day,
                    status ENUM(pending,accepted,declined), conflict_note, created_at)

notifications(id, user_id, event_type, payload JSON, read BOOL, created_at)

audit_log(id, actor_id NULLABLE, action, entity, entity_id, payload JSON, created_at)
      -- actor_id NULL means a system action (cron solve, 48 h swap expiry,
      -- nightly backup) — those transitions are logged too and have no human
      -- actor. There is deliberately no system user row. Users are never
      -- hard-deleted (§5), so a NULL actor_id is never a vanished human.

solver_state(user_id PK, last_worked_slot ENUM(am,pm), last_worked_date)
```

---

## 7. API surface (FastAPI, session-cookie auth)

```
POST   /auth/login            POST /auth/logout           GET /me
PATCH  /me/settings           (language, email_notifications, password change)

-- /me carries the caller's own §5 capabilities as derived booleans, so the
-- frontend knows which panels to render. They are derived from the same matrix
-- the permission dependencies enforce — never a parallel mapping. They appear on
-- /me ONLY: no endpoint returning *other* users exposes them. `is_root` itself
-- is never serialized anywhere (§5: root is visible only to itself).

GET    /weeks                 (statuses, deadlines)
GET    /schedule?week=        (assignments incl. weekend template)
GET    /export/ics            (per-user calendar feed, token-authenticated URL)

GET    /constraints?week=     POST /constraints           DELETE /constraints/{id}
       (multi-week: any week with status=open)

POST   /swaps                 POST /swaps/{id}/accept     POST /swaps/{id}/reject
GET    /swaps?week=

GET    /notifications         POST /notifications/read

POST   /sacrifice/{id}/accept POST /sacrifice/{id}/decline

-- admin --
POST   /admin/solve?week=     POST /admin/override        GET /admin/constraints?week=
GET    /admin/audit

-- root --
GET/POST/PATCH /root/users
```

Auth: `argon2` password hashing, server-side sessions (signed cookie, `HttpOnly`, `SameSite=Lax`), simple rate-limit on login.

---

## 8. Solver (Python, OR-Tools CP-SAT)

**Variables** (Mon–Fri only; weekend is template):

- `free[u][d]` ∈ Bool for core u, d ∈ {Mon..Thu}, with Σ_d free[u][d] = 1.
- `x[u][d][s][r]` ∈ Bool: user u works day d, slot s, role r — restricted to role-compatible (u,r) pairs (Mattia compatible with both).

**Constraints:** direct encodings of H1–H7. Hard personal constraints enter as **assumption literals** so infeasibility explanations name the responsible constraint (feeds the sacrifice flow).

**Objective:** minimize `W1·(unmet soft requests) + W2·(alternation breaks + fairness deviation) + W3·(days on which Mattia works ≥ 1 slot)` — note S3 is expressed as *minimizing Mattia's worked days*, which is equivalent to maximizing his full free days and induces free-day pairing.

**State:** after publish, write each worker's `last_worked_slot`/`last_worked_date` (Sunday PM for Matteo, etc., from the weekend template) into `solver_state`.

**Golden test:** given the free days of the photographed week (Pasha Mon, Francesco+Amir Tue, Matteo Wed) as pinned inputs, the solver must produce a valid schedule matching the photo's coverage structure (Mattia doubling Tuesday, all slots covered, one slot per worker per day). This is the regression anchor.

Solve time expectation: < 1 s (trivial search space). Fail loudly if > 10 s.

---

## 9. Frontend

- **Stack:** React + Vite + Tailwind CSS v4, served as static assets by FastAPI (single deployable). TypeScript strict.
- **Views:** Login · Week schedule (grid: days × slots, role-colored) · My constraints (multi-week picker, hard/soft toggle, note) · Swaps (create/respond) · Notifications (bell + list) · Settings (language, email toggle, password) · Admin panel (solve, override, submissions, audit) · Root panel (users).
- **i18n:** flat key dictionary `it.ts` / `en.ts`, toggle in the header, persisted to `localStorage` *and* to `users.language` (email language follows the user setting). Every user-visible string goes through the dictionary — no hardcoded text. Dates/weekdays localized via `Intl`.
- **Design:** restrained dark palette, deliberate typography — reuse the sensibility from the personal-site work; no component-library default look.

---

## 10. Notifications

Single dispatch abstraction:

```python
notify(user, event_type, payload)  # fans out to every enabled channel
```

- **Channel 1 — in-app:** insert into `notifications`; frontend polls `GET /notifications` every 60 s (SSE optional later).
- **Channel 2 — email:** Resend API, per-user opt-out, templated in the user's language.
- **Channel 3 — PWA push:** *phase-2, not in v1*; the abstraction must allow adding it without touching call sites.

**Events:** `schedule_published`, `swap_requested`, `swap_accepted`, `swap_rejected`, `sacrifice_proposed`, `sacrifice_resolved`, `window_closing_24h` (reminder cron Sat 17:00), `admin_override`.

---

## 11. Deployment & ops

- Single container: FastAPI + APScheduler + built frontend. Host: Fly.io or Railway with a persistent volume for SQLite (+ nightly `sqlite3 .backup` to the volume, keep 14).
- Config via env: `SECRET_KEY`, `RESEND_API_KEY`, `REQUIRE_ADMIN_APPROVAL`, `TZ=Europe/Rome`, weight constants.
- Health endpoint `/healthz`; structured logs; solver runs logged with duration + objective values.

---

## 12. Phased build plan (gate-based)

Each phase ends with: tests green, gate checklist verified manually, commit tagged `phase-N`. Do not start phase N+1 with an open gate.

**Phase 0 — Scaffold.** Repo, FastAPI + Vite monorepo layout, tooling (ruff, pytest, eslint, prettier), CI stub. *Gate:* dev servers run, lint clean.

**Phase 1 — Data + auth.** SQLAlchemy models, migrations, session auth, seed script (5 users — see §5's single-account build decision), role/permission middleware. *Gate:* login/logout works for all roles; root invisible to a non-root user listing.

**Phase 2 — Solver core.** CP-SAT model, weekend template emission, solver_state continuity, assumption-literal infeasibility explanation. **Test-heavy phase:** golden test (photographed week), infeasibility tests, alternation-across-weeks test, Mattia-clustering test. *Gate:* all solver tests pass; golden week reproduced.

**Phase 3 — Constraints lifecycle.** Constraint CRUD (multi-week), window open/close logic, cron solve at Sun 17:00, publish + lock, sacrifice flow end-to-end. *Gate:* full simulated week from submissions → publish, including one forced infeasibility → sacrifice → accept → re-solve.

**Phase 4 — Schedule UI + swaps.** Schedule grid, swap request/accept with server-side validation, `REQUIRE_ADMIN_APPROVAL` state machine (flag off), ICS export. *Gate:* role-invalid swap rejected; valid swap applies atomically and audit-logs.

**Phase 5 — Notifications + i18n.** `notify()` abstraction, in-app bell, Resend integration, all events wired, complete IT/EN dictionaries, language toggle, localized emails. *Gate:* zero hardcoded strings (grep check); every event produces both channels for an opted-in user.

**Phase 6 — Admin/root + deploy.** Admin panel (solve, override, submissions, audit view), root user management, backups, deployment to host, smoke test in production. *Gate:* admin override on a locked slot notifies affected workers; production URL live; root account invisible.

---

## 13. Deferred (explicitly out of v1)

- PWA push notifications (Channel 3)
- Admin approval on swaps (flag exists, defaults off)
- Changes to the Mattia-clustering objective (isolated behind `W3`)
- Sunday bagnini rotation logic (weekend is a fixed template; swaps handle exceptions)
