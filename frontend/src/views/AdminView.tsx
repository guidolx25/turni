/**
 * Admin panel (§9: "solve, override, submissions, audit").
 *
 * Every section is gated on the caller's own §5 capability from /me — never on
 * `is_admin`. §7 puts `capabilities` on /me precisely so §5's matrix has one
 * source of truth: the question the frontend asks is "may I trigger a solve",
 * not "am I an admin", and if §5 ever moves a row between tiers no view here
 * changes.
 *
 * One week selection is shared by solve, override and submissions, so the three
 * always speak about the same week — a panel where "generate" and "submissions"
 * could silently disagree on which week they mean is a panel that publishes the
 * wrong one.
 */
import { useMemo, useState } from 'react'

import type { WeekOut } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import {
  ErrorNote,
  Help,
  LoadingIndicator,
  WeekPicker,
  WeekStatusBadge,
} from '../components/common'
import { useAdminConstraints, useWeeks } from '../hooks/useResource'
import { useT } from '../i18n'
import { AuditPanel } from './admin/AuditPanel'
import { OverridePanel } from './admin/OverridePanel'
import { SolvePanel } from './admin/SolvePanel'
import { SubmissionsPanel } from './admin/SubmissionsPanel'

/** The upcoming or current week, else the last one listed. */
function defaultWeek(weeks: WeekOut[]): string | null {
  const open = weeks.find((week) => week.status === 'open')
  return open?.monday_date ?? weeks[weeks.length - 1]?.monday_date ?? null
}

export function AdminView() {
  const t = useT()
  const { user } = useAuth()
  const weeks = useWeeks()
  const [selectedWeek, setSelectedWeek] = useState<string | null>(null)

  const capabilities = user?.capabilities
  const weekList = useMemo(() => weeks.data ?? [], [weeks.data])
  const activeWeek = selectedWeek ?? defaultWeek(weekList)
  const week = weekList.find((candidate) => candidate.monday_date === activeWeek) ?? null

  const canViewConstraints = capabilities?.view_all_constraints ?? false
  const submissions = useAdminConstraints(activeWeek, canViewConstraints)

  /**
   * user_id → display name for this week. The §8 unsat core and the override
   * violations are ids-only by design (§6: conflicts are data, localized at
   * render time), and a blocking constraint is by definition a submission — so
   * the submissions response is the honest name source for both.
   */
  const names = useMemo(() => {
    const map = new Map<number, string>()
    for (const row of submissions.data?.constraints ?? []) map.set(row.user_id, row.user_name)
    return map
  }, [submissions.data])

  const reloadAll = () => {
    weeks.reload()
    submissions.reload()
  }

  return (
    <section className="space-y-4">
      <h1 className="text-lg font-medium">{t('admin.title')}</h1>
      <Help>{t('admin.intro')}</Help>

      {weeks.loading && weekList.length === 0 ? <LoadingIndicator /> : null}
      {weeks.errorKey ? <ErrorNote errorKey={weeks.errorKey} onRetry={weeks.reload} /> : null}
      {!weeks.loading && weekList.length === 0 ? <Help>{t('admin.noWeeks')}</Help> : null}

      {week && activeWeek ? (
        <div className="flex flex-wrap items-center gap-3">
          <WeekPicker weeks={weekList} selected={activeWeek} onSelect={setSelectedWeek} />
          <WeekStatusBadge status={week.status} />
        </div>
      ) : null}

      {/* Every week-scoped panel below is gated on `week`, so an unresolvable
          week used to render NOTHING — no controls, no explanation, on a page
          whose entire purpose is those controls. Silence is the worst failure
          here: it is indistinguishable from "you lack the capability", which is
          what it was mistaken for. Say which of the two it is. */}
      {!week && weekList.length > 0 && !weeks.loading && !weeks.errorKey ? (
        <Help>{t('admin.noWeekSelected')}</Help>
      ) : null}

      {week && capabilities?.trigger_solve ? (
        <SolvePanel week={week} names={names} onChanged={reloadAll} />
      ) : null}

      {week && capabilities?.override_locked_slots ? (
        <OverridePanel week={week} onChanged={reloadAll} />
      ) : null}

      {week && activeWeek && canViewConstraints ? (
        <SubmissionsPanel monday={activeWeek} resource={submissions} />
      ) : null}

      {capabilities?.view_audit_log ? <AuditPanel /> : null}
    </section>
  )
}
