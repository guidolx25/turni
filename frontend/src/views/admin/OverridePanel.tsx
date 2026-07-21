/**
 * Admin override of a locked slot (§5, §3.4, §7 `POST /admin/override`).
 *
 * Only meaningful on a LOCKED week: §3.4 makes swap and override the two
 * post-lock instruments, while an unpublished week is regenerated instead. The
 * consequence — an already published schedule changes under people who are
 * relying on it, and both affected workers get a §10 `admin_override` notice —
 * is stated *above* the button, not reported after the fact.
 *
 * The slot list and the person list are both derived from the week's own
 * schedule: §7 exposes no admin-facing user directory (`/root/users` is root
 * only), and H1 puts every active worker in some slot of a published week.
 * Picking a concrete assignment row also supplies `assignment_id`, which is what
 * disambiguates the H5 weekend slots that seat two spiaggini.
 */
import { useMemo, useState } from 'react'

import { errorKey as toErrorKey } from '../../api/client'
import { adminApi } from '../../api/endpoints'
import type { ScheduleAssignmentOut, ViolationOut, WeekOut } from '../../api/types'
import { DAY_ORDER } from '../../api/types'
import {
  BUTTON_PRIMARY,
  ErrorNote,
  FIELD_CLASS,
  FieldLabel,
  Help,
  LoadingIndicator,
  Panel,
  SuccessNote,
} from '../../components/common'
import { AlertIcon } from '../../components/icons'
import { useSchedule } from '../../hooks/useResource'
import type { TranslationKey } from '../../i18n'
import { useLanguage, useT } from '../../i18n'
import { weekdayLabel } from '../../lib/dates'

const SLOT_ORDER = ['am', 'pm'] as const

/** §2.1 rule ids as the backend spells them, lowercased for the key lookup. */
const VIOLATION_KEYS: Record<string, TranslationKey> = {
  h2: 'admin.override.violation.h2',
  h3: 'admin.override.violation.h3',
  h4: 'admin.override.violation.h4',
}

function ViolationList({
  violations,
  monday,
  names,
}: {
  violations: ViolationOut[]
  monday: string
  names: Map<number, string>
}) {
  const t = useT()
  const { language } = useLanguage()

  const line = (violation: ViolationOut): string => {
    const name = names.get(violation.user_id) ?? t('admin.override.someone')
    const key = VIOLATION_KEYS[violation.rule.toLowerCase()]
    const day = violation.day ? weekdayLabel(monday, violation.day, language) : null
    const slot = violation.slot ? t(`slot.${violation.slot}`) : null
    // A rule whose sentence needs a field the payload did not carry falls back
    // to the generic line rather than printing an empty placeholder.
    if (key === 'admin.override.violation.h3') return t(key, { name })
    if (key === 'admin.override.violation.h4' && day) return t(key, { name, day })
    if (key === 'admin.override.violation.h2' && day && slot) return t(key, { name, day, slot })
    return t('admin.override.violation.other', { name, rule: violation.rule })
  }

  return (
    <div className="space-y-2 rounded-md border border-danger-dim bg-danger-dim/15 px-3 py-2.5">
      <p className="flex items-center gap-2 text-xs font-medium text-danger">
        <AlertIcon className="h-3.5 w-3.5 shrink-0" />
        {t('admin.override.violations')}
      </p>
      <ul className="space-y-1">
        {violations.map((violation, index) => (
          <li
            key={`${violation.rule}:${String(violation.user_id)}:${String(index)}`}
            className="text-xs text-ink-1"
          >
            {line(violation)}
          </li>
        ))}
      </ul>
      <Help>{t('admin.override.violations.help')}</Help>
    </div>
  )
}

export function OverridePanel({ week, onChanged }: { week: WeekOut; onChanged: () => void }) {
  const t = useT()
  const { language } = useLanguage()
  const locked = week.status === 'locked'
  const schedule = useSchedule(locked ? week.monday_date : null)

  const [assignmentId, setAssignmentId] = useState('')
  const [userId, setUserId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)
  const [violations, setViolations] = useState<ViolationOut[] | null>(null)

  const assignments = useMemo<ScheduleAssignmentOut[]>(() => {
    const rows = [...(schedule.data?.assignments ?? [])]
    rows.sort(
      (a, b) =>
        DAY_ORDER.indexOf(a.day) - DAY_ORDER.indexOf(b.day) ||
        SLOT_ORDER.indexOf(a.slot) - SLOT_ORDER.indexOf(b.slot) ||
        a.role.localeCompare(b.role) ||
        a.user_name.localeCompare(b.user_name),
    )
    return rows
  }, [schedule.data])

  const people = useMemo(() => {
    const map = new Map<number, string>()
    for (const row of assignments) map.set(row.user_id, row.user_name)
    return [...map.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [assignments])

  const names = useMemo(() => new Map(people.map(({ id, name }) => [id, name])), [people])

  const selected = assignments.find((row) => String(row.id) === assignmentId) ?? null

  const apply = () => {
    if (!selected || userId === '') return
    setBusy(true)
    setError(null)
    setViolations(null)
    adminApi
      .override({
        week: week.monday_date,
        day: selected.day,
        slot: selected.slot,
        role: selected.role,
        user_id: Number(userId),
        assignment_id: selected.id,
      })
      .then((outcome) => {
        setViolations(outcome.violations)
        setUserId('')
      })
      .catch((err: unknown) => {
        setError(toErrorKey(err))
      })
      .finally(() => {
        setBusy(false)
        schedule.reload()
        onChanged()
      })
  }

  return (
    <Panel title={t('admin.override.title')}>
      <Help>{t('admin.override.help')}</Help>

      {!locked ? (
        <Help>{t('admin.override.needsLocked')}</Help>
      ) : (
        <>
          {schedule.loading && assignments.length === 0 ? <LoadingIndicator /> : null}
          {schedule.errorKey ? (
            <ErrorNote errorKey={schedule.errorKey} onRetry={schedule.reload} />
          ) : null}

          {!schedule.loading && assignments.length === 0 ? (
            <Help>{t('admin.override.noSlots')}</Help>
          ) : null}

          {assignments.length > 0 ? (
            <div className="space-y-3">
              <label className="block space-y-1">
                <FieldLabel>{t('admin.override.slot')}</FieldLabel>
                <select
                  aria-label={t('admin.override.slot')}
                  value={assignmentId}
                  onChange={(event) => {
                    setAssignmentId(event.target.value)
                    setViolations(null)
                  }}
                  className={FIELD_CLASS}
                >
                  <option value="">{t('admin.override.pick')}</option>
                  {assignments.map((row) => (
                    <option key={row.id} value={row.id}>
                      {t('admin.override.slotOption', {
                        day: weekdayLabel(week.monday_date, row.day, language),
                        slot: t(`slot.${row.slot}`),
                        role: t(`role.${row.role}`),
                        name: row.user_name,
                      })}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block space-y-1">
                <FieldLabel>{t('admin.override.newHolder')}</FieldLabel>
                <select
                  aria-label={t('admin.override.newHolder')}
                  value={userId}
                  disabled={!selected}
                  onChange={(event) => {
                    setUserId(event.target.value)
                    setViolations(null)
                  }}
                  className={FIELD_CLASS}
                >
                  <option value="">{t('admin.override.pick')}</option>
                  {people.map(({ id, name }) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>

              {/* Stated BEFORE the commit — §5's override is unilateral and
                  immediately visible to the people it moves. */}
              <p className="flex gap-2 rounded-md border border-spiaggino-dim bg-spiaggino-dim/20 px-2.5 py-2 text-[11px] leading-relaxed text-spiaggino">
                <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {t('admin.override.warning')}
              </p>

              <button
                type="button"
                disabled={busy || !selected || userId === ''}
                onClick={apply}
                className={BUTTON_PRIMARY}
              >
                {busy ? t('admin.override.working') : t('admin.override.confirmAction')}
              </button>
            </div>
          ) : null}

          {error ? <ErrorNote errorKey={error} /> : null}
          {violations ? <SuccessNote>{t('admin.override.done')}</SuccessNote> : null}
          {violations && violations.length > 0 ? (
            <ViolationList violations={violations} monday={week.monday_date} names={names} />
          ) : null}
        </>
      )}
    </Panel>
  )
}
