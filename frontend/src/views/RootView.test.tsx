import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import App from '../App'
import { it as itDict } from '../i18n/it'
import { renderWithProviders, stubFetch } from '../test/utils'
import { RootView } from './RootView'

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const CAPABILITIES = {
  trigger_solve: true,
  override_locked_slots: true,
  view_all_constraints: true,
  view_audit_log: true,
  manage_users: true,
  see_root_account: true,
}

const ROOT_ME = {
  id: 1,
  username: 'matteo',
  display_name: 'Matteo',
  role: 'bagnino',
  is_admin: true,
  email: null,
  email_notifications: true,
  language: 'it',
  active: true,
  ics_token: 'token',
  capabilities: CAPABILITIES,
}

const USERS = [
  {
    id: 1,
    username: 'matteo',
    display_name: 'Matteo',
    role: 'bagnino',
    is_admin: true,
    email: null,
    email_notifications: true,
    language: 'it',
    active: true,
    created_at: '2026-05-01T08:00:00Z',
  },
  {
    id: 3,
    username: 'pasha',
    display_name: 'Pasha',
    role: 'spiaggino',
    is_admin: false,
    email: 'pasha@example.com',
    email_notifications: true,
    language: 'en',
    active: false,
    created_at: '2026-05-01T08:00:00Z',
  },
]

test('the user list renders every account the API returns', async () => {
  stubFetch({
    'GET /me': { json: ROOT_ME },
    'GET /root/users': { json: USERS },
  })

  renderWithProviders(<RootView />)

  expect(await screen.findByText('Matteo')).toBeInTheDocument()
  expect(screen.getByText('Pasha')).toBeInTheDocument()
  expect(screen.getByText(itDict['root.status.active'])).toBeInTheDocument()
  expect(screen.getByText(itDict['root.status.inactive'])).toBeInTheDocument()
})

// §5: root is visible only to itself, and `is_root` is serialized nowhere — so
// the UI has nothing to render a root badge FROM, and must not invent one.
test('no row is marked as the root account', async () => {
  stubFetch({
    'GET /me': { json: ROOT_ME },
    'GET /root/users': { json: USERS },
  })

  renderWithProviders(<RootView />)

  await screen.findByText('Matteo')
  const badges = screen.getAllByText(itDict['root.badge.admin'])
  // Exactly one admin badge (Matteo is `is_admin`), and nothing beyond it: no
  // second, root-specific marking derived from the username.
  expect(badges).toHaveLength(1)
})

// §5: "Users are never hard-deleted. Deactivation via users.active = false is
// the only removal: the root panel offers deactivate, not delete."
test('an active user is offered deactivation, never deletion', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: ROOT_ME },
    'GET /root/users': { json: USERS },
    'PATCH /root/users/1': { json: { ...USERS[0], active: false } },
  })

  renderWithProviders(<RootView />)

  fireEvent.click(
    await screen.findByRole('button', {
      name: itDict['root.edit.open'].replace('{name}', 'Matteo'),
    }),
  )

  // The reason deletion is not on offer is part of the interface.
  expect(screen.getByText(itDict['root.deactivate.why'])).toBeInTheDocument()
  expect(screen.getByRole('button', { name: itDict['root.deactivate.submit'] })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: itDict['root.deactivate.submit'] }))
  fireEvent.click(screen.getByRole('button', { name: itDict['root.deactivate.confirmAction'] }))

  await waitFor(() => {
    const call = calls.find((entry) => entry.key === 'PATCH /root/users/1')
    expect(call?.body).toEqual({ active: false })
  })
  // Removal is a PATCH of `active`, never a DELETE.
  expect(calls.some((entry) => entry.key.startsWith('DELETE /root/users'))).toBe(false)
})

test('a deactivated user is offered reactivation instead', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: ROOT_ME },
    'GET /root/users': { json: USERS },
    'PATCH /root/users/3': { json: { ...USERS[1], active: true } },
  })

  renderWithProviders(<RootView />)

  fireEvent.click(
    await screen.findByRole('button', {
      name: itDict['root.edit.open'].replace('{name}', 'Pasha'),
    }),
  )

  expect(
    screen.queryByRole('button', { name: itDict['root.deactivate.submit'] }),
  ).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: itDict['root.reactivate.submit'] }))

  await waitFor(() => {
    const call = calls.find((entry) => entry.key === 'PATCH /root/users/3')
    expect(call?.body).toEqual({ active: true })
  })
})

test('creating a user posts the §7 body and reloads the list', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: ROOT_ME },
    'GET /root/users': { json: USERS },
    'POST /root/users': { json: { ...USERS[1], id: 9, username: 'amir' } },
  })

  renderWithProviders(<RootView />)

  fireEvent.change(await screen.findByLabelText(itDict['root.field.username']), {
    target: { value: 'amir' },
  })
  fireEvent.change(screen.getByLabelText(itDict['root.field.displayName']), {
    target: { value: 'Amir' },
  })
  fireEvent.change(screen.getByLabelText(itDict['root.field.role']), {
    target: { value: 'spiaggino' },
  })
  fireEvent.change(screen.getByLabelText(itDict['root.field.password']), {
    target: { value: 'initial-secret' },
  })
  fireEvent.click(screen.getByRole('button', { name: itDict['root.create.submit'] }))

  await waitFor(() => {
    const call = calls.find((entry) => entry.key === 'POST /root/users')
    expect(call?.body).toEqual({
      username: 'amir',
      display_name: 'Amir',
      role: 'spiaggino',
      email: null,
      is_admin: false,
      language: 'it',
      password: 'initial-secret',
    })
  })
  expect(await screen.findByText(itDict['root.create.done'])).toBeInTheDocument()
})

test('resetting a password posts only the new one (§7: no current password)', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: ROOT_ME },
    'GET /root/users': { json: USERS },
    'POST /root/users/3/password': { json: {} },
  })

  renderWithProviders(<RootView />)

  fireEvent.click(
    await screen.findByRole('button', {
      name: itDict['root.edit.open'].replace('{name}', 'Pasha'),
    }),
  )
  fireEvent.change(screen.getByLabelText(itDict['root.password.new']), {
    target: { value: 'brand-new-secret' },
  })
  fireEvent.click(screen.getByRole('button', { name: itDict['root.password.submit'] }))

  await waitFor(() => {
    const call = calls.find((entry) => entry.key === 'POST /root/users/3/password')
    expect(call?.body).toEqual({ new_password: 'brand-new-secret' })
  })
})

// §5 row 7 is root-only: an admin must not reach /root, by nav or by URL.
test('an admin without manage_users cannot reach the root panel', async () => {
  stubFetch({
    'GET /me': { json: { ...ROOT_ME, capabilities: { ...CAPABILITIES, manage_users: false } } },
    'GET /notifications': { json: [] },
    'GET /weeks': { json: [] },
  })

  renderWithProviders(<App />, '/root')

  expect(await screen.findByText(itDict['schedule.title'])).toBeInTheDocument()
  expect(screen.queryByText(itDict['root.title'])).not.toBeInTheDocument()
})
