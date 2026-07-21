import { fireEvent, screen, waitFor } from '@testing-library/react'
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

// --- §3.2 solved: the reviewer sees the grid, the worker sees nothing --------
//
// The backend has always implemented this (`GET /schedule`: visible when
// `status is LOCKED or has_admin_capability`). This view gated the *request* on
// `locked` alone, so the preview was never asked for and an admin reviewing a
// solved week saw the worker's empty state — with no way to publish, because the
// only publish control lived on a panel they had not found.

const solvedWeek = {
  ...lockedWeek,
  status: 'solved',
  locked_at: null,
}

const solvedSchedule = { ...schedule, status: 'solved' }

const adminMe = {
  ...me,
  id: 5,
  username: 'mattia',
  display_name: 'Mattia',
  is_admin: true,
  capabilities: { ...me.capabilities, trigger_solve: true, override_locked_slots: true },
}

test('an admin previews a solved week: the grid renders and says it is not yet published', async () => {
  stubFetch({
    'GET /me': { json: adminMe },
    'GET /weeks': { json: [solvedWeek] },
    'GET /schedule': { json: solvedSchedule },
  })

  renderWithProviders(<ScheduleView />)

  expect(await screen.findByText('Amir')).toBeInTheDocument()
  // The preview must never be mistaken for the published week.
  expect(screen.getByText(itDict['schedule.preview'])).toBeInTheDocument()
  expect(screen.queryByText(itDict['schedule.published'])).not.toBeInTheDocument()
})

test('the publish action is offered inline beside the solved grid', async () => {
  stubFetch({
    'GET /me': { json: adminMe },
    'GET /weeks': { json: [solvedWeek] },
    'GET /schedule': { json: solvedSchedule },
  })

  renderWithProviders(<ScheduleView />)

  expect(
    await screen.findByRole('button', { name: itDict['admin.publish.submit'] }),
  ).toBeInTheDocument()
})

test('publishing from the schedule view POSTs the same admin endpoint', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: adminMe },
    'GET /weeks': { json: [solvedWeek] },
    'GET /schedule': { json: solvedSchedule },
    'POST /admin/publish': { json: { monday_date: '2026-07-13', status: 'locked' } },
  })

  renderWithProviders(<ScheduleView />)
  fireEvent.click(await screen.findByRole('button', { name: itDict['admin.publish.submit'] }))

  await waitFor(() => {
    expect(calls.some((c) => c.key === 'POST /admin/publish')).toBe(true)
  })
})

test('a worker sees nothing on a solved week and never fetches the grid', async () => {
  // The negative half of §3.2, and the one that must never regress: `solved`
  // exists so reviewers can look BEFORE workers can. A worker seeing the draft
  // would publish the schedule by accident.
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [solvedWeek] },
  })

  renderWithProviders(<ScheduleView />)

  expect(await screen.findByText(itDict['schedule.notPublished.title'])).toBeInTheDocument()
  expect(screen.getByText(itDict['schedule.notPublished.solved'])).toBeInTheDocument()
  expect(calls.some((c) => c.key === 'GET /schedule')).toBe(false)
  expect(screen.queryByText(itDict['schedule.preview'])).not.toBeInTheDocument()
})

test('a worker is offered no publish control on a solved week', async () => {
  stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [solvedWeek] },
  })

  renderWithProviders(<ScheduleView />)

  await screen.findByText(itDict['schedule.notPublished.title'])
  expect(
    screen.queryByRole('button', { name: itDict['admin.publish.submit'] }),
  ).not.toBeInTheDocument()
})
