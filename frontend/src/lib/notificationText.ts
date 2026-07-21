/**
 * §10 notification payloads → localized lines (§9).
 *
 * Backend payloads are DATA, never prose: `sacrifice_proposals.conflict` is
 * `[{worker_id, day, slot}]`, a swap event carries `{day, slot, role}` tuples.
 * This module is the single place that turns those shapes into sentences, so a
 * notification written in one language is *read* in the reader's language —
 * that is the whole reason §6 stopped storing pre-formatted sentences (v1.5).
 *
 * Every field read goes through a validating accessor. A payload that is null,
 * truncated, or shaped unexpectedly, and any `event_type` this build has never
 * heard of, degrade to `notif.unknown` — never a crash, never raw JSON on
 * screen. New backend events are therefore forward-compatible by construction.
 */
import type { ConflictItem, Day, NotificationOut } from '../api/types'
import { DAY_ORDER } from '../api/types'
import type { Language, TranslationKey, Translate } from '../i18n'
import { weekRangeLabel, weekdayLabel } from './dates'

/** Slot values a payload may carry — the §6 constraint slots plus `full_day`. */
const SLOT_VALUES = ['am', 'pm', 'full_day'] as const
type PayloadSlot = (typeof SLOT_VALUES)[number]

const ROLE_VALUES = ['bagnino', 'spiaggino'] as const
type PayloadRole = (typeof ROLE_VALUES)[number]

type Payload = Record<string, unknown> | null

function str(payload: Payload, key: string): string | null {
  const value = payload?.[key]
  return typeof value === 'string' && value !== '' ? value : null
}

function num(payload: Payload, key: string): number | null {
  const value = payload?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function day(payload: Payload, key: string): Day | null {
  const value = payload?.[key]
  return DAY_ORDER.find((d) => d === value) ?? null
}

function slot(payload: Payload, key: string): PayloadSlot | null {
  const value = payload?.[key]
  return SLOT_VALUES.find((s) => s === value) ?? null
}

function role(payload: Payload, key: string): PayloadRole | null {
  const value = payload?.[key]
  return ROLE_VALUES.find((r) => r === value) ?? null
}

function nested(payload: Payload, key: string): Payload {
  const value = payload?.[key]
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null
}

/** A `{day, slot, role}` assignment tuple as "Mon Morning (Lifeguard)". */
function shiftLabel(
  tuple: Payload,
  monday: string,
  t: Translate,
  language: Language,
): string | null {
  const d = day(tuple, 'day')
  const s = slot(tuple, 'slot')
  const r = role(tuple, 'role')
  if (!d || !s || !r) return null
  return t('notif.shift', {
    day: weekdayLabel(monday, d, language),
    slot: t(`slot.${s}`),
    role: t(`role.${r}`),
  })
}

export interface RenderedNotification {
  /** The localized one-line summary. */
  line: string
  /** The §8 unsat core, localized — empty unless the event carries one. */
  conflict: string[]
}

/** The §6 conflict array, if this payload carries a well-formed one. */
function conflictItems(payload: Payload): ConflictItem[] {
  const raw = payload?.['conflict']
  if (!Array.isArray(raw)) return []
  const items: ConflictItem[] = []
  for (const entry of raw as unknown[]) {
    const item = typeof entry === 'object' && entry !== null ? (entry as Payload) : null
    const workerId = num(item, 'worker_id')
    const d = day(item, 'day')
    const s = slot(item, 'slot')
    if (workerId !== null && d && s) items.push({ worker_id: workerId, day: d, slot: s })
  }
  return items
}

/**
 * Localize the unsat core. `viewerId` decides whose request each line names:
 * the payload has ids and no names, and no §7 endpoint lets a worker resolve
 * another worker's id, so "yours" vs "a colleague's" is the honest distinction
 * available — never a bare id, never a name we cannot look up.
 */
function renderConflict(
  items: ConflictItem[],
  monday: string | null,
  viewerId: number | null,
  t: Translate,
  language: Language,
): string[] {
  if (!monday) return []
  return items.map((item) =>
    t('notif.conflict.item', {
      who: item.worker_id === viewerId ? t('notif.conflict.you') : t('notif.conflict.other'),
      day: weekdayLabel(monday, item.day, language),
      slot: t(`slot.${item.slot}`),
    }),
  )
}

const UNKNOWN: TranslationKey = 'notif.unknown'

export function renderNotification(
  notification: NotificationOut,
  t: Translate,
  language: Language,
  viewerId: number | null,
): RenderedNotification {
  const payload = notification.payload
  const monday = str(payload, 'week')
  const week = monday ? weekRangeLabel(monday, language) : null
  const generic = { line: t(UNKNOWN), conflict: [] }

  switch (notification.event_type) {
    case 'schedule_published':
    case 'window_closing_24h':
    case 'admin_override': {
      if (!week) return generic
      const key = `notif.${notification.event_type}` as const
      return { line: t(key, { week }), conflict: [] }
    }

    case 'swap_requested':
    case 'swap_accepted':
    case 'swap_rejected': {
      if (!monday || !week) return generic
      const from = shiftLabel(nested(payload, 'from_assignment'), monday, t, language)
      const to = shiftLabel(nested(payload, 'to_assignment'), monday, t, language)
      if (!from || !to) return generic
      const key = `notif.${notification.event_type}` as const
      return { line: t(key, { from, to, week }), conflict: [] }
    }

    case 'sacrifice_proposed': {
      const freeDay = day(payload, 'proposed_free_day')
      if (!monday || !week || !freeDay) return generic
      return {
        line: t('notif.sacrifice_proposed', {
          week,
          day: weekdayLabel(monday, freeDay, language),
        }),
        conflict: [],
      }
    }

    case 'sacrifice_resolved': {
      const freeDay = day(payload, 'free_day')
      if (!monday || !week || !freeDay) return generic
      return {
        line: t('notif.sacrifice_resolved', {
          week,
          day: weekdayLabel(monday, freeDay, language),
        }),
        conflict: [],
      }
    }

    case 'sacrifice_escalated': {
      if (!week) return generic
      return {
        line: t('notif.sacrifice_escalated', { week }),
        conflict: renderConflict(conflictItems(payload), monday, viewerId, t, language),
      }
    }

    case 'weekend_hard_escalated': {
      const name = str(payload, 'display_name')
      const d = day(payload, 'day')
      const s = slot(payload, 'slot')
      if (!monday || !name || !d || !s) return generic
      return {
        line: t('notif.weekend_hard_escalated', {
          name,
          day: weekdayLabel(monday, d, language),
          slot: t(`slot.${s}`),
        }),
        conflict: [],
      }
    }

    default:
      // A future §10 event this build predates: say *something* true.
      return generic
  }
}

/** The §2.3 proposal a `sacrifice_proposed` payload points at, if well-formed. */
export interface PendingProposalRef {
  proposalId: number
  week: string
  proposedFreeDay: Day
}

export function pendingProposalRef(notification: NotificationOut): PendingProposalRef | null {
  if (notification.event_type !== 'sacrifice_proposed') return null
  const payload = notification.payload
  const proposalId = num(payload, 'proposal_id')
  const week = str(payload, 'week')
  const proposedFreeDay = day(payload, 'proposed_free_day')
  if (proposalId === null || !week || !proposedFreeDay) return null
  return { proposalId, week, proposedFreeDay }
}
