/**
 * Swaps (§4): create a request, answer incoming ones, review history.
 * The client narrows only the obviously-invalid pairings (same person,
 * role-incompatible for non-jolly, weekend non-bagnino); the SERVER is the
 * validator — its §7 error codes surface verbatim through the dictionaries.
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { errorKey as toErrorKey } from '../api/client'
import { swapsApi } from '../api/endpoints'
import type { ScheduleAssignmentOut, SwapAssignmentRef, SwapRequestOut } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { ErrorNote, LoadingIndicator, WeekPicker, WeekStatusBadge } from '../components/common'
import { SwapIcon } from '../components/icons'
import { useSchedule, useSwaps, useWeeks } from '../hooks/useResource'
import type { TranslationKey } from '../i18n'
import { useLanguage, useT } from '../i18n'
import { relativeAge, weekdayLabel } from '../lib/dates'

type NameById = ReadonlyMap<number, string>

function AssignmentLabel({
  monday,
  assignment,
}: {
  monday: string
  assignment: Pick<SwapAssignmentRef, 'day' | 'slot' | 'role'>
}) {
  const t = useT()
  const { language } = useLanguage()
  const roleTone = assignment.role === 'bagnino' ? 'text-bagnino' : 'text-spiaggino'
  return (
    <span className="inline-flex items-baseline gap-1.5 text-xs">
      <span className="text-ink-1">{weekdayLabel(monday, assignment.day, language)}</span>
      <span className="text-ink-2">{t(`slot.${assignment.slot}`)}</span>
      <span className={roleTone}>{t(`role.${assignment.role}`)}</span>
    </span>
  )
}

function statusTone(status: SwapRequestOut['status']): string {
  switch (status) {
    case 'accepted':
    case 'applied':
      return 'text-ok border-ok-dim'
    case 'rejected':
    case 'expired':
      return 'text-danger border-danger-dim'
    case 'pending':
    case 'pending_admin':
      return 'text-ink-2 border-line'
  }
}

function SwapCard({
  swap,
  names,
  mineIsFrom,
  onAnswered,
}: {
  swap: SwapRequestOut
  names: NameById
  mineIsFrom: boolean
  onAnswered: () => void
}) {
  const t = useT()
  const { language } = useLanguage()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)

  const counterpartId = mineIsFrom ? swap.to_user : swap.from_user
  const counterpartName = names.get(counterpartId) ?? `#${String(counterpartId)}`
  const mine = mineIsFrom ? swap.from_assignment : swap.to_assignment
  const theirs = mineIsFrom ? swap.to_assignment : swap.from_assignment
  const answerable = !mineIsFrom && swap.status === 'pending'

  const answer = (action: 'accept' | 'reject') => {
    setBusy(true)
    setError(null)
    ;(action === 'accept' ? swapsApi.accept(swap.id) : swapsApi.reject(swap.id))
      .then(onAnswered)
      .catch((err: unknown) => {
        setError(toErrorKey(err))
      })
      .finally(() => {
        setBusy(false)
      })
  }

  return (
    <article className="space-y-2 rounded-lg border border-line bg-surface-1 p-3">
      <header className="flex items-center justify-between gap-2">
        <span className="text-sm text-ink-1">
          {mineIsFrom
            ? t('swaps.toUser', { name: counterpartName })
            : t('swaps.fromUser', { name: counterpartName })}
        </span>
        <span className={`rounded-full border px-2 py-0.5 text-[11px] ${statusTone(swap.status)}`}>
          {t(`swaps.status.${swap.status}`)}
        </span>
      </header>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="flex flex-col">
          <span className="text-[10px] uppercase tracking-wide text-ink-3">
            {t('swaps.yourShift')}
          </span>
          <AssignmentLabel monday={swap.week} assignment={mine} />
        </span>
        <SwapIcon className="h-3.5 w-3.5 shrink-0 text-ink-3" />
        <span className="flex flex-col">
          <span className="text-[10px] uppercase tracking-wide text-ink-3">
            {t('swaps.theirShift')}
          </span>
          <AssignmentLabel monday={swap.week} assignment={theirs} />
        </span>
        <span className="ml-auto text-[11px] text-ink-3">
          {relativeAge(swap.created_at, new Date(), language)}
        </span>
      </div>
      {error ? <ErrorNote errorKey={error} /> : null}
      {answerable ? (
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              answer('accept')
            }}
            className="rounded-md bg-ok-dim px-3 py-1.5 text-xs font-medium text-ok hover:opacity-90 disabled:opacity-50"
          >
            {t('swaps.accept')}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              answer('reject')
            }}
            className="rounded-md border border-danger-dim px-3 py-1.5 text-xs text-danger hover:bg-danger-dim/30 disabled:opacity-50"
          >
            {t('swaps.reject')}
          </button>
        </div>
      ) : null}
    </article>
  )
}

function CreateSwap({
  monday,
  assignments,
  onCreated,
}: {
  monday: string
  assignments: ScheduleAssignmentOut[]
  onCreated: () => void
}) {
  const t = useT()
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const preselected = Number(searchParams.get('from') ?? '')
  const [fromId, setFromId] = useState<number | null>(
    Number.isInteger(preselected) && preselected > 0 ? preselected : null,
  )
  const [toId, setToId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)
  const [sent, setSent] = useState(false)

  const mine = useMemo(
    () => assignments.filter((a) => a.user_id === user?.id),
    [assignments, user?.id],
  )
  const from = mine.find((a) => a.id === fromId) ?? null

  // Client-side narrowing only — the server re-validates everything (§4).
  const candidates = useMemo(() => {
    if (!from || !user) return []
    const isWeekend = (d: ScheduleAssignmentOut['day']) => d === 'sat' || d === 'sun'
    return assignments.filter((a) => {
      if (a.user_id === user.id) return false
      if (user.role !== 'jolly' && a.role !== from.role) return false
      if (
        (isWeekend(a.day) || isWeekend(from.day)) &&
        (a.role !== 'bagnino' || from.role !== 'bagnino')
      ) {
        return false // §H5: weekend swaps are bagnino↔bagnino only
      }
      return true
    })
  }, [assignments, from, user])

  const to = candidates.find((a) => a.id === toId) ?? null

  const submit = () => {
    if (!from || !to || busy) return
    setBusy(true)
    setError(null)
    setSent(false)
    swapsApi
      .create({ to_user: to.user_id, from_assignment: from.id, to_assignment: to.id })
      .then(() => {
        setSent(true)
        setFromId(null)
        setToId(null)
        onCreated()
      })
      .catch((err: unknown) => {
        setError(toErrorKey(err))
      })
      .finally(() => {
        setBusy(false)
      })
  }

  const optionClass = (selected: boolean) =>
    `flex w-full items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left ${
      selected ? 'border-ink-3 bg-surface-2' : 'border-line bg-surface-1 hover:border-ink-3'
    }`

  return (
    <section className="space-y-3 rounded-lg border border-line bg-surface-1 p-4">
      <h2 className="text-sm font-medium">{t('swaps.create.title')}</h2>
      <p className="text-[11px] text-ink-3">{t('swaps.expiresNote')}</p>

      <div className="space-y-1.5">
        <p className="text-xs text-ink-2">{t('swaps.create.step1')}</p>
        {mine.length === 0 ? (
          <p className="text-xs text-ink-3">{t('swaps.create.noneOfMine')}</p>
        ) : (
          <div className="grid gap-1.5 sm:grid-cols-2">
            {mine.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => {
                  setFromId(a.id)
                  setToId(null)
                  setSent(false)
                }}
                className={optionClass(a.id === fromId)}
              >
                <AssignmentLabel monday={monday} assignment={a} />
              </button>
            ))}
          </div>
        )}
      </div>

      {from ? (
        <div className="space-y-1.5">
          <p className="text-xs text-ink-2">{t('swaps.create.step2')}</p>
          {candidates.length === 0 ? (
            <p className="text-xs text-ink-3">{t('swaps.create.noCandidates')}</p>
          ) : (
            <div className="grid gap-1.5 sm:grid-cols-2">
              {candidates.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => {
                    setToId(a.id)
                    setSent(false)
                  }}
                  className={optionClass(a.id === toId)}
                >
                  <span className="truncate text-xs text-ink-1">{a.user_name}</span>
                  <AssignmentLabel monday={monday} assignment={a} />
                </button>
              ))}
            </div>
          )}
        </div>
      ) : null}

      {error ? <ErrorNote errorKey={error} /> : null}
      {sent ? (
        <p role="status" className="text-xs text-ok">
          {t('swaps.create.success')}
        </p>
      ) : null}

      <button
        type="button"
        disabled={!from || !to || busy}
        onClick={submit}
        className="rounded-md bg-ink-1 px-3 py-1.5 text-xs font-medium text-surface-0 hover:opacity-90 disabled:opacity-40"
      >
        {busy ? t('swaps.create.submitting') : t('swaps.create.submit')}
      </button>
    </section>
  )
}

export function SwapsView() {
  const t = useT()
  const { user } = useAuth()
  const weeks = useWeeks()
  const [searchParams] = useSearchParams()
  const [selectedWeek, setSelectedWeek] = useState<string | null>(null)

  // §4: swaps exist only on locked (published) weeks.
  const lockedWeeks = useMemo(
    () => (weeks.data ?? []).filter((w) => w.status === 'locked'),
    [weeks.data],
  )
  const paramWeek = searchParams.get('week')
  const activeWeek =
    selectedWeek ??
    (paramWeek && lockedWeeks.some((w) => w.monday_date === paramWeek)
      ? paramWeek
      : (lockedWeeks[lockedWeeks.length - 1]?.monday_date ?? null))

  const schedule = useSchedule(activeWeek)
  const swaps = useSwaps(activeWeek)

  const names: NameById = useMemo(() => {
    const map = new Map<number, string>()
    for (const a of schedule.data?.assignments ?? []) {
      map.set(a.user_id, a.user_name)
    }
    return map
  }, [schedule.data])

  const incoming = (swaps.data ?? []).filter(
    (s) => s.to_user === user?.id && s.status === 'pending',
  )
  const others = (swaps.data ?? []).filter((s) => !incoming.includes(s))

  const reloadAll = () => {
    swaps.reload()
    schedule.reload()
  }

  return (
    <section className="space-y-5">
      <h1 className="text-lg font-medium">{t('swaps.title')}</h1>

      {weeks.loading ? <LoadingIndicator /> : null}
      {weeks.errorKey ? <ErrorNote errorKey={weeks.errorKey} onRetry={weeks.reload} /> : null}

      {!weeks.loading && lockedWeeks.length === 0 ? (
        <p className="rounded-lg border border-line bg-surface-1 px-4 py-8 text-center text-xs text-ink-2">
          {t('swaps.create.needLockedWeek')}
        </p>
      ) : null}

      {activeWeek ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <WeekPicker weeks={lockedWeeks} selected={activeWeek} onSelect={setSelectedWeek} />
            <WeekStatusBadge status="locked" />
          </div>

          {schedule.errorKey ? (
            <ErrorNote errorKey={schedule.errorKey} onRetry={schedule.reload} />
          ) : null}
          {schedule.data ? (
            <CreateSwap
              monday={activeWeek}
              assignments={schedule.data.assignments}
              onCreated={reloadAll}
            />
          ) : null}

          {swaps.loading ? <LoadingIndicator /> : null}
          {swaps.errorKey ? <ErrorNote errorKey={swaps.errorKey} onRetry={swaps.reload} /> : null}

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-ink-2">{t('swaps.incoming.title')}</h2>
            {incoming.length === 0 ? (
              <p className="text-xs text-ink-3">{t('swaps.incoming.empty')}</p>
            ) : (
              incoming.map((swap) => (
                <SwapCard
                  key={swap.id}
                  swap={swap}
                  names={names}
                  mineIsFrom={false}
                  onAnswered={reloadAll}
                />
              ))
            )}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-ink-2">{t('swaps.outgoing.title')}</h2>
            {others.length === 0 ? (
              <p className="text-xs text-ink-3">{t('swaps.outgoing.empty')}</p>
            ) : (
              others.map((swap) => (
                <SwapCard
                  key={swap.id}
                  swap={swap}
                  names={names}
                  mineIsFrom={swap.from_user === user?.id}
                  onAnswered={reloadAll}
                />
              ))
            )}
          </section>
        </>
      ) : null}
    </section>
  )
}
