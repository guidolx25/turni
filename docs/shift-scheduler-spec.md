# Turni — Shift Scheduler Specification

**Version:** 1.7 (2026-07-21) · **Status:** Approved for build
**v1.5:** §6 `sacrifice_proposals.conflict_note` (prose) → `conflict` (structured
§8 unsat core, `[{worker_id, day, slot}]`), so conflicts localize at render time (§9).
**v1.6:** the accepted `sacrifice_proposals` row is the §2.1 H3 **grant of record** —
every solve of a week carries the grants from its accepted proposals; §6 adds
`UNIQUE(week_id, user_id)` on `sacrifice_proposals`.
**v1.7:** §6 `users` gains `ics_token UNIQUE` — the §7 `/export/ics` bearer
credential: per-user, random, regenerable (revocation is per-user, never a
SECRET_KEY rotation).
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

  **Sacrifice grant (§2.3).** The Mon–Thu restriction is the *default* domain, not the whole rule. The domain is parameterized by an optional per-worker **sacrifice grant**: for a worker holding a grant for day `g`, the free-day domain is **Mon–Thu ∪ {g}**. A grant is issued only by the §2.3 sacrifice flow, only for the day named in the blocking hard constraint, and only for the week in question — never by a normal solve, where every domain is exactly Mon–Thu. Exactly one free day still holds (H3's cardinality is untouched); the grant widens *where* it may fall, and nothing else.

  **Grant of record (v1.6).** An accepted grant is durable for its week: the accepted §6 `sacrifice_proposals` row *is* the grant of record, and **every** solve of that week — cron, manual, regenerate, the accept re-solve itself — reads the week's accepted proposals and carries their grants. A grant never evaporates with the call that created it, so an accepted week cannot relapse into INFEASIBLE for the conflict it already resolved; a later infeasibility implicates a *different* core and iterates the §2.3 flow toward a different worker.
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
   - *Rest spread (full-weekend workers)* (weight `W2_SPREAD`, in the S2 band): penalty for each pair of workers who work the full weekend template — both Saturday and Sunday full-day, i.e. the two full-day spiaggini — that shares the same free day, so their role is never left covered by the jolly alone for a whole day. `W2_SPREAD` is sized so that co-locating such a pair is dispreferred to the one alternation break splitting them incurs (and thus also outweighs the S3 clustering pull below). Name-agnostic: the pair is selected by weekend-template membership, never by identity. Empirically confirmed across observed weeks — the two full-weekend workers always split their free days (one Monday, one Tuesday) rather than both resting Monday, accepting that the jolly may work an extra day.
3. **S3 — Mattia free-day clustering** (weight `W3`): **prefer pairing** core workers' free days on the same day(s), so Mattia doubles on fewer days and gets full days off (observed pattern: two pairs → two Mattia full days off, typically Tuesday). Do **not** hardcode a preferred day. This general pairing preference yields to the S2 rest-spread term above for the two full-weekend workers, who are spread rather than clustered. `W3` must be an easily editable named constant with a comment noting this tier is expected to change.

Weight separation: `W1 >> {W2, W2_SPREAD} >> W3` (e.g., 10 000 / 100 / 200 / 1 — `W2_SPREAD` sits in the S2 band: above a single `W2` alternation unit but far below `W1`). Document in code.

### 2.3 Sacrifice flow (infeasibility resolution)

1. Solver returns INFEASIBLE → identify the blocking hard constraint set via CP-SAT **assumption literals** (`sufficient_assumptions_for_infeasibility`).
2. If the conflict involves a core worker's hard slot request colliding with free-day placement: propose to **that worker**: *"No feasible schedule. Move your free day to {day}?"* (in-app + email, requires explicit accept/decline).
3. On accept → re-solve with the free day pinned. On decline → escalate to admin (Mattia) with the conflict explanation.
4. Never resolve silently.

**What is being traded.** The worker sacrifices their *weekday free-day placement*, never their hard request. H7 is inviolable: an accepted proposal still honors the hard unavailability in full — the worker asked to be off day `{day}` and is off day `{day}`, having given up the Mon–Thu free day they would otherwise have taken. A proposal never withdraws, downgrades, or supersedes the request that caused the conflict.

**Mechanics — domain extension, not a bare pin.** The probe in step 2 and the re-solve in step 3 both carry a **sacrifice grant** (H3) extending that one worker's free-day domain to the conflicted day: `Mon–Thu ∪ {day}`. This is load-bearing and must not be reduced to pinning a free day inside Mon–Thu. A pin alone only *adds* `free[u][d] = 1` to an otherwise unchanged model, so the probe's feasible region would be a subset of the plain solve's — an INFEASIBLE week would stay INFEASIBLE under every pin and step 2 could never fire. The grant is what makes the propose branch reachable at all.

**Corollary — Friday is the only reachable sacrifice day.** A proposal fires **iff** the unsat core implicates a hard constraint on a **Friday**, held by a **core** worker who has not already answered a proposal for this week (§2.3 step 3 never re-offers), and the Friday-extended probe is feasible. The other days are unreachable by construction:
- **Mon–Thu** — a grant is a no-op there. The day is already inside the default domain, so the extended probe reduces to the plain solve plus a pin, and a pin only *adds* `free[u][d] = 1` to an otherwise unchanged model: its feasible region is a subset of the plain solve's, so an INFEASIBLE week stays INFEASIBLE. This holds for slot-level and full-day requests alike, and is the same monotonicity argument as the Mechanics paragraph above. Such a conflict escalates (step 3).
- **Sat/Sun** — H5 makes the weekend a fixed template with no solver variables, so no free-day move can absorb a weekend request. These escalate to the admin at submission time instead (§10 `weekend_hard_escalated`).
- **Friday** — the sole day that H4 forces worked but H3's default domain cannot free. Hence the only day where extending the domain changes the outcome.

A Friday conflict whose extended probe is *still* infeasible produces no proposal and escalates (step 3) like any other.

---

## 3. Weekly lifecycle

Timezone: **Europe/Rome** everywhere.

1. **Open window** (`status=open`)**:** constraints may be submitted for any future week (multi-week supported), each week's window closes **Sunday 17:00** before that week starts. Submission is an **upsert** on `(user, week, day, slot)`; within a day the `full_day` slot and the `am`/`pm` slots are mutually exclusive — writing `full_day` replaces any `am`/`pm` rows for that day, and writing `am`/`pm` replaces a `full_day` row for that day.
2. **Solve** (→ `status=solved`)**:** the scheduled job (APScheduler cron, Sun 17:00) runs the solver for the upcoming week; admin/root also have a manual **"Generate now"** button (marks the window closed early — confirmation required). Running the solver moves the week to `solved` — the window is closed and a schedule may be computed, but it is **not yet visible and no notifications fire**. Schedule visibility and fan-out key off `locked`, never `solved`.
3. **Publish + lock** (→ `status=locked`)**:** publishing makes the schedule **visible to all**, locks the slots, and fans out notifications (§10). Two paths reach it:
   - **Cron — atomic:** a feasible scheduled solve publishes immediately (solve+publish in one Sunday-17:00 automation), *unless* a sacrifice is pending — see below.
   - **Manual — solve → review → publish:** an admin "Generate now" leaves the week in `solved` for review; publishing is a separate, explicit step (`POST /admin/publish`, §7).
   - **Sacrifice pending:** when a solve is INFEASIBLE the §2.3 sacrifice flow opens and the week **parks in `solved`** — never published with an unresolved conflict — and **auto-publishes once the sacrifice is resolved** (accepted and the re-solve is feasible). A declined/escalated proposal leaves the week in `solved` for the admin to resolve (§2.3, §5 override).
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
      language ENUM(it,en), ics_token UNIQUE, active BOOL, created_at)
      -- ics_token (v1.7): the §7 /export/ics bearer credential — per-user,
      -- random, opaque, regenerable. Revoking a leaked feed URL is a per-user
      -- regeneration, never a SECRET_KEY rotation. Never serialized to anyone
      -- but its own user.

sessions(id, user_id, created_at, expires_at)
      -- infrastructure, not domain: the server-side session store behind §7's
      -- signed cookie. Logout deletes the row; expired rows are purged by the
      -- nightly job (§11).

weeks(id, monday_date UNIQUE, status ENUM(open,solved,locked), solved_at, locked_at)
      -- open   = submission window open, constraints editable (§3.1)
      -- solved = window closed, solver has run; schedule computed but NOT yet
      --          visible/published, OR a §2.3 sacrifice is pending. Reached by a
      --          manual "Generate now" (awaits review) or by any solve that opens
      --          the sacrifice flow. Visibility and fan-out never key off this
      --          state — only `locked` (§3.2/§3.3).
      -- locked = published: schedule visible to all, slots locked (§3.3)

constraints(id, user_id, week_id, day ENUM(mon..sun), slot ENUM(am,pm,full_day),
            kind ENUM(hard,soft), note, created_at, updated_at,
            UNIQUE(user_id, week_id, day, slot))
            -- editable while week.status = open; submission is an upsert (§3)

assignments(id, week_id, day, slot ENUM(am,pm), role ENUM(bagnino,spiaggino),
            user_id, source ENUM(solver,weekend_template,swap,override),
            UNIQUE(week_id, day, slot, role) WHERE day IN (mon..fri))
            -- Weekday-only uniqueness: H1 gives exactly one holder per role per
            -- Mon–Fri slot. The H5 weekend template deliberately has TWO
            -- spiaggini per slot (Pasha and Amir full-day Sat+Sun), which that
            -- key would forbid, so weekend rows are exempt; their integrity comes
            -- from emit_weekend_template being the sole writer of them.

swap_requests(id, week_id, from_user, to_user, from_assignment, to_assignment,
              status ENUM(pending,accepted,rejected,expired,pending_admin,applied),
              created_at, resolved_at)

sacrifice_proposals(id, week_id, user_id, proposed_free_day,
                    status ENUM(pending,accepted,declined), conflict JSON, created_at,
                    UNIQUE(week_id, user_id))
                    -- conflict: the §8 minimal unsat core as data — a list of
                    -- {worker_id, day, slot} items for the blocking hard
                    -- requests. Rendered in the viewer's language by the §9
                    -- dictionaries; never stored as a pre-formatted sentence.
                    -- UNIQUE(week_id, user_id) (v1.6): one proposal per worker
                    -- per week — safe by construction (§2.3: Friday is the only
                    -- reachable sacrifice day) and load-bearing, because the
                    -- ACCEPTED row is the §2.1 H3 grant of record.

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
GET    /export/ics            (per-user calendar feed; authenticated by the
                               users.ics_token bearer credential (v1.7), compared
                               in constant time — never by session cookie, so
                               calendar apps can poll it)

GET    /constraints?week=     POST /constraints           DELETE /constraints/{id}
       (multi-week: any week with status=open)

POST   /swaps                 POST /swaps/{id}/accept     POST /swaps/{id}/reject
GET    /swaps?week=

GET    /notifications         POST /notifications/read

POST   /sacrifice/{id}/accept POST /sacrifice/{id}/decline

-- admin --
POST   /admin/solve?week=     POST /admin/publish?week=   POST /admin/override
GET    /admin/constraints?week=   GET /admin/audit
       -- solve runs the solver (→ status=solved); publish locks a solved week
       -- (→ status=locked) and fans out (§3.2/§3.3). They are distinct steps:
       -- an INFEASIBLE solve can never publish, and the manual path reviews the
       -- solved schedule before publishing.

-- root --
GET/POST/PATCH /root/users
```

Auth: `argon2` password hashing, server-side sessions (signed cookie, `HttpOnly`, `SameSite=Lax`), simple rate-limit on login.

---

## 8. Solver (Python, OR-Tools CP-SAT)

**Variables** (Mon–Fri only; weekend is template):

- `free[u][d]` ∈ Bool for core u, d ∈ D(u), with Σ_d free[u][d] = 1. The domain `D(u)` is `{Mon..Thu}` for every worker on a normal solve, and `{Mon..Thu} ∪ {g}` for a worker carrying a §2.3 sacrifice grant for day `g` (in practice `g = Fri`; see the §2.3 corollary). The cardinality constraint is unchanged in either case.
- `x[u][d][s][r]` ∈ Bool: user u works day d, slot s, role r — restricted to role-compatible (u,r) pairs (Mattia compatible with both).

**Constraints:** direct encodings of H1–H7. Hard personal constraints enter as **assumption literals** so infeasibility explanations name the responsible constraint (feeds the sacrifice flow).

**Objective:** minimize `W1·(unmet soft requests) + W2·(alternation breaks + fairness deviation) + W2_SPREAD·(full-weekend worker pairs sharing a free day) + W3·(days on which Mattia works ≥ 1 slot)` — note S3 is expressed as *minimizing Mattia's worked days*, which is equivalent to maximizing his full free days and induces free-day pairing (except for the two full-weekend workers, whom the `W2_SPREAD` term spreads apart).

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

**Events:** `schedule_published`, `swap_requested`, `swap_accepted`, `swap_rejected`, `sacrifice_proposed`, `sacrifice_resolved`, `sacrifice_escalated`, `weekend_hard_escalated`, `window_closing_24h` (reminder cron Sat 17:00), `admin_override`.

- `weekend_hard_escalated` (§2.1 H7 / §2.3): fired when a worker submits a **hard** unavailability on Sat/Sun. H5 makes the weekend a fixed template with no solver variables, so no free-day move can absorb such a request and it cannot be honored by solving. The submission is still accepted and recorded; escalating it is what keeps the outcome from being silent (§2.3 step 4). Audience is the **visible admins only** — role-based, so root is excluded (§5) via the same filtered helper every user listing uses. Fires on creation of a hard weekend request (including a soft→hard change), not on re-submission of an already-hard one and not on deletion.
- `sacrifice_escalated` (§2.3): fired when a proposal is declined, or when no free-day move restores coverage. Audience is the **visible admins only** — a role-based fan-out, so root is excluded (§5) via the same filtered helper every user listing uses, never an ad-hoc recipient query. The payload carries the conflict explanation **and the minimal unsat core** (the conflicting hard requests, from the assumption literals of §8) so the admin can act without re-solving. It fires with the week still `solved` (unpublished): escalation triggers **no worker-facing notification and no schedule visibility**.

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
