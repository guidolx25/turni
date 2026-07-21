import { fireEvent, screen } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import { it as itDict } from '../i18n/it'
import { renderWithProviders, stubFetch } from '../test/utils'
import { LoginView } from './LoginView'

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

test('login form posts credentials and navigates on success', async () => {
  const { calls } = stubFetch({
    // 401 on first load (no session), then the real row: AuthContext re-reads
    // /me after a successful POST rather than trusting the login response.
    'GET /me': [{ status: 401, json: { detail: 'not_authenticated' } }, { json: me }],
    'POST /auth/login': { json: me },
  })

  renderWithProviders(
    <Routes>
      <Route path="/login" element={<LoginView />} />
      <Route path="/" element={<div data-testid="home" />} />
    </Routes>,
    '/login',
  )

  fireEvent.change(await screen.findByLabelText(itDict['login.username']), {
    target: { value: 'francesco' },
  })
  fireEvent.change(screen.getByLabelText(itDict['login.password']), {
    target: { value: 'segreto' },
  })
  fireEvent.click(screen.getByRole('button', { name: itDict['login.submit'] }))

  await screen.findByTestId('home')
  const login = calls.find((c) => c.key === 'POST /auth/login')
  expect(login?.body).toEqual({ username: 'francesco', password: 'segreto' })
})

test('invalid credentials surface the dictionary error', async () => {
  stubFetch({
    'GET /me': { status: 401, json: { detail: 'not_authenticated' } },
    'POST /auth/login': { status: 401, json: { detail: 'invalid_credentials' } },
  })

  renderWithProviders(
    <Routes>
      <Route path="/login" element={<LoginView />} />
    </Routes>,
    '/login',
  )

  fireEvent.change(await screen.findByLabelText(itDict['login.username']), {
    target: { value: 'francesco' },
  })
  fireEvent.change(screen.getByLabelText(itDict['login.password']), {
    target: { value: 'sbagliata' },
  })
  fireEvent.click(screen.getByRole('button', { name: itDict['login.submit'] }))

  expect(await screen.findByText(itDict['errors.invalid_credentials'])).toBeInTheDocument()
})
