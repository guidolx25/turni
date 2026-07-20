import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { it as itDict } from '../i18n/it'
import { renderWithProviders, stubFetch } from '../test/utils'
import { SwapsView } from './SwapsView'

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
  ics_token: 'feed-token',
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

// Francesco's own bagnino row, a matching bagnino row held by Matteo, and a
// spiaggino row that a core bagnino may never take (§4 role validity).
const schedule = {
  monday_date: '2026-07-13',
  status: 'locked',
  assignments: [
    {
      id: 10,
      day: 'mon',
      slot: 'am',
      role: 'bagnino',
      user_id: 2,
      user_name: 'Francesco',
      source: 'solver',
    },
    {
      id: 11,
      day: 'mon',
      slot: 'pm',
      role: 'bagnino',
      user_id: 1,
      user_name: 'Matteo',
      source: 'solver',
    },
    {
      id: 12,
      day: 'mon',
      slot: 'pm',
      role: 'spiaggino',
      user_id: 4,
      user_name: 'Amir',
      source: 'solver',
    },
  ],
}

const incoming = {
  id: 77,
  week: '2026-07-13',
  from_user: 1,
  to_user: 2, // addressed to me → answerable
  from_assignment: { id: 11, day: 'mon', slot: 'pm', role: 'bagnino', user_id: 1 },
  to_assignment: { id: 10, day: 'mon', slot: 'am', role: 'bagnino', user_id: 2 },
  status: 'pending',
  created_at: '2026-07-12T16:00:00Z',
  resolved_at: null,
}

test('an incoming pending swap is answerable and accepting posts to the API', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [lockedWeek] },
    'GET /schedule': { json: schedule },
    'GET /swaps': { json: [incoming] },
    'POST /swaps/77/accept': { json: { ...incoming, status: 'applied' } },
  })

  renderWithProviders(<SwapsView />)

  const accept = await screen.findByRole('button', { name: itDict['swaps.accept'] })
  fireEvent.click(accept)

  await waitFor(() => {
    expect(calls.some((c) => c.key === 'POST /swaps/77/accept')).toBe(true)
  })
})

test('a swap I sent is shown but offers me no accept button', async () => {
  // Same swap, reversed: I am the requester, so §4 gives me nothing to answer.
  const outgoing = { ...incoming, from_user: 2, to_user: 1 }
  stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [lockedWeek] },
    'GET /schedule': { json: schedule },
    'GET /swaps': { json: [outgoing] },
  })

  renderWithProviders(<SwapsView />)

  expect(await screen.findByText(itDict['swaps.status.pending'])).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: itDict['swaps.accept'] })).not.toBeInTheDocument()
})

test('a server refusal surfaces through the dictionary, not as a raw code', async () => {
  stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [lockedWeek] },
    'GET /schedule': { json: schedule },
    'GET /swaps': { json: [incoming] },
    'POST /swaps/77/accept': { status: 422, json: { detail: 'swap_h3_violation' } },
  })

  renderWithProviders(<SwapsView />)

  fireEvent.click(await screen.findByRole('button', { name: itDict['swaps.accept'] }))

  // §9: the user reads a sentence in their language — never `swap_h3_violation`.
  expect(await screen.findByText(itDict['errors.swap_h3_violation'])).toBeInTheDocument()
  expect(screen.queryByText('swap_h3_violation')).not.toBeInTheDocument()
})
