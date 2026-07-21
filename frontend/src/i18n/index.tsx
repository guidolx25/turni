/**
 * i18n runtime (spec §9): flat-key dictionaries, language state, `useT()`.
 *
 * §9 requires the active language to be persisted to localStorage *and* to
 * `users.language`, so email templates follow the same setting (§10 Channel 2).
 * `setLanguage` therefore writes both: localStorage synchronously (it is the
 * pre-auth source of truth — the login screen has no session to read) and
 * `PATCH /me/settings` fire-and-forget. The PATCH is deliberately not awaited
 * and its failure is deliberately swallowed: the UI language is a local
 * preference that must switch instantly whether or not the network agrees, and
 * a signed-out visitor toggling on /login must not see an error.
 *
 * `setLanguage(next, { sync: false })` is the one exception — used when we are
 * *adopting* the server's stored value, where echoing it back is a pointless
 * round-trip.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

import { meApi } from '../api/endpoints'
import { en } from './en'
import { it, type TranslationKey } from './it'

export type Language = 'it' | 'en'
export type { TranslationKey }

const DICTIONARIES: Record<Language, Record<TranslationKey, string>> = {
  it,
  en,
}

const STORAGE_KEY = 'turni.language'
const DEFAULT_LANGUAGE: Language = 'it'

function isLanguage(value: unknown): value is Language {
  return value === 'it' || value === 'en'
}

/** The stored preference, or null when the user has never chosen one here. */
function readStoredLanguage(): Language | null {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return isLanguage(stored) ? stored : null
  } catch {
    return null
  }
}

export type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string

export interface SetLanguageOptions {
  /** False when adopting the server's own value — see the module comment. */
  sync?: boolean
}

interface LanguageContextValue {
  language: Language
  /** True once the user has expressed a choice on this device. */
  hasStoredPreference: boolean
  setLanguage: (language: Language, options?: SetLanguageOptions) => void
  t: Translate
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

export function LanguageProvider({ children }: { children: ReactNode }) {
  const stored = readStoredLanguage()
  const [language, setLanguageState] = useState<Language>(stored ?? DEFAULT_LANGUAGE)
  const [hasStoredPreference, setHasStoredPreference] = useState(stored !== null)

  const setLanguage = useCallback((next: Language, options: SetLanguageOptions = {}) => {
    const { sync = true } = options
    setLanguageState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
      setHasStoredPreference(true)
    } catch {
      // Private mode etc.: the in-memory choice still applies for the session.
    }
    if (sync) {
      // §9: users.language drives the language of the emails (§10), so the
      // server has to learn about the toggle too.
      void meApi.updateSettings({ language: next }).catch(() => {
        // Signed out, offline, or the endpoint is unreachable: the local
        // preference already applied and is re-sent on the next toggle.
      })
    }
  }, [])

  const t = useCallback<Translate>(
    (key, params) => {
      let text = DICTIONARIES[language][key]
      if (params) {
        for (const [name, value] of Object.entries(params)) {
          text = text.replaceAll(`{${name}}`, String(value))
        }
      }
      return text
    },
    [language],
  )

  const value = useMemo(
    () => ({ language, hasStoredPreference, setLanguage, t }),
    [language, hasStoredPreference, setLanguage, t],
  )

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext)
  // i18n-gate-ignore: developer invariant, thrown on a wiring bug — never rendered as UI copy.
  if (!ctx) throw new Error('useLanguage requires <LanguageProvider>')
  return ctx
}

export function useT(): Translate {
  return useLanguage().t
}
