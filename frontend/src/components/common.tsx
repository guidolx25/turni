/** Small shared presentational pieces — one look across every view (§9). */
import { useState, type ReactNode } from 'react'

import type { TranslationKey } from '../i18n'
import { useLanguage, useT } from '../i18n'
import type { ConstraintKind, WeekOut, WeekStatus } from '../api/types'
import { weekRangeLabel } from '../lib/dates'
import { LockIcon } from './icons'

/** One card. The schedule grid, the admin panel and settings all sit in these. */
export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border border-line bg-surface-1 p-4">
      <h2 className="text-sm font-medium text-ink-1">{title}</h2>
      {children}
    </section>
  )
}

export function Help({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-relaxed text-ink-2">{children}</p>
}

/** Section eyebrow — the uppercase micro-label above a group of controls. */
export function FieldLabel({ children }: { children: ReactNode }) {
  return <p className="text-[10px] tracking-wide uppercase text-ink-3">{children}</p>
}

export const FIELD_CLASS =
  'w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-ink-1 outline-none focus:border-ink-3 disabled:opacity-50'

export const BUTTON_PRIMARY =
  'rounded-md bg-ink-1 px-3 py-1.5 text-xs font-medium text-surface-0 hover:opacity-90 disabled:opacity-40'

export const BUTTON_QUIET =
  'rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 hover:border-ink-3 hover:text-ink-1 disabled:opacity-50'

export function SuccessNote({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="text-xs text-ok">
      {children}
    </p>
  )
}

/**
 * §2.1 H7 vs §2.2 S1 wear the same two tones everywhere they appear — the
 * worker's own constraint editor and the admin's submissions view — so "binding"
 * never reads as one thing on one screen and another elsewhere.
 */
export function KindBadge({ kind }: { kind: ConstraintKind }) {
  const t = useT()
  const tone =
    kind === 'hard'
      ? 'border-danger bg-danger-dim/40 text-danger'
      : 'border-bagnino bg-bagnino-dim/40 text-bagnino'
  return (
    <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] ${tone}`}>
      {t(`constraints.kind.${kind}`)}
    </span>
  )
}

/**
 * A consequential action behind an explicit two-step confirmation: the trigger
 * reveals the consequence in words, and only the second tap acts. Used wherever
 * §3.2/§5 make an action irreversible or visible to other people (closing the
 * submission window early, overriding a published slot, deactivating a user).
 *
 * Deliberately not a toast and not a `window.confirm`: the consequence copy is
 * part of the layout, translated, and stays on screen while the user decides.
 */
export function ConfirmAction({
  label,
  confirmLabel,
  consequence,
  busyLabel,
  disabled = false,
  tone = 'default',
  onConfirm,
}: {
  label: string
  confirmLabel: string
  consequence: string
  busyLabel: string
  disabled?: boolean
  tone?: 'default' | 'danger'
  /** Must settle: the prompt stays open and busy until it does. */
  onConfirm: () => Promise<void>
}) {
  const t = useT()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const run = () => {
    setBusy(true)
    void onConfirm().finally(() => {
      setBusy(false)
      setConfirming(false)
    })
  }

  if (!confirming) {
    return (
      <button
        type="button"
        disabled={disabled || busy}
        onClick={() => {
          setConfirming(true)
        }}
        className={
          tone === 'danger'
            ? 'rounded-md border border-danger/40 px-2.5 py-1 text-xs text-danger hover:bg-danger-dim/40 disabled:opacity-40'
            : BUTTON_PRIMARY
        }
      >
        {label}
      </button>
    )
  }

  return (
    <div
      className={`space-y-2 rounded-md border px-3 py-2.5 ${
        tone === 'danger' ? 'border-danger-dim bg-danger-dim/15' : 'border-line bg-surface-2'
      }`}
    >
      <p className="text-xs leading-relaxed text-ink-2">{consequence}</p>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={run}
          className={
            tone === 'danger'
              ? 'rounded-md bg-danger-dim px-2.5 py-1 text-xs font-medium text-danger hover:opacity-90 disabled:opacity-50'
              : BUTTON_PRIMARY
          }
        >
          {busy ? busyLabel : confirmLabel}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setConfirming(false)
          }}
          className={BUTTON_QUIET}
        >
          {t('common.cancel')}
        </button>
      </div>
    </div>
  )
}

export function LoadingIndicator() {
  const t = useT()
  return (
    <p role="status" className="py-8 text-center text-sm text-ink-3">
      {t('common.loading')}
    </p>
  )
}

export function ErrorNote({
  errorKey: key,
  onRetry,
}: {
  errorKey: TranslationKey
  onRetry?: () => void
}) {
  const t = useT()
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-md border border-danger-dim bg-danger-dim/30 px-3 py-2 text-sm text-danger"
    >
      <span>{t(key)}</span>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded border border-danger/40 px-2 py-0.5 text-xs hover:bg-danger-dim"
        >
          {t('common.retry')}
        </button>
      ) : null}
    </div>
  )
}

const STATUS_STYLE: Record<WeekStatus, string> = {
  open: 'text-ink-2 border-line',
  solved: 'text-spiaggino border-spiaggino-dim',
  locked: 'text-ok border-ok-dim',
}

export function WeekStatusBadge({ status }: { status: WeekStatus }) {
  const t = useT()
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${STATUS_STYLE[status]}`}
    >
      {status === 'locked' ? <LockIcon className="h-3 w-3" /> : null}
      {t(`week.status.${status}`)}
    </span>
  )
}

export function WeekPicker({
  weeks,
  selected,
  onSelect,
}: {
  weeks: WeekOut[]
  selected: string | null
  onSelect: (monday: string) => void
}) {
  const t = useT()
  const { language } = useLanguage()
  return (
    <select
      aria-label={t('schedule.pickWeek')}
      value={selected ?? ''}
      onChange={(e) => {
        onSelect(e.target.value)
      }}
      className="w-full rounded-md border border-line bg-surface-1 px-3 py-2 text-sm text-ink-1 outline-none focus:border-ink-3 sm:w-auto"
    >
      {weeks.map((week) => (
        <option key={week.monday_date} value={week.monday_date}>
          {weekRangeLabel(week.monday_date, language)}
          {' — '}
          {t(`week.status.${week.status}`)}
        </option>
      ))}
    </select>
  )
}
