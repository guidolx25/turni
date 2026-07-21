/**
 * §2.3 sacrifice proposal — the blocking prompt.
 *
 * "Requires explicit accept/decline. Never resolve silently." So this is a modal
 * with no dismissal path: no close button, no backdrop click, no Escape handler,
 * no auto-timeout. It is deliberately NOT a toast — the week cannot publish
 * until this worker answers, and an offer that can be swiped away is an offer
 * that resolves silently by neglect.
 *
 * What is being traded is stated in full (§2.3 "What is being traded"): the hard
 * request survives either way, only the weekday free-day placement moves.
 */
import { useState } from 'react'

import { errorKey as toErrorKey } from '../api/client'
import { sacrificeApi } from '../api/endpoints'
import type { TranslationKey } from '../i18n'
import { useLanguage, useT } from '../i18n'
import { weekRangeLabel, weekdayLabel } from '../lib/dates'
import type { PendingProposalRef } from '../lib/notificationText'
import { useNotifications } from '../notifications/NotificationsContext'
import { ErrorNote } from './common'
import { AlertIcon } from './icons'

export function SacrificePrompt({ proposal }: { proposal: PendingProposalRef }) {
  const t = useT()
  const { language } = useLanguage()
  const { markProposalAnswered, reload } = useNotifications()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)

  const answer = (action: 'accept' | 'decline') => {
    setBusy(true)
    setError(null)
    const call =
      action === 'accept'
        ? sacrificeApi.accept(proposal.proposalId)
        : sacrificeApi.decline(proposal.proposalId)
    call
      .then(() => {
        markProposalAnswered(proposal.proposalId)
        reload()
      })
      .catch((err: unknown) => {
        const key = toErrorKey(err)
        // Already answered elsewhere (another device, a stale tab): the offer is
        // genuinely closed, so stop blocking rather than trapping the user.
        if (key === 'errors.sacrifice_already_resolved' || key === 'errors.sacrifice_not_found') {
          markProposalAnswered(proposal.proposalId)
          reload()
          return
        }
        setError(key)
      })
      .finally(() => {
        setBusy(false)
      })
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="sacrifice-title"
      className="fixed inset-0 z-50 flex items-end justify-center bg-surface-0/90 p-4 backdrop-blur-sm sm:items-center"
    >
      <div className="w-full max-w-md space-y-4 rounded-lg border border-spiaggino-dim bg-surface-1 p-5">
        <header className="flex items-center gap-2">
          <AlertIcon className="h-5 w-5 shrink-0 text-spiaggino" />
          <h2 id="sacrifice-title" className="text-base font-medium text-ink-1">
            {t('sacrifice.title')}
          </h2>
        </header>

        <p className="text-sm leading-relaxed text-ink-1">
          {t('sacrifice.question', {
            week: weekRangeLabel(proposal.week, language),
            day: weekdayLabel(proposal.week, proposal.proposedFreeDay, language),
          })}
        </p>

        <p className="rounded-md border border-line bg-surface-2 px-3 py-2 text-xs leading-relaxed text-ink-2">
          {t('sacrifice.keepsHard')}
        </p>

        <ul className="space-y-1.5 text-xs leading-relaxed text-ink-2">
          <li>{t('sacrifice.acceptConsequence')}</li>
          <li>{t('sacrifice.declineConsequence')}</li>
        </ul>

        {error ? <ErrorNote errorKey={error} /> : null}

        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              answer('accept')
            }}
            className="flex-1 rounded-md bg-ok-dim px-3 py-2.5 text-sm font-medium text-ok hover:opacity-90 disabled:opacity-50"
          >
            {busy ? t('sacrifice.working') : t('sacrifice.accept')}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              answer('decline')
            }}
            className="flex-1 rounded-md border border-danger-dim px-3 py-2.5 text-sm text-danger hover:bg-danger-dim/30 disabled:opacity-50"
          >
            {t('sacrifice.decline')}
          </button>
        </div>
      </div>
    </div>
  )
}
