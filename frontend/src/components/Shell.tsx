/**
 * App shell (§9): header with app name, nav, language toggle, notification bell,
 * user + logout. Mobile-first — bottom tab bar on small screens, inline top nav
 * from `sm:`.
 *
 * Everything authenticated renders inside <NotificationsProvider>, so the §10
 * 60 s poll starts with the session and stops with it, and the §2.3 blocking
 * prompt can sit above every route.
 */
import { NavLink, Outlet } from 'react-router-dom'
import { useEffect } from 'react'

import { useAuth } from '../auth/AuthContext'
import type { Language, TranslationKey } from '../i18n'
import { useLanguage, useT } from '../i18n'
import { NotificationsProvider, useNotifications } from '../notifications/NotificationsContext'
import {
  BellIcon,
  CalendarIcon,
  GearIcon,
  ShieldIcon,
  SlidersIcon,
  SwapIcon,
  UsersIcon,
} from './icons'
import { SacrificePrompt } from './SacrificePrompt'
import { canManageUsers, hasAdminPanelAccess } from '../auth/capabilities'

interface NavItem {
  labelKey: TranslationKey
  path: string
  icon: typeof CalendarIcon
}

const NAV_ITEMS: NavItem[] = [
  { labelKey: 'nav.schedule', path: '/', icon: CalendarIcon },
  { labelKey: 'nav.swaps', path: '/swaps', icon: SwapIcon },
  { labelKey: 'nav.constraints', path: '/constraints', icon: SlidersIcon },
  { labelKey: 'nav.notifications', path: '/notifications', icon: BellIcon },
  { labelKey: 'nav.settings', path: '/settings', icon: GearIcon },
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

/** Header bell + unread badge (§10 Channel 1). */
function NotificationBell() {
  const t = useT()
  const { unreadCount } = useNotifications()
  return (
    <NavLink
      to="/notifications"
      aria-label={t('notifications.bell', { count: unreadCount })}
      className={({ isActive }) =>
        `relative rounded-md p-1.5 ${isActive ? 'text-ink-1' : 'text-ink-2 hover:text-ink-1'}`
      }
    >
      <BellIcon className="h-4.5 w-4.5" />
      {unreadCount > 0 ? (
        <span className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-spiaggino px-1 text-[10px] leading-4 font-medium text-surface-0">
          {unreadCount}
        </span>
      ) : null}
    </NavLink>
  )
}

/**
 * The §5 admin/root panels, as icon links in the header (§9).
 *
 * Deliberately NOT extra entries in the bottom tab bar: that bar is the daily
 * navigation for five worker views and a seventh tab does not fit a phone
 * without shrinking all of them. The panels are tools two of six people reach
 * occasionally, so they sit in the header at every breakpoint instead — present
 * on mobile, never crowding the primary nav.
 *
 * Gated on the caller's own §5 capabilities: a plain worker renders neither, and
 * the route guard refuses the URL as well.
 */
function ToolLinks() {
  const t = useT()
  const { user } = useAuth()
  const capabilities = user?.capabilities
  const links: { path: string; labelKey: TranslationKey; icon: typeof ShieldIcon }[] = []
  if (hasAdminPanelAccess(capabilities)) {
    links.push({ path: '/admin', labelKey: 'nav.admin', icon: ShieldIcon })
  }
  if (canManageUsers(capabilities)) {
    links.push({ path: '/root', labelKey: 'nav.root', icon: UsersIcon })
  }
  if (links.length === 0) return null

  return (
    <>
      {links.map(({ path, labelKey, icon: Icon }) => (
        <NavLink
          key={path}
          to={path}
          aria-label={t(labelKey)}
          className={({ isActive }) =>
            `rounded-md p-1.5 ${isActive ? 'text-ink-1' : 'text-ink-2 hover:text-ink-1'}`
          }
        >
          <Icon className="h-4.5 w-4.5" />
        </NavLink>
      ))}
    </>
  )
}

function navLinkClass(isActive: boolean): string {
  return isActive ? 'text-ink-1 font-medium' : 'text-ink-2 hover:text-ink-1 transition-colors'
}

/**
 * §9: the language is persisted to localStorage *and* `users.language`. On first
 * load of a session with no local choice yet, the server's stored value is the
 * one the user last expressed (possibly on another device), so adopt it —
 * without echoing it straight back (`sync: false`).
 */
function useAdoptAccountLanguage() {
  const { user } = useAuth()
  const { hasStoredPreference, setLanguage } = useLanguage()
  const accountLanguage = user?.language

  useEffect(() => {
    if (!accountLanguage || hasStoredPreference) return
    setLanguage(accountLanguage, { sync: false })
  }, [accountLanguage, hasStoredPreference, setLanguage])
}

function ShellFrame() {
  const t = useT()
  const { user, logout } = useAuth()
  const { pendingProposal } = useNotifications()
  useAdoptAccountLanguage()

  return (
    <div className="min-h-screen bg-surface-0">
      <header className="sticky top-0 z-10 border-b border-line bg-surface-1/95 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-3xl items-center gap-5 px-4">
          <span className="text-sm font-semibold tracking-[0.2em] uppercase">{t('app.name')}</span>
          <nav className="hidden items-center gap-4 text-sm sm:flex">
            {NAV_ITEMS.map(({ labelKey, path }) => (
              <NavLink
                key={labelKey}
                to={path}
                end={path === '/'}
                className={({ isActive }) => navLinkClass(isActive)}
              >
                {t(labelKey)}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <ToolLinks />
            <NotificationBell />
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
          {NAV_ITEMS.map(({ labelKey, path, icon: Icon }) => (
            <NavLink
              key={labelKey}
              to={path}
              end={path === '/'}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 px-2.5 py-2 text-[11px] ${navLinkClass(isActive)}`
              }
            >
              <Icon className="h-4 w-4" />
              {t(labelKey)}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* §2.3: unmissable and undismissable, above every route. */}
      {pendingProposal ? <SacrificePrompt proposal={pendingProposal} /> : null}
    </div>
  )
}

export function Shell() {
  return (
    <NotificationsProvider>
      <ShellFrame />
    </NotificationsProvider>
  )
}
