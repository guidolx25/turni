import { screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { it as itDict } from '../i18n/it'
import { renderWithProviders, stubFetch } from '../test/utils'
import { ScheduleView } from './ScheduleView'

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
  capabilities: {
    trigger_solve: false,
    override_locked_slots: false,
    view_all_constraints: false,
    view_audit_log: false,
    manage_users: false,
    see_root_account: false,
  },
}

const lockedWeek = {
  monday_date: '2026-07-13',
  status: 'locked',
  submission_deadline: '2026-07-12T15:00:00Z',
  solved_at: '2026-07-12T15:00:05Z',
  locked_at: '2026-07-12T15:00:06Z',
}

const schedule = {
  monday_date: '2026-07-13',
  status: 'locked',
  assignments: [
    {
      id: 1,
      day: 'mon',
      slot: 'am',
      role: 'bagnino',
      user_id: 2,
      user_name: 'Francesco',
      source: 'solver',
    },
    {
      id: 2,
      day: 'mon',
      slot: 'am',
      role: 'spiaggino',
      user_id: 4,
      user_name: 'Amir',
      source: 'solver',
    },
  ],
}

test('locked week renders the grid with role chips and the published marker', async () => {
  stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [lockedWeek] },
    'GET /schedule': { json: schedule },
  })

  renderWithProviders(<ScheduleView />)

  expect(await screen.findByText('Amir')).toBeInTheDocument()
  expect(screen.getByText('Francesco')).toBeInTheDocument()
  // Own shift is emphasized and tappable (starts the swap flow).
  expect(screen.getByText(itDict['schedule.you'])).toBeInTheDocument()
  expect(screen.getByText(itDict['schedule.published'])).toBeInTheDocument()
})

test('an open week shows the not-published state and never fetches the grid', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [{ ...lockedWeek, status: 'open', locked_at: null }] },
  })

  renderWithProviders(<ScheduleView />)

  expect(await screen.findByText(itDict['schedule.notPublished.title'])).toBeInTheDocument()
  expect(calls.some((c) => c.key === 'GET /schedule')).toBe(false)
})
