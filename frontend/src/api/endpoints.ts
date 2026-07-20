/** Typed endpoint functions for the §7 surface used in Phase 4. */
import { request } from './client'
import type { LoginIn, MeOut, ScheduleOut, SwapCreateIn, SwapRequestOut, WeekOut } from './types'

export const authApi = {
  login: (body: LoginIn) =>
    request<MeOut>('/auth/login', {
      method: 'POST',
      body,
      skipUnauthorizedHandler: true,
    }),
  logout: () => request<unknown>('/auth/logout', { method: 'POST' }),
  me: () => request<MeOut>('/me', { skipUnauthorizedHandler: true }),
}

export const weeksApi = {
  list: () => request<WeekOut[]>('/weeks'),
}

export const scheduleApi = {
  get: (week: string) => request<ScheduleOut>(`/schedule?week=${encodeURIComponent(week)}`),
}

export const swapsApi = {
  list: (week: string) => request<SwapRequestOut[]>(`/swaps?week=${encodeURIComponent(week)}`),
  create: (body: SwapCreateIn) => request<SwapRequestOut>('/swaps', { method: 'POST', body }),
  accept: (id: number) =>
    request<SwapRequestOut>(`/swaps/${String(id)}/accept`, { method: 'POST' }),
  reject: (id: number) =>
    request<SwapRequestOut>(`/swaps/${String(id)}/reject`, { method: 'POST' }),
}
