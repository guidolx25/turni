/**
 * My constraints (§9): multi-week picker, per-day slot choice, hard/soft toggle,
 * note, and the countdown to the Sunday-17:00 deadline (§3.1).
 *
 * Two rules drive the whole interaction:
 *  - §3.1 submission is an UPSERT on (user, week, day, slot), and within a day
 *    `full_day` and `am`/`pm` are mutually exclusive. The server enforces the
 *    exclusion; the UI states it in words *before* the tap and reloads after
 *    every write, so the page never shows a contradictory day.
 *  - §2.1 H7 vs §2.2 S1: "binding" is a promise the solver cannot break and can
 *    make a week infeasible (§2.3); "preference" is an objective term. That is a
 *    consequential choice, so both options carry their consequence in copy
 *    rather than being two equal-looking pills.
 */
import { useCallback, useMemo, useState } from 'react'

import { errorKey as toErrorKey } from '../api/client'
import { constraintsApi } from '../api/endpoints'
import type { ConstraintKind, ConstraintOut, ConstraintSlot, Day, WeekOut } from '../api/types'
import { DAY_ORDER, WEEKEND_DAYS } from '../api/types'
import { ErrorNote, LoadingIndicator, WeekPicker, WeekStatusBadge } from '../components/common'
import { AlertIcon } from '../components/icons'
import { useCountdown } from '../hooks/useCountdown'
import { useConstraints, useWeeks } from '../hooks/useResource'
import type { TranslationKey } from '../i18n'
import { useLanguage, useT } from '../i18n'
import { countdownTo, dayNumberLabel, weekdayLabel, type Countdown } from '../lib/dates'

const SLOT_ORDER: readonly ConstraintSlot[] = ['am', 'pm', 'full_day']
const KINDS: readonly ConstraintKind[] = ['soft', 'hard']

function formatCountdown(c: Countdown, t: ReturnType<typeof useT>): string {
  const d = `${String(c.days)}${t('countdown.days')}`
  const h = `${String(c.hours)}${t('countdown.hours')}`
  const m = `${String(c.minutes)}${t('countdown.minutes')}`
  if (c.days > 0) return `${d} ${h}`
  if (c.hours > 0) return `${h} ${m}`
  return m
}

/** Mirrors `app.scheduling.is_submittable` (§3.1): open AND before the deadline. */
function readOnlyReason(week: WeekOut): TranslationKey | null {
  if (week.status === 'locked') return 'constraints.readOnly.locked'
  if (week.status === 'solved') return 'constraints.readOnly.solved'
  if (countdownTo(week.submission_deadline, new Date()) === null) {
    return 'constraints.readOnly.deadlinePassed'
  }
  return null
}

/**
 * Hard and soft must not look like two equal pills: hard borrows the danger
 * accent (it is the H7 promise that can make a week infeasible), soft the calm
 * bagnino accent (an S1 objective term).
 */
function kindTone(kind: ConstraintKind, selected: boolean): string {
  if (!selected) return 'border-line text-ink-3 hover:text-ink-2'
  return kind === 'hard'
    ? 'border-danger bg-danger-dim/40 text-danger'
    : 'border-bagnino bg-bagnino-dim/40 text-bagnino'
}

interface DayWrite {
  slot: ConstraintSlot
  kind: ConstraintKind
  note: string | null
}

function KindChoice({
  slotLabel,
  value,
  disabled,
  onChange,
}: {
  slotLabel: string
  value: ConstraintKind
  disabled: boolean
  onChange: (kind: ConstraintKind) => void
}) {
  const t = useT()
  return (
    <div role="group" aria-label={slotLabel} className="flex gap-1.5">
      {KINDS.map((kind) => {
        const selected = kind === value
        return (
          <button
            key={kind}
            type="button"
            disabled={disabled}
            aria-pressed={selected}
            onClick={() => {
              onChange(kind)
            }}
            className={`rounded-md border px-2 py-1 text-[11px] disabled:opacity-50 ${kindTone(kind, selected)}`}
          >
            {t(`constraints.kind.${kind}`)}
          </button>
        )
      })}
    </div>
  )
}

function DayEditor({
  monday,
  day,
  rows,
  readOnly,
  onWrite,
  onRemove,
}: {
  monday: string
  day: Day
  rows: ConstraintOut[]
  readOnly: boolean
  onWrite: (day: Day, write: DayWrite) => Promise<void>
  onRemove: (id: number) => Promise<void>
}) {
  const t = useT()
  const { language } = useLanguage()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(rows[0]?.note ?? '')

  const isWeekend = WEEKEND_DAYS.includes(day)
  const dayLabel = weekdayLabel(monday, day, language)
  const rowFor = (slot: ConstraintSlot) => rows.find((row) => row.slot === slot) ?? null
  const hasFullDay = rowFor('full_day') !== null
  const hasSlots = rowFor('am') !== null || rowFor('pm') !== null
  const anyHard = rows.some((row) => row.kind === 'hard')

  const run = (action: Promise<void>) => {
    setBusy(true)
    void action.finally(() => {
      setBusy(false)
    })
  }

  const toggleSlot = (slot: ConstraintSlot) => {
    const existing = rowFor(slot)
    if (existing) {
      run(onRemove(existing.id))
      return
    }
    // A new selection starts as a preference: the binding promise (H7) should be
    // opted into deliberately, never arrived at by a default.
    run(onWrite(day, { slot, kind: 'soft', note: note === '' ? null : note }))
  }

  const setKind = (slot: ConstraintSlot, kind: ConstraintKind) => {
    run(onWrite(day, { slot, kind, note: note === '' ? null : note }))
  }

  const saveNote = () => {
    const current = rows[0]?.note ?? ''
    if (note === current || rows.length === 0) return
    const value = note === '' ? null : note
    run(
      Promise.all(
        rows.map((row) => onWrite(day, { slot: row.slot, kind: row.kind, note: value })),
      ).then(() => undefined),
    )
  }

  const summary =
    rows.length === 0
      ? t('constraints.day.free')
      : rows
          .map((row) => `${t(`slot.${row.slot}`)} · ${t(`constraints.summary.${row.kind}`)}`)
          .join(' — ')

  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        aria-label={
          open
            ? t('constraints.day.collapse', { day: dayLabel })
            : t('constraints.day.open', { day: dayLabel })
        }
        onClick={() => {
          setOpen((value) => !value)
        }}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2/60"
      >
        <span className="flex w-12 shrink-0 flex-col">
          <span className="text-[11px] text-ink-2">{dayLabel}</span>
          <span className="text-sm text-ink-1">{dayNumberLabel(monday, day, language)}</span>
        </span>
        <span
          className={`flex-1 truncate text-xs ${rows.length === 0 ? 'text-ink-3' : anyHard ? 'text-danger' : 'text-bagnino'}`}
        >
          {summary}
        </span>
      </button>

      {open ? (
        <div className="space-y-3 border-t border-line bg-surface-2/40 px-3 py-3">
          <p className="text-[10px] tracking-wide uppercase text-ink-3">
            {t('constraints.slots.label')}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {SLOT_ORDER.map((slot) => {
              const selected = rowFor(slot) !== null
              return (
                <button
                  key={slot}
                  type="button"
                  disabled={readOnly || busy}
                  aria-pressed={selected}
                  onClick={() => {
                    toggleSlot(slot)
                  }}
                  className={`rounded-md border px-2.5 py-1.5 text-xs disabled:opacity-50 ${
                    selected
                      ? 'border-ink-3 bg-surface-1 font-medium text-ink-1'
                      : 'border-line text-ink-2 hover:border-ink-3'
                  }`}
                >
                  {t(`slot.${slot}`)}
                </button>
              )
            })}
          </div>

          {/* §3.1 exclusivity, said out loud instead of enforced by a dead control. */}
          {hasFullDay ? (
            <p className="text-[11px] text-ink-3">{t('constraints.fullDayReplaces')}</p>
          ) : hasSlots ? (
            <p className="text-[11px] text-ink-3">{t('constraints.slotReplacesFullDay')}</p>
          ) : null}

          {rows.length > 0 ? (
            <div className="space-y-2">
              <p className="text-[10px] tracking-wide uppercase text-ink-3">
                {t('constraints.kind.label')}
              </p>
              {rows.map((row) => (
                <div key={row.id} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-ink-2">{t(`slot.${row.slot}`)}</span>
                  <KindChoice
                    slotLabel={t(`slot.${row.slot}`)}
                    value={row.kind}
                    disabled={readOnly || busy}
                    onChange={(kind) => {
                      setKind(row.slot, kind)
                    }}
                  />
                </div>
              ))}
              <p className="text-[11px] leading-relaxed text-ink-2">
                {anyHard ? t('constraints.kind.hardHelp') : t('constraints.kind.softHelp')}
              </p>
            </div>
          ) : null}

          {/* §10 weekend_hard_escalated: the moment of choosing is the moment to
              say a hard weekend request goes to a human, not to the solver. */}
          {isWeekend ? (
            <p className="text-[11px] text-ink-3">{t('constraints.weekend.hint')}</p>
          ) : null}
          {isWeekend && anyHard ? (
            <p
              role="alert"
              className="flex gap-2 rounded-md border border-spiaggino-dim bg-spiaggino-dim/20 px-2.5 py-2 text-[11px] leading-relaxed text-spiaggino"
            >
              <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t('constraints.weekend.hardWarning')}
            </p>
          ) : null}

          {rows.length > 0 ? (
            <label className="block space-y-1">
              <span className="text-xs text-ink-2">{t('constraints.note.label')}</span>
              <textarea
                rows={2}
                value={note}
                disabled={readOnly || busy}
                placeholder={t('constraints.note.placeholder')}
                onChange={(event) => {
                  setNote(event.target.value)
                }}
                onBlur={saveNote}
                className="w-full rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-xs text-ink-1 outline-none focus:border-ink-3 disabled:opacity-50"
              />
            </label>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

export function ConstraintsView() {
  const t = useT()
  const weeks = useWeeks()
  const [selectedWeek, setSelectedWeek] = useState<string | null>(null)
  const [error, setError] = useState<TranslationKey | null>(null)

  const weekList = weeks.data ?? []
  // §7: "multi-week: any week with status=open". Closed weeks stay listed so a
  // worker can read what they submitted — read-only, with the reason stated.
  const activeWeek =
    selectedWeek ??
    weekList.find((week) => week.status === 'open')?.monday_date ??
    weekList[0]?.monday_date ??
    null
  const week = weekList.find((w) => w.monday_date === activeWeek) ?? null

  const constraints = useConstraints(activeWeek)
  const countdown = useCountdown(week?.status === 'open' ? week.submission_deadline : null)
  const readOnly = week ? readOnlyReason(week) : null

  const rowsByDay = useMemo(() => {
    const map = new Map<Day, ConstraintOut[]>()
    for (const row of constraints.data ?? []) {
      const list = map.get(row.day) ?? []
      list.push(row)
      map.set(row.day, list)
    }
    for (const list of map.values()) {
      list.sort((a, b) => SLOT_ORDER.indexOf(a.slot) - SLOT_ORDER.indexOf(b.slot))
    }
    return map
  }, [constraints.data])

  const { reload } = constraints

  const write = useCallback(
    async (day: Day, { slot, kind, note }: DayWrite) => {
      if (!activeWeek) return
      setError(null)
      try {
        await constraintsApi.upsert({ week: activeWeek, day, slot, kind, note })
      } catch (err: unknown) {
        setError(toErrorKey(err))
      } finally {
        // Always re-read: the upsert may have deleted sibling rows (§3.1).
        reload()
      }
    },
    [activeWeek, reload],
  )

  const remove = useCallback(
    async (id: number) => {
      setError(null)
      try {
        await constraintsApi.remove(id)
      } catch (err: unknown) {
        setError(toErrorKey(err))
      } finally {
        reload()
      }
    },
    [reload],
  )

  return (
    <section className="space-y-4">
      <h1 className="text-lg font-medium">{t('constraints.title')}</h1>
      <p className="text-xs leading-relaxed text-ink-2">{t('constraints.intro')}</p>

      {weeks.loading ? <LoadingIndicator /> : null}
      {weeks.errorKey ? <ErrorNote errorKey={weeks.errorKey} onRetry={weeks.reload} /> : null}
      {!weeks.loading && weekList.length === 0 ? (
        <p className="rounded-lg border border-line bg-surface-1 px-4 py-8 text-center text-xs text-ink-2">
          {t('constraints.noWeeks')}
        </p>
      ) : null}

      {week && activeWeek ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <WeekPicker weeks={weekList} selected={activeWeek} onSelect={setSelectedWeek} />
            <WeekStatusBadge status={week.status} />
          </div>

          {readOnly ? (
            <p
              role="status"
              className="rounded-md border border-line bg-surface-1 px-3 py-2 text-xs leading-relaxed text-ink-2"
            >
              {t(readOnly)}
            </p>
          ) : (
            <p className="text-xs text-ink-2">
              {countdown
                ? `${t('constraints.deadline')} — ${t('week.closesIn', { time: formatCountdown(countdown, t) })}`
                : t('constraints.deadline')}
            </p>
          )}

          {error ? <ErrorNote errorKey={error} /> : null}
          {constraints.errorKey ? (
            <ErrorNote errorKey={constraints.errorKey} onRetry={constraints.reload} />
          ) : null}

          <ul className="overflow-hidden rounded-lg border border-line bg-surface-1">
            {DAY_ORDER.map((day) => (
              <DayEditor
                key={`${activeWeek}:${day}`}
                monday={activeWeek}
                day={day}
                rows={rowsByDay.get(day) ?? []}
                readOnly={readOnly !== null}
                onWrite={write}
                onRemove={remove}
              />
            ))}
          </ul>
        </>
      ) : null}
    </section>
  )
}
