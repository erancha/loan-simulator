import { expect, test, vi } from 'vitest'
import { DEMO_SECONDS } from '../copy.ts'
import { createDemoBackend } from './backend.ts'
import type { Recording } from './backend.ts'
import { PACE, START_RATE } from './pace.ts'
import recording from './recording.json'

test("the seconds the demo's link promises are its length at its first speed", async () => {
  vi.useFakeTimers()
  try {
    const started = Date.now()
    const backend = createDemoBackend(recording as Recording, PACE, () => () => {})
    backend.clock.setRate(START_RATE)
    await vi.runAllTimersAsync()
    await backend.finished
    // To the nearest ten seconds, so a small change to the recording keeps the link's promise.
    expect(Math.round((Date.now() - started) / 10_000) * 10).toBe(DEMO_SECONDS)
  } finally {
    vi.useRealTimers()
  }
})
