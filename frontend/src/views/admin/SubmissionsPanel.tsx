/**
 * Every worker's submissions for a week (§5 "View all constraint submissions",
 * §7 `GET /admin/constraints?week=`).
 *
 * Hard and soft wear the same two tones as the worker's own editor
 * (`KindBadge`): the distinction §2.1 H7 / §2.2 S1 draws is the one an admin
 * reads a submission list to see, so it must not be a different visual language
 * on this screen than on the one where it was chosen.
 */
import type { AdminConstraintsOut } from '../../api/types'
import { ErrorNote, Help, KindBadge, LoadingIndicator, Panel } from '../../components/common'
import type { Resource } from '../../hooks/useResource'
import { useLanguage, useT } from '../../i18n'
import { weekdayLabel } from '../../lib/dates'

interface Group {
  userId: number
  userName: string
  rows: AdminConstraintsOut['constraints']
}

/** Server order is (display_name, day, slot); grouping preserves it. */
function groupByWorker(data: AdminConstraintsOut): Group[] {
  const groups: Group[] = []
  for (const row of data.constraints) {
    const last = groups[groups.length - 1]
    if (last && last.userId === row.user_id) last.rows.push(row)
    else groups.push({ userId: row.user_id, userName: row.user_name, rows: [row] })
  }
  return groups
}

export function SubmissionsPanel({
  monday,
  resource,
}: {
  monday: string
  resource: Resource<AdminConstraintsOut>
}) {
  const t = useT()
  const { language } = useLanguage()
  const groups = resource.data ? groupByWorker(resource.data) : []

  return (
    <Panel title={t('admin.submissions.title')}>
      <Help>{t('admin.submissions.help')}</Help>

      {resource.loading ? <LoadingIndicator /> : null}
      {resource.errorKey ? (
        <ErrorNote errorKey={resource.errorKey} onRetry={resource.reload} />
      ) : null}

      {resource.data && groups.length === 0 ? <Help>{t('admin.submissions.empty')}</Help> : null}

      {groups.length > 0 ? (
        <ul className="divide-y divide-line overflow-hidden rounded-md border border-line">
          {groups.map((group) => (
            <li key={group.userId} className="space-y-1.5 px-3 py-2.5">
              <p className="text-xs font-medium text-ink-1">{group.userName}</p>
              <ul className="space-y-1">
                {group.rows.map((row) => (
                  <li key={row.id} className="flex items-start gap-2">
                    <KindBadge kind={row.kind} />
                    <span className="text-[11px] text-ink-2">
                      {t('admin.submissions.item', {
                        day: weekdayLabel(monday, row.day, language),
                        slot: t(`slot.${row.slot}`),
                      })}
                      {row.note ? ` — ${row.note}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  )
}
