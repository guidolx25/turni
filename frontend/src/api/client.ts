/**
 * Thin typed fetch wrapper for the §7 API (same-origin, session cookie).
 *
 * Backend errors arrive as `{detail: "snake_case_code"}`; they surface as
 * `ApiError` whose `code` maps to the `errors.<code>` dictionary key, with
 * `errors.generic` / `errors.network` as fallbacks. A 401 anywhere invokes the
 * unauthorized handler installed by the auth provider, which routes to /login.
 */
import type { TranslationKey } from '../i18n/it'
import { it } from '../i18n/it'

/**
 * §7 (v1.11): every API route is namespaced under this prefix.
 *
 * It exists so the API and the §9 client routes cannot collide: `/swaps` is a
 * react-router view, `/api/swaps` is the endpoint. Endpoint functions pass
 * spec-shaped paths (`/me`, `/swaps/{id}/accept`) and `request` prepends this —
 * so this is the one place the prefix appears in the frontend, and the only
 * place it should. A `fetch` that bypasses `request` bypasses this too.
 */
export const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string) {
    super(code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/** Dictionary key for any failure — `errors.<code>` when known, else generic. */
export function errorKey(error: unknown): TranslationKey {
  if (error instanceof ApiError) {
    const candidate = `errors.${error.code}`
    if (candidate in it) return candidate as TranslationKey
    return 'errors.generic'
  }
  return 'errors.network'
}

type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null

/** Installed once by the auth provider; fires on any 401 outside /auth/login. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  onUnauthorized = handler
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  /** /auth/login handles its own 401 (bad credentials, not a dead session). */
  skipUnauthorizedHandler?: boolean
}

async function parseCode(response: Response): Promise<string> {
  try {
    const data: unknown = await response.json()
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const { detail } = data
      if (typeof detail === 'string') return detail
    }
  } catch {
    // Non-JSON error body: fall through to the generic code.
  }
  return 'generic'
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, skipUnauthorizedHandler = false } = options
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    if (response.status === 401 && !skipUnauthorizedHandler) {
      onUnauthorized?.()
    }
    throw new ApiError(response.status, await parseCode(response))
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
