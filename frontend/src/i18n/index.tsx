/**
 * i18n runtime (spec §9): flat-key dictionaries, language state, `useT()`.
 *
 * The active language is persisted to localStorage now; server persistence via
 * PATCH /me/settings ships with the Settings view.
 * TODO(§9, Phase 5): also PATCH /me/settings {language} on toggle so email
 * language follows the user setting.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

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

function readStoredLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return stored === 'it' || stored === 'en' ? stored : DEFAULT_LANGUAGE
  } catch {
    return DEFAULT_LANGUAGE
  }
}

export type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string

interface LanguageContextValue {
  language: Language
  setLanguage: (language: Language) => void
  t: Translate
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(readStoredLanguage)

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Private mode etc.: the in-memory choice still applies for the session.
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

  const value = useMemo(() => ({ language, setLanguage, t }), [language, setLanguage, t])

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext)
  if (!ctx) throw new Error('useLanguage requires <LanguageProvider>')
  return ctx
}

export function useT(): Translate {
  return useLanguage().t
}
