/** Shared test helpers: provider wrapper + a tiny path-matched fetch stub. */
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { AuthProvider } from '../auth/AuthContext'
import { LanguageProvider } from '../i18n'
import { NotificationsProvider } from '../notifications/NotificationsContext'

export function renderWithProviders(ui: ReactNode, route = '/') {
  return render(
    <LanguageProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </AuthProvider>
    </LanguageProvider>,
  )
}

/**
 * For views that read the §10 notification poll. Adds <NotificationsProvider>,
 * which starts a GET /notifications on mount — stub that route.
 */
export function renderWithNotifications(ui: ReactNode, route = '/') {
  return render(
    <LanguageProvider>
      <AuthProvider>
        <NotificationsProvider>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </NotificationsProvider>
      </AuthProvider>
    </LanguageProvider>,
  )
}

export interface StubRoute {
  status?: number
  json: unknown
}

/**
 * A route may be a single response or a SEQUENCE consumed one call at a time,
 * with the last entry repeating. Sequences exist for genuinely stateful flows —
 * `GET /me` is 401 before login and 200 after, and a test that could not express
 * that would have to pretend the app re-reads nothing after authenticating.
 */
export type StubResponse = StubRoute | StubRoute[]

/**
 * Stub global fetch: `routes` maps "METHOD /path" (query string stripped) to a
 * response. Unmatched requests 404 so a test never silently hits the network.
 */
export function stubFetch(routes: Record<string, StubResponse>) {
  const calls: { key: string; body: unknown }[] = []
  const consumed: Record<string, number> = {}
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = url.split('?')[0] ?? url
    const method = init?.method ?? 'GET'
    const key = `${method} ${path}`
    calls.push({
      key,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
    })
    const entry = routes[key]
    if (!entry) {
      return Promise.resolve(new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 }))
    }
    let route: StubRoute
    if (Array.isArray(entry)) {
      const index = consumed[key] ?? 0
      route = entry[Math.min(index, entry.length - 1)] as StubRoute
      consumed[key] = index + 1
    } else {
      route = entry
    }
    return Promise.resolve(
      new Response(JSON.stringify(route.json), {
        status: route.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}
