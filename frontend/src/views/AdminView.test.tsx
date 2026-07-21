import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import App from '../App'
import { it as itDict } from '../i18n/it'
import { weekdayLabel } from '../lib/dates'
import { renderWithProviders, stubFetch } from '../test/utils'
import { AdminView } from './AdminView'

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const MONDAY = '2026-07-13'

const NO_CAPABILITIES = {
  trigger_solve: false,
  override_locked_slots: false,
  view_all_constraints: false,
  view_audit_log: false,
  manage_users: false,
  see_root_account: false,
}

const ADMIN_CAPABILITIES = {
  ...NO_CAPABILITIES,
  trigger_solve: true,
  override_locked_slots: true,
  view_all_constraints: true,
  view_audit_log: true,
}

function me(capabilities: typeof NO_CAPABILITIES) {
  return {
    id: 5,
    username: 'mattia',
    display_name: 'Mattia',
    role: 'jolly',
    is_admin: capabilities.trigger_solve,
    email: null,
    email_notifications: true,
    language: 'it',
    active: true,
    ics_token: 'token',
    capabilities,
  }
}

function week(status: 'open' | 'solved' | 'locked') {
  return {
    monday_date: MONDAY,
    status,
    submission_deadline: '2026-07-12T15:00:00Z',
    solved_at: null,
    locked_at: null,
  }
}

const SUBMISSIONS = {
  week: MONDAY,
  status: 'open',
  constraints: [
    {
      id: 1,
      user_id: 2,
      user_name: 'Francesco',
      day: 'fri',
      slot: 'full_day',
      kind: 'hard',
      note: null,
      created_at: '2026-07-08T09:00:00Z',
      updated_at: '2026-07-08T09:00:00Z',
    },
  ],
}

// §5 row 3 ("Trigger solve / regenerate": worker —): the panel is not merely
// hidden behind a nav item, it is unreachable by URL.
test('a worker without trigger_solve gets no admin nav entry and no admin route', async () => {
  stubFetch({
    'GET /me': { json: me(NO_CAPABILITIES) },
    'GET /notifications': { json: [] },
    'GET /weeks': { json: [week('open')] },
  })

  renderWithProviders(<App />, '/admin')

  // Redirected to the schedule, which is what a worker may see.
  expect(await screen.findByText(itDict['schedule.title'])).toBeInTheDocument()
  expect(screen.queryByText(itDict['admin.title'])).not.toBeInTheDocument()
  expect(screen.queryByLabelText(itDict['nav.admin'])).not.toBeInTheDocument()
  expect(screen.queryByLabelText(itDict['nav.root'])).not.toBeInTheDocument()
})

test('an admin gets the admin nav entry but not the root one (§5 row 7)', async () => {
  stubFetch({
    'GET /me': { json: me(ADMIN_CAPABILITIES) },
    'GET /notifications': { json: [] },
    'GET /weeks': { json: [week('open')] },
    'GET /admin/constraints': { json: SUBMISSIONS },
    'GET /admin/audit': { json: { total: 0, limit: 20, offset: 0, entries: [] } },
  })

  renderWithProviders(<App />, '/admin')

  expect(await screen.findByText(itDict['admin.title'])).toBeInTheDocument()
  expect(screen.getByLabelText(itDict['nav.admin'])).toBeInTheDocument()
  expect(screen.queryByLabelText(itDict['nav.root'])).not.toBeInTheDocument()
})

// §2.3 / §8: the unsat core is DATA on the wire ({worker_id, day, slot}) and
// becomes a sentence only here, in the viewer's language (§6 v1.5).
test('an INFEASIBLE solve renders the blocking constraints through the dictionaries', async () => {
  stubFetch({
    'GET /me': { json: me(ADMIN_CAPABILITIES) },
    'GET /weeks': { json: [week('open')] },
    'GET /admin/constraints': { json: SUBMISSIONS },
    'GET /admin/audit': { json: { total: 0, limit: 20, offset: 0, entries: [] } },
    'POST /admin/solve': {
      json: {
        status: 'infeasible',
        solve_seconds: 0.42,
        objective: null,
        blocking_constraints: [{ worker_id: 2, day: 'fri', slot: 'full_day', kind: 'hard' }],
      },
    },
  })

  renderWithProviders(<AdminView />)

  // §3.2: "Generate now" closes the window early, so it takes two taps.
  fireEvent.click(await screen.findByRole('button', { name: itDict['admin.solve.generate'] }))
  expect(screen.getByText(itDict['admin.solve.confirm'])).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: itDict['admin.solve.confirmAction'] }))

  expect(await screen.findByText(itDict['admin.solve.status.infeasible'])).toBeInTheDocument()

  const expected = itDict['admin.solve.blocking.item']
    .replace('{who}', 'Francesco')
    .replace('{day}', weekdayLabel(MONDAY, 'fri', 'it'))
    .replace('{slot}', itDict['slot.full_day'])
  expect(screen.getByText(expected)).toBeInTheDocument()
  // An infeasible week can never publish (§7).
  expect(screen.getByText(itDict['admin.solve.infeasibleNote'])).toBeInTheDocument()
})

// An unknown worker id must degrade to a word, never surface as a raw id.
test('a blocking constraint whose worker has no known name reads as "a worker"', async () => {
  stubFetch({
    'GET /me': { json: me(ADMIN_CAPABILITIES) },
    'GET /weeks': { json: [week('open')] },
    'GET /admin/constraints': { json: { ...SUBMISSIONS, constraints: [] } },
    'GET /admin/audit': { json: { total: 0, limit: 20, offset: 0, entries: [] } },
    'POST /admin/solve': {
      json: {
        status: 'infeasible',
        solve_seconds: 0.1,
        objective: null,
        blocking_constraints: [{ worker_id: 99, day: 'fri', slot: 'pm', kind: 'hard' }],
      },
    },
  })

  renderWithProviders(<AdminView />)

  fireEvent.click(await screen.findByRole('button', { name: itDict['admin.solve.generate'] }))
  fireEvent.click(screen.getByRole('button', { name: itDict['admin.solve.confirmAction'] }))

  const expected = itDict['admin.solve.blocking.item']
    .replace('{who}', itDict['admin.solve.blocking.unknownWorker'])
    .replace('{day}', weekdayLabel(MONDAY, 'fri', 'it'))
    .replace('{slot}', itDict['slot.pm'])
  expect(await screen.findByText(expected)).toBeInTheDocument()
})

// §7: solve and publish are DISTINCT steps — the manual path reviews the solved
// schedule before publishing, so solving must never publish as a side effect.
test('solving does not publish; publishing is a second, explicit action', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me(ADMIN_CAPABILITIES) },
    'GET /weeks': { json: [week('solved')] },
    'GET /admin/constraints': { json: SUBMISSIONS },
    'GET /admin/audit': { json: { total: 0, limit: 20, offset: 0, entries: [] } },
    'POST /admin/solve': {
      json: {
        status: 'optimal',
        solve_seconds: 0.2,
        objective: {
          soft_unmet: 0,
          alternation_breaks: 1,
          fairness_deviation: 0,
          spread_shared_pairs: 0,
          jolly_days: 3,
          weighted_total: 103,
        },
        blocking_constraints: [],
      },
    },
    'POST /admin/publish': { json: week('locked') },
  })

  renderWithProviders(<AdminView />)

  fireEvent.click(await screen.findByRole('button', { name: itDict['admin.solve.generate'] }))
  fireEvent.click(screen.getByRole('button', { name: itDict['admin.solve.confirmAction'] }))

  await waitFor(() => {
    expect(calls.some((call) => call.key === 'POST /admin/solve')).toBe(true)
  })
  expect(calls.some((call) => call.key === 'POST /admin/publish')).toBe(false)

  fireEvent.click(screen.getByRole('button', { name: itDict['admin.publish.submit'] }))

  await waitFor(() => {
    expect(calls.some((call) => call.key === 'POST /admin/publish')).toBe(true)
  })
  expect(await screen.findByText(itDict['admin.publish.done'])).toBeInTheDocument()
})

// §6: "actor_id NULL means a system action ... There is deliberately no system
// user row." So it renders as an explicit actor, never as a blank.
test('the audit view names a NULL actor as the system, not as an empty cell', async () => {
  stubFetch({
    'GET /me': { json: me(ADMIN_CAPABILITIES) },
    'GET /weeks': { json: [week('solved')] },
    'GET /admin/constraints': { json: SUBMISSIONS },
    'GET /admin/audit': {
      json: {
        total: 2,
        limit: 20,
        offset: 0,
        entries: [
          {
            id: 2,
            actor_id: null,
            actor_name: null,
            system: true,
            action: 'solve',
            entity: 'week',
            entity_id: 7,
            payload: null,
            created_at: '2026-07-12T15:00:03Z',
          },
          {
            id: 1,
            actor_id: 5,
            actor_name: 'Mattia',
            system: false,
            action: 'override',
            entity: 'assignment',
            entity_id: 12,
            payload: null,
            created_at: '2026-07-11T09:00:00Z',
          },
        ],
      },
    },
  })

  renderWithProviders(<AdminView />)

  expect(await screen.findByText(itDict['admin.audit.systemActor'])).toBeInTheDocument()
  expect(screen.getByText('Mattia')).toBeInTheDocument()
  // Both action verbs read as words, not as their backend codes.
  expect(screen.getByText(itDict['admin.audit.action.solve'])).toBeInTheDocument()
  expect(screen.getByText(itDict['admin.audit.action.override'])).toBeInTheDocument()
  expect(screen.getByText(itDict['admin.audit.systemHelp'])).toBeInTheDocument()
})

// §5/§3.4: an unpublished week is regenerated, never overridden.
test('override is refused on an unpublished week and offered on a locked one', async () => {
  stubFetch({
    'GET /me': { json: me(ADMIN_CAPABILITIES) },
    'GET /weeks': { json: [week('open')] },
    'GET /admin/constraints': { json: SUBMISSIONS },
    'GET /admin/audit': { json: { total: 0, limit: 20, offset: 0, entries: [] } },
  })

  renderWithProviders(<AdminView />)

  expect(await screen.findByText(itDict['admin.override.needsLocked'])).toBeInTheDocument()
  expect(screen.queryByLabelText(itDict['admin.override.slot'])).not.toBeInTheDocument()
})

test('an override names the slot, warns before committing, and POSTs the natural key', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me(ADMIN_CAPABILITIES) },
    'GET /weeks': { json: [week('locked')] },
    'GET /admin/constraints': { json: SUBMISSIONS },
    'GET /admin/audit': { json: { total: 0, limit: 20, offset: 0, entries: [] } },
    'GET /schedule': {
      json: {
        monday_date: MONDAY,
        status: 'locked',
        assignments: [
          {
            id: 31,
            day: 'mon',
            slot: 'am',
            role: 'bagnino',
            user_id: 2,
            user_name: 'Francesco',
            source: 'solver',
          },
          {
            id: 32,
            day: 'mon',
            slot: 'am',
            role: 'spiaggino',
            user_id: 3,
            user_name: 'Pasha',
            source: 'solver',
          },
        ],
      },
    },
    'POST /admin/override': {
      json: {
        assignment: {
          id: 31,
          day: 'mon',
          slot: 'am',
          role: 'bagnino',
          user_id: 3,
          user_name: 'Pasha',
          source: 'override',
        },
        previous_user_id: 2,
        new_user_id: 3,
        created: false,
        violations: [{ rule: 'H4', user_id: 3, day: 'mon', slot: null }],
      },
    },
  })

  renderWithProviders(<AdminView />)

  // The consequence is on screen before the commit, not after it.
  expect(await screen.findByText(itDict['admin.override.warning'])).toBeInTheDocument()

  fireEvent.change(screen.getByLabelText(itDict['admin.override.slot']), {
    target: { value: '31' },
  })
  fireEvent.change(screen.getByLabelText(itDict['admin.override.newHolder']), {
    target: { value: '3' },
  })
  fireEvent.click(screen.getByRole('button', { name: itDict['admin.override.confirmAction'] }))

  await waitFor(() => {
    const call = calls.find((entry) => entry.key === 'POST /admin/override')
    expect(call?.body).toEqual({
      week: MONDAY,
      day: 'mon',
      slot: 'am',
      role: 'bagnino',
      user_id: 3,
      assignment_id: 31,
    })
  })

  // §5 allows an override to leave H2-H4 standing — so it must report them.
  const violation = itDict['admin.override.violation.h4']
    .replace('{name}', 'Pasha')
    .replace('{day}', weekdayLabel(MONDAY, 'mon', 'it'))
  expect(await screen.findByText(violation)).toBeInTheDocument()
})

test('the submissions view distinguishes binding from preference', async () => {
  stubFetch({
    'GET /me': { json: me(ADMIN_CAPABILITIES) },
    'GET /weeks': { json: [week('open')] },
    'GET /admin/audit': { json: { total: 0, limit: 20, offset: 0, entries: [] } },
    'GET /admin/constraints': {
      json: {
        week: MONDAY,
        status: 'open',
        constraints: [
          { ...SUBMISSIONS.constraints[0], id: 1, kind: 'hard' },
          {
            ...SUBMISSIONS.constraints[0],
            id: 2,
            user_id: 3,
            user_name: 'Pasha',
            day: 'tue',
            slot: 'am',
            kind: 'soft',
          },
        ],
      },
    },
  })

  renderWithProviders(<AdminView />)

  expect(await screen.findByText('Francesco')).toBeInTheDocument()
  expect(screen.getByText('Pasha')).toBeInTheDocument()
  expect(screen.getByText(itDict['constraints.kind.hard'])).toBeInTheDocument()
  expect(screen.getByText(itDict['constraints.kind.soft'])).toBeInTheDocument()
})
