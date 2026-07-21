/**
 * Wire types mirroring `backend/app/schemas.py` (spec §7).
 * Only the shapes this frontend consumes; enum values are the §6 lowercase
 * strings. `is_root` never appears anywhere (§5) — do not add it.
 */

export type UserRole = 'bagnino' | 'spiaggino' | 'jolly'
export type Language = 'it' | 'en'
export type WeekStatus = 'open' | 'solved' | 'locked'
export type Day = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
export type AssignmentSlot = 'am' | 'pm'
export type AssignmentRole = 'bagnino' | 'spiaggino'
export type AssignmentSource = 'solver' | 'weekend_template' | 'swap' | 'override'
/** §6 constraints.slot — day-level `full_day` on top of the two real slots. */
export type ConstraintSlot = 'am' | 'pm' | 'full_day'
export type ConstraintKind = 'hard' | 'soft'
export type SacrificeStatus = 'pending' | 'accepted' | 'declined'

export const DAY_ORDER: readonly Day[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
/** H5 makes these a fixed template — a hard request here escalates (§10). */
export const WEEKEND_DAYS: readonly Day[] = ['sat', 'sun']

export interface Capabilities {
  trigger_solve: boolean
  override_locked_slots: boolean
  view_all_constraints: boolean
  view_audit_log: boolean
  manage_users: boolean
  see_root_account: boolean
}

export interface UserOut {
  id: number
  username: string
  display_name: string
  role: UserRole
  is_admin: boolean
  email: string | null
  email_notifications: boolean
  language: Language
  active: boolean
}

export interface MeOut extends UserOut {
  capabilities: Capabilities
  // §6 (v1.7): the caller's own /export/ics feed credential. Carried by /me
  // ONLY — never by UserOut, never for another user. The Settings view that
  // surfaces (and regenerates) the feed URL lands in Phase 5 (§9).
  ics_token: string
}

export interface WeekOut {
  monday_date: string // YYYY-MM-DD (Monday)
  status: WeekStatus
  submission_deadline: string // ISO datetime — Sun 17:00 Europe/Rome as an instant
  solved_at: string | null
  locked_at: string | null
}

export interface ScheduleAssignmentOut {
  // `id` is required by the swap-create flow (POST /swaps names assignments by
  // id); the swaps backend work adds it to GET /schedule in this same phase.
  id: number
  day: Day
  slot: AssignmentSlot
  role: AssignmentRole
  user_id: number
  user_name: string
  source: AssignmentSource
}

export interface ScheduleOut {
  monday_date: string
  status: WeekStatus
  assignments: ScheduleAssignmentOut[]
}

export type SwapStatus =
  'pending' | 'accepted' | 'rejected' | 'expired' | 'pending_admin' | 'applied'

export interface SwapAssignmentRef {
  id: number
  day: Day
  slot: AssignmentSlot
  role: AssignmentRole
  user_id: number
}

export interface SwapRequestOut {
  id: number
  week: string // Monday date
  from_user: number
  to_user: number
  from_assignment: SwapAssignmentRef
  to_assignment: SwapAssignmentRef
  status: SwapStatus
  created_at: string
  resolved_at: string | null
}

export interface SwapCreateIn {
  to_user: number
  from_assignment: number
  to_assignment: number
}

export interface LoginIn {
  username: string
  password: string
}

/** §7 `POST /constraints` body — the week is named by its Monday date. */
export interface ConstraintIn {
  week: string
  day: Day
  slot: ConstraintSlot
  kind: ConstraintKind
  note: string | null
}

export interface ConstraintOut {
  id: number
  week: string
  day: Day
  slot: ConstraintSlot
  kind: ConstraintKind
  note: string | null
  created_at: string
  updated_at: string
}

/**
 * §7 `PATCH /me/settings`. Every field optional: the view sends only what the
 * user touched, so a language toggle never re-submits a password.
 */
export interface MeSettingsIn {
  language?: Language
  email_notifications?: boolean
  current_password?: string
  new_password?: string
}

/**
 * §6 (v1.7) `POST /me/ics-token` — the regenerated feed credential. Typed to the
 * one field the Settings view reads; /me is re-fetched for everything else.
 */
export interface IcsTokenOut {
  ics_token: string
}

/**
 * §7 `GET /notifications` (§10 Channel 1). `payload` is DATA, never prose —
 * `unknown`-valued on purpose so every read goes through a validating accessor
 * and an unexpected shape degrades instead of crashing the list.
 */
export interface NotificationOut {
  id: number
  event_type: string
  payload: Record<string, unknown> | null
  read: boolean
  created_at: string
}

/** §7 `POST /notifications/read`. `ids` omitted marks every own row read. */
export interface MarkReadIn {
  ids?: number[]
}

/** One item of the §8 minimal unsat core (§6 sacrifice_proposals.conflict). */
export interface ConflictItem {
  worker_id: number
  day: Day
  slot: ConstraintSlot
}

export interface SacrificeProposalOut {
  id: number
  week: string
  proposed_free_day: Day
  status: SacrificeStatus
  conflict: ConflictItem[] | null
  created_at: string
}

/* -- admin (§7 `-- admin --`) -- */

/** §8 solve outcome. OPTIMAL/FEASIBLE carry the objective; INFEASIBLE the core. */
export type SolverStatus = 'optimal' | 'feasible' | 'infeasible'

export interface ObjectiveBreakdownOut {
  soft_unmet: number
  alternation_breaks: number
  fairness_deviation: number
  weighted_total: number
}

/** One hard request named by the §8 assumption literals as blocking (§2.3). */
export interface BlockingConstraintOut {
  worker_id: number
  day: Day
  slot: ConstraintSlot
  kind: ConstraintKind
}

export interface SolveResultOut {
  // A plain string on the wire: an unrecognised status must render as "unknown",
  // never crash the panel, so the union is narrowed at render time.
  status: string
  solve_seconds: number
  objective: ObjectiveBreakdownOut | null
  blocking_constraints: BlockingConstraintOut[]
}

/**
 * §7 `POST /admin/override` body. The slot is named by its §6 natural key;
 * `assignment_id` disambiguates the H5 weekend slots, which seat two spiaggini
 * and so are not uniquely keyed by (week, day, slot, role).
 */
export interface OverrideIn {
  week: string
  day: Day
  slot: AssignmentSlot
  role: AssignmentRole
  user_id: number
  assignment_id?: number
}

/** One §2.1 hard rule the override left standing — data, rendered by §9. */
export interface ViolationOut {
  rule: string
  user_id: number
  day: Day | null
  slot: AssignmentSlot | null
}

export interface OverrideOut {
  assignment: ScheduleAssignmentOut
  previous_user_id: number | null
  new_user_id: number
  created: boolean
  violations: ViolationOut[]
}

export interface AdminConstraintOut {
  id: number
  user_id: number
  user_name: string
  day: Day
  slot: ConstraintSlot
  kind: ConstraintKind
  note: string | null
  created_at: string
  updated_at: string
}

export interface AdminConstraintsOut {
  week: string
  status: WeekStatus
  constraints: AdminConstraintOut[]
}

/**
 * One §6 `audit_log` row. `actor_id`/`actor_name` are null exactly when
 * `system` is true (§6: cron solve, 48 h swap expiry, nightly backup — there is
 * deliberately no system user row, and a null actor is never a vanished human).
 */
export interface AuditEntryOut {
  id: number
  actor_id: number | null
  actor_name: string | null
  system: boolean
  action: string
  entity: string
  entity_id: number | null
  payload: Record<string, unknown> | null
  created_at: string
}

export interface AuditPageOut {
  total: number
  limit: number
  offset: number
  entries: AuditEntryOut[]
}

export interface AuditQuery {
  limit: number
  offset: number
  action: string | null
  entity: string | null
}

/* -- root (§7 `-- root --`) -- */

/** `GET /root/users`. Inherits UserOut, so `is_root` is absent here too (§5). */
export interface UserAdminOut extends UserOut {
  created_at: string
}

/** `POST /root/users`. No `is_root` (§5: root-ness is seeded, never minted). */
export interface UserCreateIn {
  username: string
  display_name: string
  role: UserRole
  email: string | null
  is_admin: boolean
  language: Language
  password: string
}

/**
 * `PATCH /root/users/{id}`. Partial: an absent field is left alone. `active`
 * is how a user is removed — §5: never hard-deleted, only deactivated.
 */
export interface UserUpdateIn {
  display_name?: string
  role?: UserRole
  email?: string | null
  is_admin?: boolean
  language?: Language
  active?: boolean
}

/** `POST /root/users/{id}/password` — a reset, so no current password. */
export interface PasswordResetIn {
  new_password: string
}
