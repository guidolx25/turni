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

export const DAY_ORDER: readonly Day[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

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
