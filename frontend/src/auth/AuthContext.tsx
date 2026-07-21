/**
 * Session state (§7: HttpOnly cookie, so the only probe is GET /me).
 * On mount: GET /me → user, or anonymous on 401. Any later 401 from the API
 * client clears the user, and the route guard redirects to /login.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { setUnauthorizedHandler } from '../api/client'
import { authApi } from '../api/endpoints'
import type { LoginIn, MeOut } from '../api/types'

interface AuthContextValue {
  user: MeOut | null
  /** True until the initial GET /me settles — the guard waits, not redirects. */
  initializing: boolean
  login: (credentials: LoginIn) => Promise<void>
  logout: () => Promise<void>
  /** Re-read /me after a settings write (language, email, ICS token). */
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeOut | null>(null)
  const [initializing, setInitializing] = useState(true)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null)
    })
    return () => {
      setUnauthorizedHandler(null)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    authApi
      .me()
      .then((me) => {
        if (!cancelled) setUser(me)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setInitializing(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const refreshUser = useCallback(async () => {
    setUser(await authApi.me())
  }, [])

  const login = useCallback(
    async (credentials: LoginIn) => {
      // §7: /auth/login answers UserOut — it establishes the session but carries
      // neither `capabilities` nor `ics_token`. GET /me is what produces the
      // MeOut the app renders from, so the two states can never disagree.
      await authApi.login(credentials)
      await refreshUser()
    },
    [refreshUser],
  )

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, initializing, login, logout, refreshUser }),
    [user, initializing, login, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  // i18n-gate-ignore: developer invariant, thrown on a wiring bug — never rendered as UI copy.
  if (!ctx) throw new Error('useAuth requires <AuthProvider>')
  return ctx
}
