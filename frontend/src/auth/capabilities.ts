/**
 * §5 capability predicates.
 *
 * The frontend never asks "is this user an admin" — §7 ships `capabilities` on
 * /me precisely so §5's matrix has one source of truth, and each flag names the
 * matrix ROW ("may I trigger a solve") rather than the flag behind it. If §5
 * moves a row between tiers, the backend derivation changes and every consumer
 * follows without a rename here.
 *
 * The one derived predicate lives here rather than in a view, so the route
 * guard and the header nav cannot drift on who sees the admin panel.
 */
import type { Capabilities } from '../api/types'

/** Any §5 admin-tier row is enough to make the admin panel worth rendering. */
export function hasAdminPanelAccess(capabilities: Capabilities | undefined): boolean {
  if (!capabilities) return false
  return (
    capabilities.trigger_solve ||
    capabilities.override_locked_slots ||
    capabilities.view_all_constraints ||
    capabilities.view_audit_log
  )
}

export function canManageUsers(capabilities: Capabilities | undefined): boolean {
  return capabilities?.manage_users ?? false
}
