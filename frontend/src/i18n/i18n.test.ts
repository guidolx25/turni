/**
 * §9 gate guard: it.ts and en.ts must mirror keys 1:1. The `satisfies` clause
 * enforces this at compile time; this runtime test is the belt to that brace
 * (and what a plain `vitest run` reports if someone bypasses tsc).
 */
import { expect, test } from 'vitest'

import { en } from './en'
import { it as itDict } from './it'

test('it.ts and en.ts expose identical key sets', () => {
  const itKeys = Object.keys(itDict).sort()
  const enKeys = Object.keys(en).sort()
  expect(enKeys).toEqual(itKeys)
})

test('every key has a non-empty translation in both languages', () => {
  for (const [key, value] of [...Object.entries(itDict), ...Object.entries(en)]) {
    expect(value.trim(), key).not.toBe('')
  }
})

test('placeholders match between languages', () => {
  const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
  for (const key of Object.keys(itDict) as (keyof typeof itDict)[]) {
    expect(placeholders(en[key]), key).toEqual(placeholders(itDict[key]))
  }
})

test('the document language follows the active language (§9)', async () => {
  // index.html ships a static `lang`; a bilingual app that always claims one
  // language mis-cues screen readers and browser translation. This closes the
  // Phase 0 carry-forward, so it needs a test that fails if it is undone.
  const { LanguageProvider, useLanguage } = await import('./index')
  const { renderHook, act } = await import('@testing-library/react')

  const { result } = renderHook(() => useLanguage(), { wrapper: LanguageProvider })

  act(() => {
    result.current.setLanguage('en', { sync: false })
  })
  expect(document.documentElement.lang).toBe('en')

  act(() => {
    result.current.setLanguage('it', { sync: false })
  })
  expect(document.documentElement.lang).toBe('it')
})
