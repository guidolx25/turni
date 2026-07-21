/**
 * Settings (§7 `PATCH /me/settings`, §9): language, email notifications,
 * password, and the §6 (v1.7) personal ICS feed.
 *
 * Every write re-reads /me instead of trusting the response body, so what the
 * page shows is what the server stored.
 */
import { useState, type ReactNode, type SyntheticEvent } from 'react'

import { errorKey as toErrorKey } from '../api/client'
import { meApi } from '../api/endpoints'
import type { Language } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { ErrorNote, LoadingIndicator } from '../components/common'
import type { TranslationKey } from '../i18n'
import { useLanguage, useT } from '../i18n'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border border-line bg-surface-1 p-4">
      <h2 className="text-sm font-medium text-ink-1">{title}</h2>
      {children}
    </section>
  )
}

function Help({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-relaxed text-ink-2">{children}</p>
}

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-ink-1 outline-none focus:border-ink-3'

function LanguageSection() {
  const t = useT()
  const { language, setLanguage } = useLanguage()
  const options: { value: Language; labelKey: TranslationKey }[] = [
    { value: 'it', labelKey: 'language.it' },
    { value: 'en', labelKey: 'language.en' },
  ]
  return (
    <Section title={t('settings.language.title')}>
      <select
        aria-label={t('settings.language.title')}
        value={language}
        onChange={(event) => {
          // §9: writes localStorage AND PATCH /me/settings (see i18n/index).
          setLanguage(event.target.value === 'en' ? 'en' : 'it')
        }}
        className={FIELD_CLASS}
      >
        {options.map(({ value, labelKey }) => (
          <option key={value} value={value}>
            {t(labelKey)}
          </option>
        ))}
      </select>
      <Help>{t('settings.language.help')}</Help>
    </Section>
  )
}

function AccountSection() {
  const t = useT()
  const { user, refreshUser } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)

  if (!user) return null

  const toggleEmails = (enabled: boolean) => {
    setBusy(true)
    setError(null)
    meApi
      .updateSettings({ email_notifications: enabled })
      .then(refreshUser)
      .catch((err: unknown) => {
        setError(toErrorKey(err))
      })
      .finally(() => {
        setBusy(false)
      })
  }

  return (
    <Section title={t('settings.account.title')}>
      <div className="space-y-1">
        <p className="text-[10px] tracking-wide uppercase text-ink-3">
          {t('settings.account.email')}
        </p>
        <p className="text-sm text-ink-1">{user.email ?? t('settings.account.noEmail')}</p>
        {/* §7 lists language / email_notifications / password on PATCH
            /me/settings — the address itself is not a self-service field. */}
        <Help>{t('settings.account.emailManaged')}</Help>
      </div>

      <label className="flex items-center justify-between gap-3 rounded-md border border-line bg-surface-2 px-3 py-2.5">
        <span className="text-sm text-ink-1">{t('settings.account.notifications')}</span>
        <input
          type="checkbox"
          disabled={busy}
          checked={user.email_notifications}
          onChange={(event) => {
            toggleEmails(event.target.checked)
          }}
          className="h-4 w-4 accent-bagnino"
        />
      </label>
      <Help>{t('settings.account.notificationsHelp')}</Help>
      {error ? <ErrorNote errorKey={error} /> : null}
    </Section>
  )
}

function PasswordSection() {
  const t = useT()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)
  const [done, setDone] = useState(false)

  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault()
    setDone(false)
    if (next !== confirm) {
      setError('settings.password.mismatch')
      return
    }
    setBusy(true)
    setError(null)
    meApi
      .updateSettings({ current_password: current, new_password: next })
      .then(() => {
        setDone(true)
        setCurrent('')
        setNext('')
        setConfirm('')
      })
      .catch((err: unknown) => {
        // The server's §7 codes surface through `errors.<code>`.
        setError(toErrorKey(err))
      })
      .finally(() => {
        setBusy(false)
      })
  }

  const fields: { labelKey: TranslationKey; value: string; onChange: (v: string) => void }[] = [
    { labelKey: 'settings.password.current', value: current, onChange: setCurrent },
    { labelKey: 'settings.password.new', value: next, onChange: setNext },
    { labelKey: 'settings.password.confirm', value: confirm, onChange: setConfirm },
  ]

  return (
    <Section title={t('settings.password.title')}>
      <form className="space-y-3" onSubmit={submit}>
        {fields.map(({ labelKey, value, onChange }) => (
          <label key={labelKey} className="block space-y-1">
            <span className="text-xs text-ink-2">{t(labelKey)}</span>
            <input
              type="password"
              autoComplete={
                labelKey === 'settings.password.current' ? 'current-password' : 'new-password'
              }
              value={value}
              onChange={(event) => {
                onChange(event.target.value)
              }}
              className={FIELD_CLASS}
            />
          </label>
        ))}

        {error ? <ErrorNote errorKey={error} /> : null}
        {done ? (
          <p role="status" className="text-xs text-ok">
            {t('settings.password.success')}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={busy || current === '' || next === ''}
          className="rounded-md bg-ink-1 px-3 py-1.5 text-xs font-medium text-surface-0 hover:opacity-90 disabled:opacity-40"
        >
          {busy ? t('common.saving') : t('settings.password.submit')}
        </button>
      </form>
    </Section>
  )
}

function IcsSection() {
  const t = useT()
  const { user, refreshUser } = useAuth()
  const [copied, setCopied] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)
  const [regenerated, setRegenerated] = useState(false)

  if (!user) return null

  const url = `${window.location.origin}/export/ics?token=${encodeURIComponent(user.ics_token)}`

  const copy = () => {
    void navigator.clipboard
      .writeText(url)
      .then(() => {
        setCopied(true)
      })
      .catch(() => {
        // Clipboard denied (insecure context / permissions): the field is
        // selectable, so the URL stays reachable by hand.
        setCopied(false)
      })
  }

  const regenerate = () => {
    setBusy(true)
    setError(null)
    meApi
      .regenerateIcsToken()
      .then(refreshUser)
      .then(() => {
        setRegenerated(true)
        setConfirming(false)
        setCopied(false)
      })
      .catch((err: unknown) => {
        setError(toErrorKey(err))
      })
      .finally(() => {
        setBusy(false)
      })
  }

  return (
    <Section title={t('settings.ics.title')}>
      <Help>{t('settings.ics.help')}</Help>

      <div className="space-y-2">
        <label className="block space-y-1">
          <span className="text-xs text-ink-2">{t('settings.ics.url')}</span>
          <input
            readOnly
            value={url}
            onFocus={(event) => {
              event.target.select()
            }}
            className={FIELD_CLASS}
          />
        </label>
        <button
          type="button"
          onClick={copy}
          className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 hover:border-ink-3 hover:text-ink-1"
        >
          {copied ? t('common.copied') : t('common.copy')}
        </button>
      </div>

      <div className="space-y-2 rounded-md border border-danger-dim bg-danger-dim/15 px-3 py-2.5">
        <p className="text-xs leading-relaxed text-ink-2">{t('settings.ics.regenerateWarning')}</p>
        {confirming ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-danger">{t('settings.ics.regenerateConfirm')}</span>
            <button
              type="button"
              disabled={busy}
              onClick={regenerate}
              className="rounded-md bg-danger-dim px-2.5 py-1 text-xs font-medium text-danger hover:opacity-90 disabled:opacity-50"
            >
              {busy ? t('common.saving') : t('settings.ics.regenerate')}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setConfirming(false)
              }}
              className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 hover:text-ink-1"
            >
              {t('common.cancel')}
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => {
              setConfirming(true)
              setRegenerated(false)
            }}
            className="rounded-md border border-danger/40 px-2.5 py-1 text-xs text-danger hover:bg-danger-dim/40"
          >
            {t('settings.ics.regenerate')}
          </button>
        )}
        {error ? <ErrorNote errorKey={error} /> : null}
        {regenerated ? (
          <p role="status" className="text-xs text-ok">
            {t('settings.ics.regenerated')}
          </p>
        ) : null}
      </div>
    </Section>
  )
}

export function SettingsView() {
  const t = useT()
  const { user, initializing } = useAuth()

  if (initializing || !user) return <LoadingIndicator />

  return (
    <section className="space-y-4">
      <h1 className="text-lg font-medium">{t('settings.title')}</h1>
      <LanguageSection />
      <AccountSection />
      <PasswordSection />
      <IcsSection />
    </section>
  )
}
