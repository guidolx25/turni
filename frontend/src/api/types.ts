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
