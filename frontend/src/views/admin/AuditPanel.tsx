/**
 * Audit view (§5 "View audit log", §7 `GET /admin/audit`).
 *
 * §6: `actor_id` NULL is a system action — the cron solve, the 48 h swap expiry,
 * the nightly backup — and "there is deliberately no system user row". So a
 * `system` row is labelled as such, explicitly. It is never a blank cell and
 * never a missing user: §5 forbids hard-deleting users, so a null actor can only
 * mean the machine acted.
 *
 * Filtering is by tapping an action or entity chip rather than typing a code:
 * the vocabulary is the backend's (`app/audit.py`), and asking an admin on a
 * phone to spell `sacrifice_proposal` is a worse interface than letting them
 * point at one.
 */
import { useState } from 'react'

import type { AuditEntryOut, AuditQuery } from '../../api/types'
import { BUTTON_QUIET, ErrorNote, Help, LoadingIndicator, Panel } from '../../components/common'
import { useAudit } from '../../hooks/useResource'
import type { TranslationKey } from '../../i18n'
import { useLanguage, useT } from '../../i18n'
import { dateTimeLabel } from '../../lib/dates'

const PAGE_SIZE = 20

/** `app/audit.py` action verbs. An unknown verb renders as its own code. */
const ACTION_KEYS: Record<string, TranslationKey> = {
  publish: 'admin.audit.action.publish',
  solve: 'admin.audit.action.solve',
  override: 'admin.audit.action.override',
  sacrifice: 'admin.audit.action.sacrifice',
  swap: 'admin.audit.action.swap',
  credential: 'admin.audit.action.credential',
  escalate: 'admin.audit.action.escalate',
}

const ENTITY_KEYS: Record<string, TranslationKey> = {
  week: 'admin.audit.entity.week',
  constraint: 'admin.audit.entity.constraint',
  assignment: 'admin.audit.entity.assignment',
  swap_request: 'admin.audit.entity.swap_request',
  sacrifice_proposal: 'admin.audit.entity.sacrifice_proposal',
  user: 'admin.audit.entity.user',
}

function Chip({
  children,
  label,
  onClick,
}: {
  children: string
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="rounded border border-line px-1.5 py-0.5 text-[10px] text-ink-2 hover:border-ink-3 hover:text-ink-1"
    >
      {children}
    </button>
  )
}

function Entry({
  entry,
  onFilterAction,
  onFilterEntity,
}: {
  entry: AuditEntryOut
  onFilterAction: (action: string) => void
  onFilterEntity: (entity: string) => void
}) {
  const t = useT()
  const { language } = useLanguage()

  const actionKey = ACTION_KEYS[entry.action]
  const entityKey = ENTITY_KEYS[entry.entity]
  const actionLabel = actionKey ? t(actionKey) : entry.action
  const entityLabel = entityKey ? t(entityKey) : entry.entity
  // §6: null actor ⇒ system. Said in words, never left as an empty cell.
  const actor = entry.system ? t('admin.audit.systemActor') : (entry.actor_name ?? '')

  return (
    <li className="space-y-1 px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className={`truncate text-xs ${entry.system ? 'text-ink-3 italic' : 'text-ink-1'}`}>
          {actor}
        </span>
        <span className="shrink-0 text-[10px] text-ink-3">
          {dateTimeLabel(entry.created_at, language)}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip
          label={t('admin.audit.filterByAction', { action: actionLabel })}
          onClick={() => {
            onFilterAction(entry.action)
          }}
        >
          {actionLabel}
        </Chip>
        <Chip
          label={t('admin.audit.filterByEntity', { entity: entityLabel })}
          onClick={() => {
            onFilterEntity(entry.entity)
          }}
        >
          {entityLabel}
        </Chip>
      </div>
    </li>
  )
}

export function AuditPanel() {
  const t = useT()
  const [query, setQuery] = useState<AuditQuery>({
    limit: PAGE_SIZE,
    offset: 0,
    action: null,
    entity: null,
  })
  const audit = useAudit(query, true)

  const page = audit.data
  const filtered = query.action !== null || query.entity !== null
  const from = page && page.total > 0 ? page.offset + 1 : 0
  const to = page ? page.offset + page.entries.length : 0

  const setFilter = (patch: Partial<AuditQuery>) => {
    setQuery((current) => ({ ...current, ...patch, offset: 0 }))
  }

  return (
    <Panel title={t('admin.audit.title')}>
      <Help>{t('admin.audit.help')}</Help>

      {filtered ? (
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-ink-3">{t('admin.audit.filtersActive')}</span>
          <button
            type="button"
            onClick={() => {
              setFilter({ action: null, entity: null })
            }}
            className={BUTTON_QUIET}
          >
            {t('admin.audit.filtersClear')}
          </button>
        </div>
      ) : null}

      {audit.loading ? <LoadingIndicator /> : null}
      {audit.errorKey ? <ErrorNote errorKey={audit.errorKey} onRetry={audit.reload} /> : null}

      {page && page.entries.length === 0 ? <Help>{t('admin.audit.empty')}</Help> : null}

      {page && page.entries.length > 0 ? (
        <>
          <ul className="divide-y divide-line overflow-hidden rounded-md border border-line">
            {page.entries.map((entry) => (
              <Entry
                key={entry.id}
                entry={entry}
                onFilterAction={(action) => {
                  setFilter({ action })
                }}
                onFilterEntity={(entity) => {
                  setFilter({ entity })
                }}
              />
            ))}
          </ul>

          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] text-ink-3">
              {t('admin.audit.range', { from, to, total: page.total })}
            </span>
            <div className="flex gap-1.5">
              <button
                type="button"
                disabled={page.offset === 0}
                onClick={() => {
                  setQuery((current) => ({
                    ...current,
                    offset: Math.max(0, current.offset - PAGE_SIZE),
                  }))
                }}
                className={BUTTON_QUIET}
              >
                {t('common.previous')}
              </button>
              <button
                type="button"
                disabled={to >= page.total}
                onClick={() => {
                  setQuery((current) => ({ ...current, offset: current.offset + PAGE_SIZE }))
                }}
                className={BUTTON_QUIET}
              >
                {t('common.next')}
              </button>
            </div>
          </div>
        </>
      ) : null}

      <Help>{t('admin.audit.systemHelp')}</Help>
      <p className="text-[11px] text-ink-3">{t('common.romeTime')}</p>
    </Panel>
  )
}
