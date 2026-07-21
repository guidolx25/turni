/**
 * In-app notification state (§10 Channel 1): "frontend polls GET /notifications
 * every 60 s". One poller for the whole authenticated app — the header bell, the
 * list view and the §2.3 blocking prompt all read this context, so three
 * consumers never mean three request loops.
 *
 * The poll pauses while the tab is hidden and fires immediately on the way back:
 * six people checking shifts between shifts should not have a backgrounded tab
 * burning a request a minute for hours.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { errorKey as toErrorKey } from '../api/client'
import { notificationsApi } from '../api/endpoints'
import type { NotificationOut } from '../api/types'
import type { TranslationKey } from '../i18n'
import { pendingProposalRef, type PendingProposalRef } from '../lib/notificationText'

export const POLL_INTERVAL_MS = 60_000

/**
 * Proposals this device has already answered.
 *
 * §7 exposes no `GET /sacrifice`, so "is this proposal still pending?" cannot be
 * asked directly: the only evidence a worker's client has is the notification
 * that opened it. An accept is later confirmed by a `sacrifice_resolved`
 * notification, but a DECLINE fires no worker-facing event at all (§10:
 * `sacrifice_escalated` goes to admins only), so without this memo a reload
 * would re-raise the blocking prompt for an offer already answered. Purely a UI
 * memo: the server is still the authority and answers 409
 * `sacrifice_already_resolved` if it is ever wrong.
 */
const ANSWERED_KEY = 'turni.sacrifice.answered'

function readAnswered(): number[] {
  try {
    const raw: unknown = JSON.parse(window.localStorage.getItem(ANSWERED_KEY) ?? '[]')
    return Array.isArray(raw) ? raw.filter((id): id is number => typeof id === 'number') : []
  } catch {
    return []
  }
}

function writeAnswered(ids: number[]): void {
  try {
    window.localStorage.setItem(ANSWERED_KEY, JSON.stringify(ids.slice(-50)))
  } catch {
    // Private mode: the in-memory set still covers this session.
  }
}

interface NotificationsContextValue {
  items: NotificationOut[]
  unreadCount: number
  loading: boolean
  errorKey: TranslationKey | null
  reload: () => void
  markRead: (ids?: number[]) => Promise<void>
  /** The §2.3 offer awaiting this worker's explicit accept/decline, if any. */
  pendingProposal: PendingProposalRef | null
  markProposalAnswered: (proposalId: number) => void
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null)

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<NotificationOut[]>([])
  const [loading, setLoading] = useState(true)
  const [errorKey, setErrorKey] = useState<TranslationKey | null>(null)
  const [answered, setAnswered] = useState<number[]>(readAnswered)
  const [tick, setTick] = useState(0)

  const reload = useCallback(() => {
    setTick((value) => value + 1)
  }, [])

  useEffect(() => {
    let cancelled = false

    const fetchNow = () => {
      if (document.visibilityState === 'hidden') return
      notificationsApi
        .list()
        .then((rows) => {
          if (cancelled) return
          setItems(rows)
          setErrorKey(null)
        })
        .catch((error: unknown) => {
          if (cancelled) return
          setErrorKey(toErrorKey(error))
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }

    fetchNow()
    const timer = setInterval(fetchNow, POLL_INTERVAL_MS)
    // Coming back to a backgrounded tab should show current state at once,
    // not up to a minute of staleness.
    document.addEventListener('visibilitychange', fetchNow)
    return () => {
      cancelled = true
      clearInterval(timer)
      document.removeEventListener('visibilitychange', fetchNow)
    }
  }, [tick])

  const markRead = useCallback(async (ids?: number[]) => {
    // Optimistic: the badge must clear on tap, not one round-trip later.
    setItems((rows) =>
      rows.map((row) => (!ids || ids.includes(row.id) ? { ...row, read: true } : row)),
    )
    await notificationsApi.markRead(ids ? { ids } : {})
  }, [])

  const markProposalAnswered = useCallback((proposalId: number) => {
    setAnswered((previous) => {
      if (previous.includes(proposalId)) return previous
      const next = [...previous, proposalId]
      writeAnswered(next)
      return next
    })
  }, [])

  const unreadCount = useMemo(() => items.filter((item) => !item.read).length, [items])

  const pendingProposal = useMemo(() => {
    // §6 UNIQUE(week_id, user_id): at most one proposal per worker per week, so
    // a `sacrifice_resolved` for a week retires that week's proposal.
    const resolvedWeeks = new Set(
      items
        .filter((item) => item.event_type === 'sacrifice_resolved')
        .map((item) => item.payload?.['week'])
        .filter((week): week is string => typeof week === 'string'),
    )
    for (const item of items) {
      const ref = pendingProposalRef(item)
      if (!ref) continue
      if (answered.includes(ref.proposalId) || resolvedWeeks.has(ref.week)) continue
      return ref
    }
    return null
  }, [items, answered])

  const value = useMemo(
    () => ({
      items,
      unreadCount,
      loading,
      errorKey,
      reload,
      markRead,
      pendingProposal,
      markProposalAnswered,
    }),
    [
      items,
      unreadCount,
      loading,
      errorKey,
      reload,
      markRead,
      pendingProposal,
      markProposalAnswered,
    ],
  )

  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
}

export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext)
  // i18n-gate-ignore: developer invariant, thrown on a wiring bug — never rendered as UI copy.
  if (!ctx) throw new Error('useNotifications requires <NotificationsProvider>')
  return ctx
}
