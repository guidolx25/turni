/**
 * Week schedule grid (§9): days × slots, role-colored chips, own shifts
 * emphasized. Publication state keys off `week.status` — a non-locked week
 * renders a deliberate "not published" state, never a partial grid (§3:
 * visibility keys off `locked`, never `solved`).
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { AssignmentSlot, Day, ScheduleAssignmentOut, WeekOut } from '../api/types'
import type { TranslationKey } from '../i18n/it'
import { DAY_ORDER } from '../api/types'
import { errorKey as toErrorKey } from '../api/client'
import { adminApi } from '../api/endpoints'
import { useAuth } from '../auth/AuthContext'
import { hasAdminPanelAccess } from '../auth/capabilities'
import {
  BUTTON_PRIMARY,
  ErrorNote,
  LoadingIndicator,
  WeekPicker,
  WeekStatusBadge,
} from '../components/common'
import { LockIcon, LockOpenIcon } from '../components/icons'
import { useCountdown } from '../hooks/useCountdown'
import { useSchedule, useWeeks } from '../hooks/useResource'
import { useLanguage, useT } from '../i18n'
import { dayNumberLabel, parseIsoDate, weekdayLabel, type Countdown } from '../lib/dates'

const SLOTS: readonly AssignmentSlot[] = ['am', 'pm']

/** The week whose Mon–Sun range contains today, else the latest one. */
function defaultWeek(weeks: WeekOut[]): string | null {
  const today = new Date()
  for (const week of weeks) {
    const monday = parseIsoDate(week.monday_date)
    const end = new Date(monday)
    end.setDate(end.getDate() + 7)
    if (today >= monday && today < end) return week.monday_date
  }
  return weeks.length > 0 ? (weeks[weeks.length - 1]?.monday_date ?? null) : null
}

function formatCountdown(c: Countdown, t: ReturnType<typeof useT>): string {
  const d = `${String(c.days)}${t('countdown.days')}`
  const h = `${String(c.hours)}${t('countdown.hours')}`
  const m = `${String(c.minutes)}${t('countdown.minutes')}`
  if (c.days > 0) return `${d} ${h}`
  if (c.hours > 0) return `${h} ${m}`
  return m
}

function AssignmentChip({
  assignment,
  isMine,
  weekLocked,
  monday,
}: {
  assignment: ScheduleAssignmentOut
  isMine: boolean
  weekLocked: boolean
  monday: string
}) {
  const t = useT()
  const navigate = useNavigate()

  const tone =
    assignment.role === 'bagnino'
      ? isMine
        ? 'bg-bagnino text-surface-0 font-medium'
        : 'border border-bagnino-dim bg-bagnino-dim/40 text-bagnino'
      : isMine
        ? 'bg-spiaggino text-surface-0 font-medium'
        : 'border border-spiaggino-dim bg-spiaggino-dim/40 text-spiaggino'

  const label = (
    <>
      <span className="truncate">{assignment.user_name}</span>
      {isMine ? (
        <span className="text-[10px] uppercase opacity-75">{t('schedule.you')}</span>
      ) : null}
    </>
  )

  // §9: tapping one of your own slots in a published week starts the swap flow.
  if (isMine && weekLocked) {
    return (
      <button
        type="button"
        onClick={() => {
          void navigate(`/swaps?week=${monday}&from=${String(assignment.id)}`)
        }}
        className={`flex w-full items-center justify-between gap-1 rounded px-1.5 py-1 text-left text-xs ${tone}`}
      >
        {label}
      </button>
    )
  }

  return (
    <span className={`flex items-center justify-between gap-1 rounded px-1.5 py-1 text-xs ${tone}`}>
      {label}
    </span>
  )
}

function ScheduleGrid({
  monday,
  assignments,
}: {
  monday: string
  assignments: ScheduleAssignmentOut[]
}) {
  const t = useT()
  const { language } = useLanguage()
  const { user } = useAuth()

  const byCell = useMemo(() => {
    const map = new Map<string, ScheduleAssignmentOut[]>()
    for (const a of assignments) {
      const key = `${a.day}:${a.slot}`
      const cell = map.get(key) ?? []
      cell.push(a)
      map.set(key, cell)
    }
    // Stable render order inside a cell: bagnino above spiaggino(s).
    for (const cell of map.values()) {
      cell.sort((x, y) =>
        x.role === y.role ? x.user_name.localeCompare(y.user_name) : x.role === 'bagnino' ? -1 : 1,
      )
    }
    return map
  }, [assignments])

  const cellFor = (day: Day, slot: AssignmentSlot) => byCell.get(`${day}:${slot}`) ?? []

  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="grid grid-cols-[3.25rem_1fr_1fr] border-b border-line bg-surface-1 text-xs text-ink-2">
        <span />
        <span className="px-2 py-2">{t('slot.am')}</span>
        <span className="px-2 py-2">{t('slot.pm')}</span>
      </div>
      {DAY_ORDER.map((day) => (
        <div
          key={day}
          className="grid grid-cols-[3.25rem_1fr_1fr] border-b border-line last:border-b-0"
        >
          <div className="flex flex-col items-center justify-center gap-0.5 bg-surface-1 py-2">
            <span className="text-[11px] text-ink-2">{weekdayLabel(monday, day, language)}</span>
            <span className="text-sm text-ink-1">{dayNumberLabel(monday, day, language)}</span>
          </div>
          {SLOTS.map((slot) => (
            <div key={slot} className="flex flex-col gap-1 border-l border-line p-1.5">
              {cellFor(day, slot).map((assignment) => (
                <AssignmentChip
                  key={`${String(assignment.id)}:${String(assignment.user_id)}:${assignment.role}`}
                  assignment={assignment}
                  isMine={assignment.user_id === user?.id}
                  weekLocked
                  monday={monday}
                />
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

/**
 * Publish, offered beside the grid being reviewed (§3.3 solve → review → publish).
 *
 * The admin panel keeps its own publish control; this is the same call reached
 * from where the decision is actually made. Gated on `trigger_solve` — §5 has no
 * separate "publish" row, and the same tier owns both halves of the manual path.
 */
function PublishInline({ monday, onPublished }: { monday: string; onPublished: () => void }) {
  const t = useT()
  const [busy, setBusy] = useState(false)
  const [errorKey, setErrorKey] = useState<TranslationKey | null>(null)

  const publish = () => {
    setBusy(true)
    setErrorKey(null)
    adminApi
      .publish(monday)
      .then(onPublished)
      .catch((error: unknown) => {
        setErrorKey(toErrorKey(error))
      })
      .finally(() => {
        setBusy(false)
      })
  }

  return (
    <div className="space-y-2 rounded-lg border border-line bg-surface-1 p-3">
      <p className="text-xs text-ink-2">{t('schedule.publish.help')}</p>
      <button type="button" disabled={busy} onClick={publish} className={BUTTON_PRIMARY}>
        {busy ? t('admin.publish.working') : t('admin.publish.submit')}
      </button>
      {errorKey ? <ErrorNote errorKey={errorKey} /> : null}
    </div>
  )
}

function NotPublished({ status }: { status: 'open' | 'solved' }) {
  const t = useT()
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-line bg-surface-1 px-6 py-12 text-center">
      <LockOpenIcon className="h-6 w-6 text-ink-3" />
      <p className="text-sm font-medium text-ink-1">{t('schedule.notPublished.title')}</p>
      <p className="max-w-sm text-xs leading-relaxed text-ink-2">
        {status === 'open' ? t('schedule.notPublished.open') : t('schedule.notPublished.solved')}
      </p>
    </div>
  )
}

export function ScheduleView() {
  const t = useT()
  const { user } = useAuth()
  const capabilities = user?.capabilities
  const weeks = useWeeks()
  const [selectedWeek, setSelectedWeek] = useState<string | null>(null)

  const weekList = weeks.data ?? []
  const activeWeek = selectedWeek ?? defaultWeek(weekList)
  const week = weekList.find((w) => w.monday_date === activeWeek) ?? null
  const locked = week?.status === 'locked'

  /**
   * §3.2: `solved` exists so admin/root can review before publishing — workers
   * see nothing, reviewers see the grid. `GET /schedule` already implements
   * exactly that (`status is LOCKED or has_admin_capability`), but this view
   * used to gate the *request* on `locked` alone, so the preview the backend
   * served was never asked for and a reviewer saw the worker's empty state.
   *
   * Mirrors the backend predicate rather than inventing one: every §5 admin row
   * derives from the same flag `has_admin_capability` reads, and
   * `hasAdminPanelAccess` is that same OR on this side.
   */
  const canPreview = hasAdminPanelAccess(user?.capabilities)
  const showsGrid = locked || (canPreview && week?.status === 'solved')
  const schedule = useSchedule(showsGrid && activeWeek ? activeWeek : null)
  const countdown = useCountdown(week?.status === 'open' ? week.submission_deadline : null)

  return (
    <section className="space-y-4">
      <h1 className="text-lg font-medium">{t('schedule.title')}</h1>

      {weeks.loading ? <LoadingIndicator /> : null}
      {weeks.errorKey ? <ErrorNote errorKey={weeks.errorKey} onRetry={weeks.reload} /> : null}

      {week ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <WeekPicker weeks={weekList} selected={activeWeek} onSelect={setSelectedWeek} />
            <WeekStatusBadge status={week.status} />
            {week.status === 'open' ? (
              <span className="text-xs text-ink-2">
                {countdown
                  ? t('week.closesIn', { time: formatCountdown(countdown, t) })
                  : t('week.deadlinePassed')}
              </span>
            ) : null}
          </div>

          {showsGrid ? (
            <>
              {/* Lock state must be unmistakable (§9): published banner, or the
                  preview banner that says this is NOT yet what workers see. */}
              {locked ? (
                <p className="flex items-center gap-1.5 text-xs text-ok">
                  <LockIcon className="h-3.5 w-3.5" />
                  {t('schedule.published')}
                </p>
              ) : (
                <p className="flex items-center gap-1.5 text-xs text-spiaggino">
                  <LockOpenIcon className="h-3.5 w-3.5" />
                  {t('schedule.preview')}
                </p>
              )}
              {schedule.loading ? <LoadingIndicator /> : null}
              {schedule.errorKey ? (
                <ErrorNote errorKey={schedule.errorKey} onRetry={schedule.reload} />
              ) : null}
              {schedule.data ? (
                <ScheduleGrid
                  monday={schedule.data.monday_date}
                  assignments={schedule.data.assignments}
                />
              ) : null}
              {/* Reviewing and publishing are one motion, so the action sits
                  where the review happens. It is the same POST /admin/publish the
                  admin panel offers — a second entry point, not a second rule. */}
              {!locked && capabilities?.trigger_solve ? (
                <PublishInline monday={week.monday_date} onPublished={weeks.reload} />
              ) : null}
            </>
          ) : (
            <NotPublished status={week.status === 'open' ? 'open' : 'solved'} />
          )}
        </>
      ) : null}
    </section>
  )
}
