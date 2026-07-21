import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { en } from '../i18n/en'
import { it as itDict } from '../i18n/it'
import { renderWithProviders, stubFetch } from '../test/utils'
import { SettingsView } from './SettingsView'

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const me = {
  id: 2,
  username: 'francesco',
  display_name: 'Francesco',
  role: 'bagnino',
  is_admin: false,
  email: 'francesco@example.com',
  email_notifications: true,
  language: 'it',
  active: true,
  ics_token: 'feed-token-abc',
  capabilities: {
    trigger_solve: false,
    override_locked_slots: false,
    view_all_constraints: false,
    view_audit_log: false,
    manage_users: false,
    see_root_account: false,
  },
}

test('changing the language PATCHes /me/settings and switches the UI (§9)', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'PATCH /me/settings': { json: me },
  })

  renderWithProviders(<SettingsView />)

  const select = await screen.findByLabelText(itDict['settings.language.title'])
  fireEvent.change(select, { target: { value: 'en' } })

  // §9: persisted to the server (so emails follow) …
  await waitFor(() => {
    const patch = calls.find((c) => c.key === 'PATCH /me/settings')
    expect(patch?.body).toEqual({ language: 'en' })
  })
  // … and to localStorage …
  expect(window.localStorage.getItem('turni.language')).toBe('en')
  // … and the UI is already speaking English.
  expect(await screen.findByText(en['settings.password.title'])).toBeInTheDocument()
})

test('a failed language PATCH still switches the UI locally', async () => {
  stubFetch({
    'GET /me': { json: me },
    'PATCH /me/settings': { status: 500, json: { detail: 'generic' } },
  })

  renderWithProviders(<SettingsView />)

  fireEvent.change(await screen.findByLabelText(itDict['settings.language.title']), {
    target: { value: 'en' },
  })

  expect(await screen.findByText(en['settings.title'])).toBeInTheDocument()
})

test('toggling email notifications PATCHes the flag and re-reads /me', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'PATCH /me/settings': { json: me },
  })

  renderWithProviders(<SettingsView />)

  const toggle = await screen.findByRole('checkbox')
  expect(toggle).toBeChecked()
  fireEvent.click(toggle)

  await waitFor(() => {
    const patch = calls.find((c) => c.key === 'PATCH /me/settings')
    expect(patch?.body).toEqual({ email_notifications: false })
  })
  // Two /me reads: the initial probe and the post-write re-read.
  await waitFor(() => {
    expect(calls.filter((c) => c.key === 'GET /me').length).toBeGreaterThanOrEqual(2)
  })
})

test('mismatched new passwords are refused client-side, before any request', async () => {
  const { calls } = stubFetch({ 'GET /me': { json: me } })

  renderWithProviders(<SettingsView />)

  fireEvent.change(await screen.findByLabelText(itDict['settings.password.current']), {
    target: { value: 'old-secret' },
  })
  fireEvent.change(screen.getByLabelText(itDict['settings.password.new']), {
    target: { value: 'new-secret' },
  })
  fireEvent.change(screen.getByLabelText(itDict['settings.password.confirm']), {
    target: { value: 'typo-secret' },
  })
  fireEvent.click(screen.getByRole('button', { name: itDict['settings.password.submit'] }))

  expect(await screen.findByText(itDict['settings.password.mismatch'])).toBeInTheDocument()
  expect(calls.some((c) => c.key === 'PATCH /me/settings')).toBe(false)
})

// The status and code below are the ones `PATCH /me/settings` really returns
// (backend `app/routers/auth.py`). An earlier version of this test invented both,
// so it passed while a real mistyped password fell through to the generic
// message — a green test confirming its own fiction.
test('a password change posts both fields and surfaces the server error code', async () => {
  const { calls } = stubFetch({
    'GET /me': { json: me },
    'PATCH /me/settings': { status: 403, json: { detail: 'invalid_current_password' } },
  })

  renderWithProviders(<SettingsView />)

  fireEvent.change(await screen.findByLabelText(itDict['settings.password.current']), {
    target: { value: 'wrong' },
  })
  fireEvent.change(screen.getByLabelText(itDict['settings.password.new']), {
    target: { value: 'new-secret' },
  })
  fireEvent.change(screen.getByLabelText(itDict['settings.password.confirm']), {
    target: { value: 'new-secret' },
  })
  fireEvent.click(screen.getByRole('button', { name: itDict['settings.password.submit'] }))

  expect(await screen.findByText(itDict['errors.invalid_current_password'])).toBeInTheDocument()
  const patch = calls.find((c) => c.key === 'PATCH /me/settings')
  expect(patch?.body).toEqual({ current_password: 'wrong', new_password: 'new-secret' })
})

test('the ICS feed URL carries the caller’s own token and warns about regeneration', async () => {
  stubFetch({ 'GET /me': { json: me } })

  renderWithProviders(<SettingsView />)

  const field = await screen.findByLabelText(itDict['settings.ics.url'])
  expect(field).toHaveValue(`${window.location.origin}/export/ics?token=feed-token-abc`)
  expect(screen.getByText(itDict['settings.ics.regenerateWarning'])).toBeInTheDocument()
})

test('regenerating the ICS token confirms first, then POSTs and re-reads /me', async () => {
  const rotated = { ...me, ics_token: 'feed-token-xyz' }
  let meReads = 0
  const { calls, fetchMock } = stubFetch({
    'GET /me': { json: me },
    'POST /me/ics-token': { json: { ics_token: 'feed-token-xyz' } },
  })
  // Second /me read answers the rotated token.
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = url.split('?')[0] ?? url
    const method = init?.method ?? 'GET'
    calls.push({ key: `${method} ${path}`, body: null })
    if (path === '/me') {
      meReads += 1
      return Promise.resolve(
        new Response(JSON.stringify(meReads > 1 ? rotated : me), { status: 200 }),
      )
    }
    if (path === '/me/ics-token') {
      return Promise.resolve(
        new Response(JSON.stringify({ ics_token: 'feed-token-xyz' }), { status: 200 }),
      )
    }
    return Promise.resolve(new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 }))
  })

  renderWithProviders(<SettingsView />)

  // The destructive action is behind an explicit confirmation.
  fireEvent.click(await screen.findByRole('button', { name: itDict['settings.ics.regenerate'] }))
  expect(await screen.findByText(itDict['settings.ics.regenerateConfirm'])).toBeInTheDocument()

  const buttons = screen.getAllByRole('button', { name: itDict['settings.ics.regenerate'] })
  fireEvent.click(buttons[buttons.length - 1] as HTMLElement)

  await waitFor(() => {
    expect(calls.some((c) => c.key === 'POST /me/ics-token')).toBe(true)
  })
  await waitFor(() => {
    expect(screen.getByLabelText(itDict['settings.ics.url'])).toHaveValue(
      `${window.location.origin}/export/ics?token=feed-token-xyz`,
    )
  })
})
