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
