/** Shared test helpers: provider wrapper + a tiny path-matched fetch stub. */
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { AuthProvider } from '../auth/AuthContext'
import { LanguageProvider } from '../i18n'

export function renderWithProviders(ui: ReactNode, route = '/') {
  return render(
    <LanguageProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </AuthProvider>
    </LanguageProvider>,
  )
}

export interface StubRoute {
  status?: number
  json: unknown
}

/**
 * Stub global fetch: `routes` maps "METHOD /path" (query string stripped) to a
 * response. Unmatched requests 404 so a test never silently hits the network.
 */
export function stubFetch(routes: Record<string, StubRoute>) {
  const calls: { key: string; body: unknown }[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const path = url.split('?')[0] ?? url
    const method = init?.method ?? 'GET'
    const key = `${method} ${path}`
    calls.push({
      key,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
    })
    const route = routes[key]
    if (!route) {
      return Promise.resolve(new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 }))
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
