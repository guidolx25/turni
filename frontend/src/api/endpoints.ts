/** Typed endpoint functions for the §7 surface. */
import { request } from './client'
import type {
  ConstraintIn,
  ConstraintOut,
  IcsTokenOut,
  LoginIn,
  MarkReadIn,
  MeOut,
  MeSettingsIn,
  NotificationOut,
  SacrificeProposalOut,
  ScheduleOut,
  SwapCreateIn,
  SwapRequestOut,
  UserOut,
  WeekOut,
} from './types'

export const authApi = {
  // §7 `POST /auth/login` answers UserOut — no capabilities, no ics_token. The
  // session is what it establishes; AuthContext follows it with GET /me for the
  // full MeOut rather than pretending this response already is one.
  login: (body: LoginIn) =>
    request<UserOut>('/auth/login', {
      method: 'POST',
      body,
      skipUnauthorizedHandler: true,
    }),
  logout: () => request<unknown>('/auth/logout', { method: 'POST' }),
  me: () => request<MeOut>('/me', { skipUnauthorizedHandler: true }),
}

export const meApi = {
  /**
   * §7 `PATCH /me/settings` (language, email_notifications, password change).
   * Deliberately typed `unknown`: callers re-read /me instead of trusting this
   * body, so the view state cannot drift from the server's own view of the row.
   */
  updateSettings: (body: MeSettingsIn) =>
    request<unknown>('/me/settings', { method: 'PATCH', body }),
  /**
   * §6 (v1.7) regenerate the `/export/ics` credential. Per-user revocation:
   * every existing calendar subscription to the old token stops resolving.
   */
  regenerateIcsToken: () => request<IcsTokenOut>('/me/ics-token', { method: 'POST' }),
}

export const weeksApi = {
  list: () => request<WeekOut[]>('/weeks'),
}

export const scheduleApi = {
  get: (week: string) => request<ScheduleOut>(`/schedule?week=${encodeURIComponent(week)}`),
}

export const constraintsApi = {
  list: (week: string) => request<ConstraintOut[]>(`/constraints?week=${encodeURIComponent(week)}`),
  // §3.1: an upsert on (user, week, day, slot) — writing `full_day` replaces the
  // day's am/pm rows and vice versa, server-side. The view reloads after each
  // write rather than mirroring that rule twice.
  upsert: (body: ConstraintIn) => request<ConstraintOut>('/constraints', { method: 'POST', body }),
  remove: (id: number) => request<undefined>(`/constraints/${String(id)}`, { method: 'DELETE' }),
}

export const swapsApi = {
  list: (week: string) => request<SwapRequestOut[]>(`/swaps?week=${encodeURIComponent(week)}`),
  create: (body: SwapCreateIn) => request<SwapRequestOut>('/swaps', { method: 'POST', body }),
  accept: (id: number) =>
    request<SwapRequestOut>(`/swaps/${String(id)}/accept`, { method: 'POST' }),
  reject: (id: number) =>
    request<SwapRequestOut>(`/swaps/${String(id)}/reject`, { method: 'POST' }),
}

export const notificationsApi = {
  list: () => request<NotificationOut[]>('/notifications'),
  // §7: `ids` omitted marks all of the caller's rows read.
  markRead: (body: MarkReadIn = {}) =>
    request<undefined>('/notifications/read', { method: 'POST', body }),
}

export const sacrificeApi = {
  accept: (id: number) =>
    request<SacrificeProposalOut>(`/sacrifice/${String(id)}/accept`, { method: 'POST' }),
  decline: (id: number) =>
    request<SacrificeProposalOut>(`/sacrifice/${String(id)}/decline`, { method: 'POST' }),
}
