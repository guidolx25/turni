/**
 * Solve / regenerate + publish (§3.2, §3.3, §7 `-- admin --`).
 *
 * The two are DELIBERATELY separate controls, not one "generate & publish"
 * button: §7 states it outright ("an INFEASIBLE solve can never publish, and the
 * manual path reviews the solved schedule before publishing"), and §3.3 gives
 * the manual path as solve → review → publish. Collapsing them would also make
 * the sacrifice park (§2.3) invisible — the case where a week must sit in
 * `solved` until a human answers.
 *
 * "Generate now" closes the submission window early (§3.2), which is why it is
 * behind an explicit confirmation stating that consequence.
 */
import { useState } from 'react'

import { errorKey as toErrorKey } from '../../api/client'
import { adminApi } from '../../api/endpoints'
import type { BlockingConstraintOut, SolveResultOut, WeekOut } from '../../api/types'
import {
  BUTTON_PRIMARY,
  ConfirmAction,
  ErrorNote,
  FieldLabel,
  Help,
  Panel,
  SuccessNote,
} from '../../components/common'
import { AlertIcon } from '../../components/icons'
import type { TranslationKey } from '../../i18n'
import { useLanguage, useT } from '../../i18n'
import { weekdayLabel } from '../../lib/dates'

/** §8 statuses. Anything else renders as "unrecognised" rather than as itself. */
const KNOWN_STATUS: Record<string, TranslationKey> = {
  optimal: 'admin.solve.status.optimal',
  feasible: 'admin.solve.status.feasible',
  infeasible: 'admin.solve.status.infeasible',
}

function statusKey(status: string): TranslationKey {
  return KNOWN_STATUS[status] ?? 'admin.solve.status.unknown'
}

function ObjectiveRows({ result }: { result: SolveResultOut }) {
  const t = useT()
  const objective = result.objective
  if (!objective) return null
  const rows: { labelKey: TranslationKey; value: number }[] = [
    { labelKey: 'admin.solve.objective.softUnmet', value: objective.soft_unmet },
    { labelKey: 'admin.solve.objective.alternation', value: objective.alternation_breaks },
    { labelKey: 'admin.solve.objective.fairness', value: objective.fairness_deviation },
    { labelKey: 'admin.solve.objective.total', value: objective.weighted_total },
  ]
  return (
    <div className="space-y-1.5">
      <FieldLabel>{t('admin.solve.objective')}</FieldLabel>
      <dl className="divide-y divide-line overflow-hidden rounded-md border border-line">
        {rows.map(({ labelKey, value }) => (
          <div key={labelKey} className="flex items-center justify-between gap-3 px-2.5 py-1.5">
            <dt className="text-[11px] text-ink-2">{t(labelKey)}</dt>
            <dd className="text-xs text-ink-1">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/**
 * The §8 minimal unsat core, rendered through the dictionaries (§9): the API
 * ships `{worker_id, day, slot}` data and never a sentence, so this is where it
 * becomes one. An id with no known name reads as "a worker" — never as a bare
 * number, which would be an internal key leaking onto an admin's phone.
 */
function BlockingList({
  blocking,
  monday,
  names,
}: {
  blocking: BlockingConstraintOut[]
  monday: string
  names: Map<number, string>
}) {
  const t = useT()
  const { language } = useLanguage()
  return (
    <div className="space-y-2 rounded-md border border-danger-dim bg-danger-dim/15 px-3 py-2.5">
      <p className="flex items-center gap-2 text-xs font-medium text-danger">
        <AlertIcon className="h-3.5 w-3.5 shrink-0" />
        {t('admin.solve.blocking')}
      </p>
      <ul className="space-y-1">
        {blocking.map((item, index) => (
          <li key={`${String(item.worker_id)}:${item.day}:${item.slot}:${String(index)}`}>
            <span className="text-xs text-ink-1">
              {t('admin.solve.blocking.item', {
                who: names.get(item.worker_id) ?? t('admin.solve.blocking.unknownWorker'),
                day: weekdayLabel(monday, item.day, language),
                slot: t(`slot.${item.slot}`),
              })}
            </span>
          </li>
        ))}
      </ul>
      <Help>{t('admin.solve.blocking.help')}</Help>
      <p className="text-[11px] text-danger">{t('admin.solve.infeasibleNote')}</p>
    </div>
  )
}

export function SolvePanel({
  week,
  names,
  onChanged,
}: {
  week: WeekOut
  names: Map<number, string>
  onChanged: () => void
}) {
  const t = useT()
  const { language } = useLanguage()
  const [result, setResult] = useState<SolveResultOut | null>(null)
  const [solveError, setSolveError] = useState<TranslationKey | null>(null)
  const [publishError, setPublishError] = useState<TranslationKey | null>(null)
  const [published, setPublished] = useState(false)
  const [publishing, setPublishing] = useState(false)

  const solve = async () => {
    setSolveError(null)
    setResult(null)
    setPublished(false)
    try {
      setResult(await adminApi.solve(week.monday_date))
    } catch (error: unknown) {
      setSolveError(toErrorKey(error))
    } finally {
      onChanged()
    }
  }

  const publish = () => {
    setPublishing(true)
    setPublishError(null)
    adminApi
      .publish(week.monday_date)
      .then(() => {
        setPublished(true)
      })
      .catch((error: unknown) => {
        setPublishError(toErrorKey(error))
      })
      .finally(() => {
        setPublishing(false)
        onChanged()
      })
  }

  const seconds = result
    ? new Intl.NumberFormat(language, { maximumFractionDigits: 2 }).format(result.solve_seconds)
    : ''

  return (
    <>
      <Panel title={t('admin.solve.title')}>
        <Help>{t('admin.solve.help')}</Help>
        {/* §3.4: a published week is regenerated by nobody — swaps or override. */}
        {week.status === 'locked' ? (
          <Help>{t('errors.week_already_locked')}</Help>
        ) : (
          <ConfirmAction
            label={t('admin.solve.generate')}
            confirmLabel={t('admin.solve.confirmAction')}
            consequence={t('admin.solve.confirm')}
            busyLabel={t('admin.solve.working')}
            onConfirm={solve}
          />
        )}
        {solveError ? <ErrorNote errorKey={solveError} /> : null}

        {result ? (
          <div className="space-y-3">
            <div className="space-y-1">
              <FieldLabel>{t('admin.solve.result')}</FieldLabel>
              <p
                className={`text-sm ${result.status === 'infeasible' ? 'text-danger' : 'text-ok'}`}
              >
                {t(statusKey(result.status))}
              </p>
              <p className="text-[11px] text-ink-3">{t('admin.solve.duration', { seconds })}</p>
            </div>
            <ObjectiveRows result={result} />
            {result.blocking_constraints.length > 0 ? (
              <BlockingList
                blocking={result.blocking_constraints}
                monday={week.monday_date}
                names={names}
              />
            ) : null}
          </div>
        ) : null}
      </Panel>

      <Panel title={t('admin.publish.title')}>
        <Help>{t('admin.publish.help')}</Help>
        {week.status === 'locked' ? (
          <Help>{t('admin.publish.alreadyPublished')}</Help>
        ) : (
          <>
            {week.status !== 'solved' ? <Help>{t('admin.publish.needsSolved')}</Help> : null}
            <button
              type="button"
              disabled={publishing || week.status !== 'solved'}
              onClick={publish}
              className={BUTTON_PRIMARY}
            >
              {publishing ? t('admin.publish.working') : t('admin.publish.submit')}
            </button>
          </>
        )}
        {publishError ? <ErrorNote errorKey={publishError} /> : null}
        {published ? <SuccessNote>{t('admin.publish.done')}</SuccessNote> : null}
      </Panel>
    </>
  )
}
