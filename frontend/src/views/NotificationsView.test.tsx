import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { it as itDict } from '../i18n/it'
import { renderWithNotifications, stubFetch } from '../test/utils'
import { NotificationsView } from './NotificationsView'

afterEach(() => {
  vi.unstubAllGlobals()
})

const me = {
  id: 2,
  username: 'francesco',
  display_name: 'Francesco',
  role: 'bagnino',
  is_admin: false,
  email: null,
  email_notifications: true,
  language: 'it',
  active: true,
  ics_token: 'tok',
  capabilities: {
    trigger_solve: false,
    override_locked_slots: false,
    view_all_constraints: false,
    view_audit_log: false,
    manage_users: false,
    see_root_account: false,
  },
}

const WEEK = '2026-07-13'

function row(id: number, event_type: string, payload: unknown, read = false) {
  return { id, event_type, payload, read, created_at: '2026-07-12T15:00:00Z' }
}

test('renders every event type from its structured payload', async () => {
  stubFetch({
    'GET /me': { json: me },
    'GET /notifications': {
      json: [
        row(1, 'schedule_published', { week: WEEK }),
        row(2, 'swap_requested', {
          week: WEEK,
          from_user: 3,
          to_user: 2,
          from_assignment: { id: 1, day: 'mon', slot: 'am', role: 'bagnino' },
          to_assignment: { id: 2, day: 'thu', slot: 'pm', role: 'bagnino' },
          status: 'pending',
        }),
        row(3, 'sacrifice_escalated', {
          week: WEEK,
          outcome: 'declined',
          conflict: [{ worker_id: 2, day: 'fri', slot: 'am' }],
        }),
        row(4, 'weekend_hard_escalated', {
          week: WEEK,
          display_name: 'Pasha',
          day: 'sat',
          slot: 'full_day',
          user_id: 3,
          constraint_id: 8,
          reason: 'weekend_template_fixed',
        }),
      ],
    },
    'POST /notifications/read': { status: 204, json: null },
  })

  renderWithNotifications(<NotificationsView />)

  expect(await screen.findByText(/Turni pubblicati/)).toBeInTheDocument()
  expect(screen.getByText(/richiesta di scambio/i)).toBeInTheDocument()
  expect(screen.getByText(/Conflitto irrisolto/)).toBeInTheDocument()
  expect(screen.getByText(/Pasha/)).toBeInTheDocument()
  // The §8 unsat core is rendered through the dictionary, not as JSON.
  expect(screen.getByText(itDict['notif.conflict.title'])).toBeInTheDocument()
  expect(screen.getByText(/La tua richiesta/)).toBeInTheDocument()
  expect(screen.queryByText(/worker_id/)).not.toBeInTheDocument()
})

test('an unknown event type degrades to a generic line instead of crashing', async () => {
  stubFetch({
    'GET /me': { json: me },
    'GET /notifications': {
      json: [row(9, 'quantum_shift_assigned', { totally: { new: ['shape'] } })],
    },
    'POST /notifications/read': { status: 204, json: null },
  })

  renderWithNotifications(<NotificationsView />)

  expect(await screen.findByText(itDict['notif.unknown'])).toBeInTheDocument()
  expect(screen.queryByText(/quantum_shift_assigned/)).not.toBeInTheDocument()
})

test('opening the list marks the caller’s notifications read (§7 all-rows form)', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'GET /notifications': { json: [row(1, 'schedule_published', { week: WEEK })] },
    'POST /notifications/read': { status: 204, json: null },
  })

  renderWithNotifications(<NotificationsView />)

  await screen.findByText(/Turni pubblicati/)
  await waitFor(() => {
    expect(calls.some((c) => c.key === 'POST /notifications/read')).toBe(true)
  })
  const read = calls.find((c) => c.key === 'POST /notifications/read')
  expect(read?.body).toEqual({})
})

test('an already-read list neither shows the badge nor re-marks it read', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'GET /notifications': { json: [row(1, 'schedule_published', { week: WEEK }, true)] },
    'POST /notifications/read': { status: 204, json: null },
  })

  renderWithNotifications(<NotificationsView />)

  await screen.findByText(/Turni pubblicati/)
  expect(screen.queryByText(itDict['notifications.unread'])).not.toBeInTheDocument()
  expect(calls.some((c) => c.key === 'POST /notifications/read')).toBe(false)
})

test('an empty feed says so', async () => {
  stubFetch({ 'GET /me': { json: me }, 'GET /notifications': { json: [] } })
  renderWithNotifications(<NotificationsView />)
  expect(await screen.findByText(itDict['notifications.empty'])).toBeInTheDocument()
})

test('mark-all-read is available and posts the all-rows body', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'GET /notifications': { json: [row(1, 'schedule_published', { week: WEEK }, true)] },
    'POST /notifications/read': { status: 204, json: null },
  })

  renderWithNotifications(<NotificationsView />)

  fireEvent.click(await screen.findByText(itDict['notifications.markAllRead']))
  await waitFor(() => {
    expect(calls.filter((c) => c.key === 'POST /notifications/read')).toHaveLength(1)
  })
})
