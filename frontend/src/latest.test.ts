import { expect, test } from 'vitest'
import { latestOnly } from './latest.ts'

test('an answer older than one already applied is refused', () => {
  const latest = latestOnly()
  const first = latest.begin()
  const second = latest.begin()
  expect(latest.accept(second)).toBe(true)
  expect(latest.accept(first)).toBe(false)
})

test('answers arriving in order are all accepted', () => {
  const latest = latestOnly()
  const first = latest.begin()
  const second = latest.begin()
  expect(latest.accept(first)).toBe(true)
  expect(latest.accept(second)).toBe(true)
})
