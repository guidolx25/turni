/** Small shared presentational pieces — one look across every view (§9). */
import type { TranslationKey } from '../i18n'
import { useLanguage, useT } from '../i18n'
import type { WeekOut, WeekStatus } from '../api/types'
import { weekRangeLabel } from '../lib/dates'
import { LockIcon } from './icons'

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
