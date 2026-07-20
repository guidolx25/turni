/**
 * App shell (§9): header with app name, nav, language toggle, user + logout.
 * Mobile-first — bottom tab bar on small screens, inline top nav from `sm:`.
 * Constraints / Notifications / Settings are later-phase slots, rendered
 * disabled so the product shape is visible without dead routes.
 */
import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import type { Language, TranslationKey } from '../i18n'
import { useLanguage, useT } from '../i18n'
import { CalendarIcon, SwapIcon } from './icons'

interface NavItem {
  labelKey: TranslationKey
  path: string | null // null = later-phase placeholder, disabled
  icon: typeof CalendarIcon | null
}

const NAV_ITEMS: NavItem[] = [
  { labelKey: 'nav.schedule', path: '/', icon: CalendarIcon },
  { labelKey: 'nav.swaps', path: '/swaps', icon: SwapIcon },
  { labelKey: 'nav.constraints', path: null, icon: null },
  { labelKey: 'nav.notifications', path: null, icon: null },
  { labelKey: 'nav.settings', path: null, icon: null },
]

function LanguageToggle() {
  const t = useT()
  const { language, setLanguage } = useLanguage()
  const options: { value: Language; labelKey: TranslationKey }[] = [
    { value: 'it', labelKey: 'language.it' },
    { value: 'en', labelKey: 'language.en' },
  ]
  return (
    <div
      role="group"
      aria-label={t('language.toggleLabel')}
      className="flex overflow-hidden rounded-md border border-line text-xs"
    >
      {options.map(({ value, labelKey }) => (
        <button
          key={value}
          type="button"
          aria-pressed={language === value}
          onClick={() => {
            setLanguage(value)
          }}
          className={
            language === value
              ? 'bg-surface-2 px-2 py-1 font-medium text-ink-1'
              : 'px-2 py-1 text-ink-3 hover:text-ink-2'
          }
        >
          {t(labelKey)}
        </button>
      ))}
    </div>
  )
}

function navLinkClass(isActive: boolean): string {
  return isActive ? 'text-ink-1 font-medium' : 'text-ink-2 hover:text-ink-1 transition-colors'
}

export function Shell() {
  const t = useT()
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-surface-0">
      <header className="sticky top-0 z-10 border-b border-line bg-surface-1/95 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-3xl items-center gap-5 px-4">
          <span className="text-sm font-semibold tracking-[0.2em] uppercase">{t('app.name')}</span>
          <nav className="hidden items-center gap-4 text-sm sm:flex">
            {NAV_ITEMS.map(({ labelKey, path }) =>
              path ? (
                <NavLink
                  key={labelKey}
                  to={path}
                  end={path === '/'}
                  className={({ isActive }) => navLinkClass(isActive)}
                >
                  {t(labelKey)}
                </NavLink>
              ) : (
                <span
                  key={labelKey}
                  aria-disabled="true"
                  title={t('nav.soon')}
                  className="cursor-not-allowed text-ink-3"
                >
                  {t(labelKey)}
                </span>
              ),
            )}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <LanguageToggle />
            {user ? (
              <span
                className="hidden max-w-32 truncate text-sm text-ink-2 sm:inline"
                aria-label={t('shell.loggedInAs', { name: user.display_name })}
              >
                {user.display_name}
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => {
                void logout()
              }}
              className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 hover:border-ink-3 hover:text-ink-1"
            >
              {t('shell.logout')}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl px-4 pt-5 pb-24 sm:pb-10">
        <Outlet />
      </main>

      {/* Bottom tabs — the primary nav on phones (§9 mobile-first). */}
      <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-surface-1 sm:hidden">
        <div className="mx-auto flex max-w-3xl items-stretch justify-around">
          {NAV_ITEMS.map(({ labelKey, path, icon: Icon }) =>
            path ? (
              <NavLink
                key={labelKey}
                to={path}
                end={path === '/'}
                className={({ isActive }) =>
                  `flex flex-col items-center gap-0.5 px-3 py-2 text-[11px] ${navLinkClass(isActive)}`
                }
              >
                {Icon ? <Icon className="h-4 w-4" /> : null}
                {t(labelKey)}
              </NavLink>
            ) : (
              <span
                key={labelKey}
                aria-disabled="true"
                title={t('nav.soon')}
                className="flex cursor-not-allowed flex-col items-center justify-end px-3 py-2 text-[11px] text-ink-3"
              >
                {t(labelKey)}
              </span>
            ),
          )}
        </div>
      </nav>
    </div>
  )
}
