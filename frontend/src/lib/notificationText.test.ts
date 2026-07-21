/**
 * §10 payloads → §9 dictionary lines. These assert the load-bearing property:
 * a notification is stored as DATA and rendered in the *reader's* language, and
 * a payload this build does not understand degrades to a sentence rather than
 * crashing or printing JSON.
 */
import { describe, expect, test } from 'vitest'

import type { NotificationOut } from '../api/types'
import { en } from '../i18n/en'
import { it as itDict } from '../i18n/it'
import type { Language, TranslationKey, Translate } from '../i18n'
import { pendingProposalRef, renderNotification } from './notificationText'

const WEEK = '2026-07-13' // a Monday

function translator(language: Language): Translate {
  const dict: Record<TranslationKey, string> = language === 'it' ? itDict : en
  return (key, params) => {
    let text = dict[key]
    for (const [name, value] of Object.entries(params ?? {})) {
      text = text.replaceAll(`{${name}}`, String(value))
    }
    return text
  }
}

function notification(
  event_type: string,
  payload: Record<string, unknown> | null,
): NotificationOut {
  return { id: 1, event_type, payload, read: false, created_at: '2026-07-10T09:00:00Z' }
}

function render(n: NotificationOut, language: Language = 'en', viewerId: number | null = 7) {
  return renderNotification(n, translator(language), language, viewerId)
}

describe('renderNotification', () => {
  test('schedule_published names the week', () => {
    const { line } = render(notification('schedule_published', { week: WEEK }))
    expect(line).toContain('Schedule published')
    expect(line).toMatch(/2026/)
  })

  test('the same payload renders in the reader’s language', () => {
    const payload = { week: WEEK }
    expect(render(notification('schedule_published', payload), 'en').line).toContain(
      'Schedule published',
    )
    expect(render(notification('schedule_published', payload), 'it').line).toContain(
      'Turni pubblicati',
    )
  })

  test('swap_requested renders both assignment tuples, weekday via Intl', () => {
    const { line } = render(
      notification('swap_requested', {
        swap_id: 3,
        week: WEEK,
        from_user: 7,
        to_user: 8,
        from_assignment: { id: 1, day: 'mon', slot: 'am', role: 'bagnino' },
        to_assignment: { id: 2, day: 'wed', slot: 'pm', role: 'bagnino' },
        status: 'pending',
      }),
    )
    expect(line).toContain('swap request')
    expect(line).toContain('Mon')
    expect(line).toContain('Morning')
    expect(line).toContain('Wed')
    expect(line).toContain('Afternoon')
    expect(line).toContain('Lifeguard')
  })

  test('sacrifice_proposed names the offered free day', () => {
    const { line } = render(
      notification('sacrifice_proposed', {
        proposal_id: 4,
        week: WEEK,
        proposed_free_day: 'fri',
      }),
    )
    expect(line).toContain('Fri')
    expect(line).toContain('free day')
  })

  test('sacrifice_resolved reports the settled free day', () => {
    const { line } = render(
      notification('sacrifice_resolved', { week: WEEK, outcome: 'accepted', free_day: 'fri' }),
    )
    expect(line).toContain('Fri')
    expect(line).toContain('published')
  })

  test('sacrifice_escalated localizes the unsat core, never raw JSON', () => {
    const { line, conflict } = render(
      notification('sacrifice_escalated', {
        week: WEEK,
        outcome: 'declined',
        conflict: [
          { worker_id: 7, day: 'fri', slot: 'am' },
          { worker_id: 9, day: 'fri', slot: 'full_day' },
        ],
      }),
    )
    expect(line).toContain('Unresolved conflict')
    expect(conflict).toHaveLength(2)
    // The viewer is worker 7: their own request is named as theirs.
    expect(conflict[0]).toContain('Your request')
    expect(conflict[0]).toContain('Morning')
    expect(conflict[1]).toContain('colleague')
    expect(conflict[1]).toContain('All day')
    expect(conflict.join(' ')).not.toContain('worker_id')
  })

  test('weekend_hard_escalated explains the H5 template case with the name', () => {
    const { line } = render(
      notification('weekend_hard_escalated', {
        week: WEEK,
        constraint_id: 12,
        user_id: 9,
        display_name: 'Pasha',
        day: 'sat',
        slot: 'full_day',
        reason: 'weekend_template_fixed',
      }),
    )
    expect(line).toContain('Pasha')
    expect(line).toContain('Sat')
    expect(line).toContain('All day')
    expect(line).toContain('fixed template')
  })

  test('window_closing_24h and admin_override render from the week alone', () => {
    expect(render(notification('window_closing_24h', { week: WEEK })).line).toContain('24 hours')
    expect(render(notification('admin_override', { week: WEEK })).line).toContain('admin')
  })

  test('an unknown event type degrades to the generic line', () => {
    const { line, conflict } = render(
      notification('some_future_event_v2', { anything: { nested: [1, 2, 3] } }),
    )
    expect(line).toBe(en['notif.unknown'])
    expect(conflict).toEqual([])
  })

  test('a null payload degrades instead of throwing', () => {
    expect(render(notification('schedule_published', null)).line).toBe(en['notif.unknown'])
  })

  test('a malformed payload (missing/!typed fields) degrades', () => {
    expect(render(notification('schedule_published', { week: 42 })).line).toBe(en['notif.unknown'])
    expect(
      render(notification('sacrifice_proposed', { week: WEEK, proposed_free_day: 'funday' })).line,
    ).toBe(en['notif.unknown'])
    expect(
      render(notification('swap_requested', { week: WEEK, from_assignment: 'nope' })).line,
    ).toBe(en['notif.unknown'])
  })

  test('malformed conflict entries are dropped, not rendered', () => {
    const { conflict } = render(
      notification('sacrifice_escalated', {
        week: WEEK,
        outcome: 'escalated',
        conflict: [{ worker_id: 7, day: 'fri', slot: 'am' }, { bogus: true }, null, 'nope'],
      }),
    )
    expect(conflict).toHaveLength(1)
  })
})

describe('pendingProposalRef', () => {
  test('extracts the proposal id from a sacrifice_proposed payload', () => {
    expect(
      pendingProposalRef(
        notification('sacrifice_proposed', {
          proposal_id: 11,
          week: WEEK,
          proposed_free_day: 'fri',
        }),
      ),
    ).toEqual({ proposalId: 11, week: WEEK, proposedFreeDay: 'fri' })
  })

  test('ignores other events and incomplete payloads', () => {
    expect(pendingProposalRef(notification('schedule_published', { week: WEEK }))).toBeNull()
    expect(pendingProposalRef(notification('sacrifice_proposed', { week: WEEK }))).toBeNull()
  })
})
