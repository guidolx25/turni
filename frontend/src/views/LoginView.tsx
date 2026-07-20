/** Login (§7 POST /auth/login). Centered card, dictionary-driven states. */
import { useState, type SyntheticEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { errorKey as toErrorKey } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { ErrorNote } from '../components/common'
import type { TranslationKey } from '../i18n'
import { useT } from '../i18n'

export function LoginView() {
  const t = useT()
  const navigate = useNavigate()
  const { user, initializing, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)

  if (!initializing && user) return <Navigate to="/" replace />

  const onSubmit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    login({ username, password })
      .then(() => {
        void navigate('/', { replace: true })
      })
      .catch((err: unknown) => {
        setError(toErrorKey(err))
      })
      .finally(() => {
        setSubmitting(false)
      })
  }

  const inputClass =
    'w-full rounded-md border border-line bg-surface-0 px-3 py-2 text-sm text-ink-1 outline-none placeholder:text-ink-3 focus:border-ink-3'

  return (
    <div className="grid min-h-screen place-items-center bg-surface-0 px-4">
      <div className="w-full max-w-xs">
        <h1 className="mb-6 text-center text-sm font-semibold tracking-[0.3em] uppercase text-ink-2">
          {t('app.name')}
        </h1>
        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-lg border border-line bg-surface-1 p-5"
        >
          <h2 className="text-lg font-medium">{t('login.title')}</h2>
          <label className="block space-y-1.5">
            <span className="text-xs text-ink-2">{t('login.username')}</span>
            <input
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              required
              value={username}
              onChange={(e) => {
                setUsername(e.target.value)
              }}
              className={inputClass}
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs text-ink-2">{t('login.password')}</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => {
                setPassword(e.target.value)
              }}
              className={inputClass}
            />
          </label>
          {error ? <ErrorNote errorKey={error} /> : null}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-ink-1 px-3 py-2 text-sm font-medium text-surface-0 hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? t('login.submitting') : t('login.submit')}
          </button>
        </form>
      </div>
    </div>
  )
}
