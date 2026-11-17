import { expect, test, vi } from 'vitest'
import { DEMO_MINUTES } from '../copy.ts'
import { createDemoBackend } from './backend.ts'
import type { Recording } from './backend.ts'
import { PACE } from './pace.ts'
import recording from './recording.json'

test("the minutes the demo's link promises are the recording's replay length", async () => {
  vi.useFakeTimers()
  try {
    const started = Date.now()
    const backend = createDemoBackend(recording as Recording, PACE, () => () => {})
    await vi.runAllTimersAsync()
    await backend.finished
    expect(Math.round((Date.now() - started) / 60_000)).toBe(DEMO_MINUTES)
  } finally {
    vi.useRealTimers()
  }
})
