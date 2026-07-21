/**
 * Notifications list (§9, §10 Channel 1). Every row is rendered from its
 * structured payload through the dictionaries (`lib/notificationText`), so the
 * same stored event reads in Italian or English depending on who is looking.
 * Rows the backend sent with an unfamiliar `event_type` still render a sentence.
 */
import { useEffect } from 'react'

import type { NotificationOut } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { ErrorNote, LoadingIndicator } from '../components/common'
import { useLanguage, useT } from '../i18n'
import { relativeAge } from '../lib/dates'
import { renderNotification } from '../lib/notificationText'
import { useNotifications } from '../notifications/NotificationsContext'

function NotificationRow({ notification }: { notification: NotificationOut }) {
  const t = useT()
  const { language } = useLanguage()
  const { user } = useAuth()
  const { line, conflict } = renderNotification(notification, t, language, user?.id ?? null)

  return (
    <li
      className={`space-y-1.5 rounded-lg border px-3 py-2.5 ${
        notification.read ? 'border-line bg-surface-1' : 'border-spiaggino-dim bg-spiaggino-dim/15'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm leading-relaxed text-ink-1">{line}</p>
        {!notification.read ? (
          <span className="mt-1 shrink-0 rounded-full border border-spiaggino-dim px-1.5 py-0.5 text-[10px] text-spiaggino">
            {t('notifications.unread')}
          </span>
        ) : null}
      </div>

      {conflict.length > 0 ? (
        <div className="rounded-md border border-line bg-surface-2 px-2.5 py-2">
          <p className="text-[10px] tracking-wide uppercase text-ink-3">
            {t('notif.conflict.title')}
          </p>
          <ul className="mt-1 space-y-0.5">
            {conflict.map((item) => (
              <li key={item} className="text-xs text-ink-2">
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="text-[11px] text-ink-3">
        {relativeAge(notification.created_at, new Date(), language)}
      </p>
    </li>
  )
}

export function NotificationsView() {
  const t = useT()
  const { items, unreadCount, loading, errorKey, reload, markRead } = useNotifications()

  // Opening the list is the read receipt (§10 has no per-row read affordance).
  useEffect(() => {
    if (unreadCount === 0) return
    void markRead().catch(() => {
      // The badge already cleared optimistically; the next poll re-reconciles.
    })
    // Runs when unread rows appear while the list is open, too.
  }, [unreadCount, markRead])

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-lg font-medium">{t('notifications.title')}</h1>
        {items.length > 0 ? (
          <button
            type="button"
            onClick={() => {
              void markRead().catch(() => {
                /* optimistic; reconciled by the next poll */
              })
            }}
            className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 hover:border-ink-3 hover:text-ink-1"
          >
            {t('notifications.markAllRead')}
          </button>
        ) : null}
      </div>

      {loading ? <LoadingIndicator /> : null}
      {errorKey ? <ErrorNote errorKey={errorKey} onRetry={reload} /> : null}

      {!loading && items.length === 0 ? (
        <p className="rounded-lg border border-line bg-surface-1 px-4 py-10 text-center text-xs text-ink-2">
          {t('notifications.empty')}
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((notification) => (
            <NotificationRow key={notification.id} notification={notification} />
          ))}
        </ul>
      )}
    </section>
  )
}
