/**
 * Date helpers (spec §9): weekday and date rendering always goes through
 * `Intl` with the active locale — never hand-written day names.
 */
import { DAY_ORDER, type Day } from '../api/types'
import type { Language } from '../i18n'

/** Parse `YYYY-MM-DD` as a local date (never `new Date(iso)` — that is UTC). */
export function parseIsoDate(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year ?? 1970, (month ?? 1) - 1, day ?? 1)
}

/** The calendar date of `day` within the week starting at `monday`. */
export function dateOfDay(monday: string, day: Day): Date {
  const date = parseIsoDate(monday)
  date.setDate(date.getDate() + DAY_ORDER.indexOf(day))
  return date
}

/** Short localized weekday, e.g. "lun" / "Mon". */
export function weekdayLabel(monday: string, day: Day, locale: Language): string {
  return new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(dateOfDay(monday, day))
}

/** Day-of-month for grid rows, localized. */
export function dayNumberLabel(monday: string, day: Day, locale: Language): string {
  return new Intl.DateTimeFormat(locale, { day: 'numeric' }).format(dateOfDay(monday, day))
}

/** Localized "13–19 Jul 2026" style label for a week picker entry. */
export function weekRangeLabel(monday: string, locale: Language): string {
  const start = parseIsoDate(monday)
  const end = new Date(start)
  end.setDate(end.getDate() + 6)
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).formatRange(start, end)
}

export interface Countdown {
  days: number
  hours: number
  minutes: number
}

/** Time left until an ISO instant, or null once passed. */
export function countdownTo(deadlineIso: string, now: Date): Countdown | null {
  const remaining = new Date(deadlineIso).getTime() - now.getTime()
  if (remaining <= 0) return null
  const minutesTotal = Math.floor(remaining / 60_000)
  return {
    days: Math.floor(minutesTotal / (24 * 60)),
    hours: Math.floor((minutesTotal % (24 * 60)) / 60),
    minutes: minutesTotal % 60,
  }
}

/** Localized relative age ("2 ore fa" / "2 hours ago") for swap timestamps. */
export function relativeAge(iso: string, now: Date, locale: Language): string {
  const diffMinutes = Math.round((new Date(iso).getTime() - now.getTime()) / 60_000)
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const abs = Math.abs(diffMinutes)
  if (abs < 60) return rtf.format(diffMinutes, 'minute')
  if (abs < 24 * 60) return rtf.format(Math.round(diffMinutes / 60), 'hour')
  return rtf.format(Math.round(diffMinutes / (24 * 60)), 'day')
}
