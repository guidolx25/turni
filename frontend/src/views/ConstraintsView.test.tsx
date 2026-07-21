import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { it as itDict } from '../i18n/it'
import { renderWithProviders, stubFetch } from '../test/utils'
import { ConstraintsView } from './ConstraintsView'

afterEach(() => {
  vi.unstubAllGlobals()
})

/** The per-day expand control. Weekday labels come from Intl, so the rows are
 *  addressed by position rather than by a hardcoded Italian day name. */
async function dayToggle(index: number) {
  const toggles = await screen.findAllByRole('button', { name: /^Modifica /u })
  const toggle = toggles.at(index)
  if (!toggle) throw new Error(`no day toggle at index ${String(index)}`)
  return toggle
}

const firstDayToggle = () => dayToggle(0)

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

// Far enough out that the Sunday-17:00 deadline has not passed, so the week is
// genuinely editable and a read-only assertion below means the STATUS caused it.
const openWeek = {
  monday_date: '2099-07-13',
  status: 'open',
  submission_deadline: '2099-07-12T15:00:00Z',
  solved_at: null,
  locked_at: null,
}

test('marking a slot posts an upsert with the week, day, slot and kind', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [openWeek] },
    'GET /constraints': { json: [] },
    'POST /constraints': {
      json: {
        id: 1,
        week: openWeek.monday_date,
        day: 'mon',
        slot: 'am',
        kind: 'soft',
        note: null,
        created_at: '2099-07-01T10:00:00Z',
        updated_at: '2099-07-01T10:00:00Z',
      },
    },
  })

  renderWithProviders(<ConstraintsView />)

  // The weekday label comes from Intl, so find the day row by its open control.
  fireEvent.click(await firstDayToggle())

  fireEvent.click(await screen.findByRole('button', { name: itDict['slot.am'] }))

  await waitFor(() => {
    expect(calls.some((c) => c.key === 'POST /constraints')).toBe(true)
  })
  const post = calls.find((c) => c.key === 'POST /constraints')
  expect(post?.body).toMatchObject({
    week: openWeek.monday_date,
    slot: 'am',
    // §2.2 S1 vs §2.1 H7: a request must default to the SOFT reading. Defaulting
    // to hard would let a careless tap make the week infeasible.
    kind: 'soft',
  })
})

test('a published week is read-only and says why', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [{ ...openWeek, status: 'locked', locked_at: '2099-07-12T15:00:06Z' }] },
    'GET /constraints': { json: [] },
  })

  renderWithProviders(<ConstraintsView />)

  expect(await screen.findByText(itDict['constraints.readOnly.locked'])).toBeInTheDocument()

  // §3.1: editing is closed — every slot control is disabled, so the reason above
  // is not merely decorative next to working buttons.
  fireEvent.click(await firstDayToggle())
  const amButton = await screen.findByRole('button', { name: itDict['slot.am'] })
  expect(amButton).toBeDisabled()

  fireEvent.click(amButton)
  expect(calls.some((c) => c.key === 'POST /constraints')).toBe(false)
})

test('a hard weekend request warns that a human, not the solver, will handle it', async () => {
  stubFetch({
    'GET /me': { json: me },
    'GET /weeks': { json: [openWeek] },
    'GET /constraints': {
      json: [
        {
          id: 7,
          week: openWeek.monday_date,
          day: 'sat',
          slot: 'full_day',
          kind: 'hard',
          note: null,
          created_at: '2099-07-01T10:00:00Z',
          updated_at: '2099-07-01T10:00:00Z',
        },
      ],
    },
  })

  renderWithProviders(<ConstraintsView />)

  // Days render mon..sun, so index 5 is Saturday — expand it to reach the editor.
  fireEvent.click(await dayToggle(5)) // mon..sun → index 5 is Saturday

  // §2.1 H5 + §10 weekend_hard_escalated: the weekend is a fixed template no
  // solve can absorb, so the user must learn at the point of choosing that this
  // goes to an admin rather than being scheduled around.
  expect(await screen.findByText(itDict['constraints.weekend.hardWarning'])).toBeInTheDocument()
})
