/**
 * Root panel — user management (§9 "Root panel (users)", §5 row 7).
 *
 * Gated on `capabilities.manage_users` from /me, like every other panel: §7 puts
 * the §5 matrix on /me as derived booleans so there is one source of truth.
 *
 * **Root invisibility (§5).** Nothing here reintroduces what the API withholds.
 * `is_root` is serialized nowhere, so there is no "is root" badge to render and
 * no username to special-case; root sees its own row because
 * `GET /root/users` returns it *to root*, and for no other reason. A UI that
 * inferred root-ness from a hardcoded name would recreate the disclosure the
 * backend spent a chokepoint preventing.
 *
 * **Deactivate, never delete (§5).** Assignments, swaps and audit rows reference
 * users; deleting one would destroy history or leave the audit log lying about
 * who acted. So the only removal offered is `PATCH {active: false}` — and the
 * copy says why, and says that it takes effect immediately, revoking sessions
 * already open rather than merely the next sign-in.
 */
import { useState, type SyntheticEvent } from 'react'

import { errorKey as toErrorKey } from '../api/client'
import { rootApi } from '../api/endpoints'
import type { Language, UserAdminOut, UserRole } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { canManageUsers } from '../auth/capabilities'
import {
  BUTTON_PRIMARY,
  ConfirmAction,
  ErrorNote,
  FIELD_CLASS,
  FieldLabel,
  Help,
  LoadingIndicator,
  Panel,
  SuccessNote,
} from '../components/common'
import { useRootUsers } from '../hooks/useResource'
import type { TranslationKey } from '../i18n'
import { useT } from '../i18n'

const ROLES: readonly UserRole[] = ['bagnino', 'spiaggino', 'jolly']
const LANGUAGES: readonly Language[] = ['it', 'en']

function isRole(value: string): value is UserRole {
  return ROLES.some((role) => role === value)
}

function isLanguage(value: string): value is Language {
  return LANGUAGES.some((language) => language === value)
}

function RoleSelect({
  label,
  value,
  onChange,
}: {
  label: string
  value: UserRole
  onChange: (role: UserRole) => void
}) {
  const t = useT()
  return (
    <label className="block space-y-1">
      <FieldLabel>{label}</FieldLabel>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => {
          if (isRole(event.target.value)) onChange(event.target.value)
        }}
        className={FIELD_CLASS}
      >
        {ROLES.map((role) => (
          <option key={role} value={role}>
            {t(`role.${role}`)}
          </option>
        ))}
      </select>
    </label>
  )
}

function LanguageSelect({
  label,
  value,
  onChange,
}: {
  label: string
  value: Language
  onChange: (language: Language) => void
}) {
  const t = useT()
  return (
    <label className="block space-y-1">
      <FieldLabel>{label}</FieldLabel>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => {
          if (isLanguage(event.target.value)) onChange(event.target.value)
        }}
        className={FIELD_CLASS}
      >
        {LANGUAGES.map((language) => (
          <option key={language} value={language}>
            {t(`language.${language}`)}
          </option>
        ))}
      </select>
    </label>
  )
}

function TextField({
  label,
  value,
  type = 'text',
  onChange,
}: {
  label: string
  value: string
  type?: 'text' | 'password'
  onChange: (value: string) => void
}) {
  return (
    <label className="block space-y-1">
      <FieldLabel>{label}</FieldLabel>
      <input
        type={type}
        value={value}
        autoComplete="off"
        onChange={(event) => {
          onChange(event.target.value)
        }}
        className={FIELD_CLASS}
      />
    </label>
  )
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-md border border-line bg-surface-2 px-3 py-2.5">
      <span className="text-xs text-ink-1">{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => {
          onChange(event.target.checked)
        }}
        className="h-4 w-4 accent-bagnino"
      />
    </label>
  )
}

function UserRow({ user, onChanged }: { user: UserAdminOut; onChanged: () => void }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [displayName, setDisplayName] = useState(user.display_name)
  const [role, setRole] = useState<UserRole>(user.role)
  const [email, setEmail] = useState(user.email ?? '')
  const [isAdmin, setIsAdmin] = useState(user.is_admin)
  const [language, setLanguage] = useState<Language>(user.language)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)
  const [done, setDone] = useState<TranslationKey | null>(null)

  const run = (action: Promise<unknown>, success: TranslationKey) => {
    setBusy(true)
    setError(null)
    setDone(null)
    return action
      .then(() => {
        setDone(success)
      })
      .catch((err: unknown) => {
        setError(toErrorKey(err))
      })
      .finally(() => {
        setBusy(false)
        onChanged()
      })
  }

  const save = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault()
    void run(
      rootApi.update(user.id, {
        display_name: displayName,
        role,
        email: email === '' ? null : email,
        is_admin: isAdmin,
        language,
      }),
      'root.edit.done',
    )
  }

  const setActive = (active: boolean) =>
    run(
      rootApi.update(user.id, { active }),
      active ? 'root.reactivate.done' : 'root.deactivate.done',
    ).then(() => undefined)

  const resetPassword = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault()
    void run(rootApi.resetPassword(user.id, { new_password: password }), 'root.password.done').then(
      () => {
        setPassword('')
      },
    )
  }

  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        aria-label={
          open
            ? t('root.edit.close', { name: user.display_name })
            : t('root.edit.open', { name: user.display_name })
        }
        onClick={() => {
          setOpen((value) => !value)
        }}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2/60"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-ink-1">{user.display_name}</span>
          <span className="block truncate text-[11px] text-ink-3">{user.username}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {user.is_admin ? (
            <span className="rounded border border-bagnino-dim bg-bagnino-dim/40 px-1.5 py-0.5 text-[10px] text-bagnino">
              {t('root.badge.admin')}
            </span>
          ) : null}
          <span className="text-[10px] text-ink-3">{t(`role.${user.role}`)}</span>
          <span
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              user.active ? 'border-ok-dim text-ok' : 'border-line text-ink-3'
            }`}
          >
            {user.active ? t('root.status.active') : t('root.status.inactive')}
          </span>
        </span>
      </button>

      {open ? (
        <div className="space-y-4 border-t border-line bg-surface-2/40 px-3 py-3">
          <form className="space-y-3" onSubmit={save}>
            <FieldLabel>{t('root.edit.title')}</FieldLabel>
            <TextField
              label={t('root.field.displayName')}
              value={displayName}
              onChange={setDisplayName}
            />
            <RoleSelect label={t('root.field.role')} value={role} onChange={setRole} />
            <TextField label={t('root.field.email')} value={email} onChange={setEmail} />
            <LanguageSelect
              label={t('root.field.language')}
              value={language}
              onChange={setLanguage}
            />
            <Checkbox label={t('root.field.admin')} checked={isAdmin} onChange={setIsAdmin} />
            <button type="submit" disabled={busy} className={BUTTON_PRIMARY}>
              {busy ? t('common.saving') : t('common.save')}
            </button>
          </form>

          <form className="space-y-3" onSubmit={resetPassword}>
            <FieldLabel>{t('root.password.title')}</FieldLabel>
            <Help>{t('root.password.help')}</Help>
            <TextField
              label={t('root.password.new')}
              type="password"
              value={password}
              onChange={setPassword}
            />
            <button type="submit" disabled={busy || password === ''} className={BUTTON_PRIMARY}>
              {busy ? t('root.password.working') : t('root.password.submit')}
            </button>
          </form>

          <div className="space-y-2">
            <FieldLabel>{t('root.deactivate.title')}</FieldLabel>
            {/* §5: never a delete. The reason is part of the interface. */}
            <Help>{t('root.deactivate.why')}</Help>
            <Help>{t('root.deactivate.immediate')}</Help>
            {user.active ? (
              <ConfirmAction
                tone="danger"
                label={t('root.deactivate.submit')}
                confirmLabel={t('root.deactivate.confirmAction')}
                consequence={t('root.deactivate.immediate')}
                busyLabel={t('root.deactivate.working')}
                onConfirm={() => setActive(false)}
              />
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  void setActive(true)
                }}
                className={BUTTON_PRIMARY}
              >
                {t('root.reactivate.submit')}
              </button>
            )}
          </div>

          {error ? <ErrorNote errorKey={error} /> : null}
          {done ? <SuccessNote>{t(done)}</SuccessNote> : null}
        </div>
      ) : null}
    </li>
  )
}

function CreateUserPanel({ onCreated }: { onCreated: () => void }) {
  const t = useT()
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<UserRole>('bagnino')
  const [email, setEmail] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)
  const [language, setLanguage] = useState<Language>('it')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)
  const [done, setDone] = useState(false)

  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setDone(false)
    rootApi
      .create({
        username,
        display_name: displayName,
        role,
        email: email === '' ? null : email,
        is_admin: isAdmin,
        language,
        password,
      })
      .then(() => {
        setDone(true)
        setUsername('')
        setDisplayName('')
        setEmail('')
        setIsAdmin(false)
        setPassword('')
        onCreated()
      })
      .catch((err: unknown) => {
        setError(toErrorKey(err))
      })
      .finally(() => {
        setBusy(false)
      })
  }

  return (
    <Panel title={t('root.create.title')}>
      <form className="space-y-3" onSubmit={submit}>
        <TextField label={t('root.field.username')} value={username} onChange={setUsername} />
        <TextField
          label={t('root.field.displayName')}
          value={displayName}
          onChange={setDisplayName}
        />
        <RoleSelect label={t('root.field.role')} value={role} onChange={setRole} />
        <TextField label={t('root.field.email')} value={email} onChange={setEmail} />
        <LanguageSelect label={t('root.field.language')} value={language} onChange={setLanguage} />
        <Checkbox label={t('root.field.admin')} checked={isAdmin} onChange={setIsAdmin} />
        <TextField
          label={t('root.field.password')}
          type="password"
          value={password}
          onChange={setPassword}
        />
        {error ? <ErrorNote errorKey={error} /> : null}
        {done ? <SuccessNote>{t('root.create.done')}</SuccessNote> : null}
        <button
          type="submit"
          disabled={busy || username === '' || displayName === '' || password === ''}
          className={BUTTON_PRIMARY}
        >
          {busy ? t('root.create.working') : t('root.create.submit')}
        </button>
      </form>
    </Panel>
  )
}

export function RootView() {
  const t = useT()
  const { user } = useAuth()
  const users = useRootUsers(canManageUsers(user?.capabilities))

  return (
    <section className="space-y-4">
      <h1 className="text-lg font-medium">{t('root.title')}</h1>
      <Help>{t('root.intro')}</Help>

      {users.loading ? <LoadingIndicator /> : null}
      {users.errorKey ? <ErrorNote errorKey={users.errorKey} onRetry={users.reload} /> : null}
      {users.data && users.data.length === 0 ? <Help>{t('root.empty')}</Help> : null}

      {users.data && users.data.length > 0 ? (
        <ul className="overflow-hidden rounded-lg border border-line bg-surface-1">
          {users.data.map((row) => (
            <UserRow key={row.id} user={row} onChanged={users.reload} />
          ))}
        </ul>
      ) : null}

      <CreateUserPanel onCreated={users.reload} />
    </section>
  )
}
