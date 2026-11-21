import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { createDemoClock } from './clock.ts'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

/** Whether the promise has settled once the timers have run for ms. */
async function settledAfter(promise: Promise<void>, ms: number): Promise<boolean> {
  let settled = false
  void promise.then(() => {
    settled = true
  })
  await vi.advanceTimersByTimeAsync(ms)
  return settled
}

test('a wait ends after its demo time at 1×', async () => {
  const clock = createDemoClock()
  const wait = clock.wait(1000)

  expect(await settledAfter(wait, 999)).toBe(false)
  expect(await settledAfter(wait, 1)).toBe(true)
  expect(clock.elapsed()).toBe(1000)
})

test('at 2× a wait ends in half the time, and demo time runs twice as fast', async () => {
  const clock = createDemoClock()
  clock.setRate(2)
  const wait = clock.wait(1000)

  expect(await settledAfter(wait, 499)).toBe(false)
  expect(await settledAfter(wait, 1)).toBe(true)
  expect(clock.elapsed()).toBe(1000)
})

test('a rate change mid-wait applies to the time left', async () => {
  const clock = createDemoClock()
  const wait = clock.wait(1000)
  await vi.advanceTimersByTimeAsync(400)
  clock.setRate(2)

  expect(await settledAfter(wait, 299)).toBe(false)
  expect(await settledAfter(wait, 1)).toBe(true)
})

test('a pause holds a wait and demo time until resumed, which continues from there', async () => {
  const clock = createDemoClock()
  const wait = clock.wait(1000)
  await vi.advanceTimersByTimeAsync(600)
  clock.pause()

  expect(await settledAfter(wait, 5000)).toBe(false)
  expect(clock.elapsed()).toBe(600)
  expect(clock.paused()).toBe(true)

  clock.resume()
  expect(await settledAfter(wait, 399)).toBe(false)
  expect(await settledAfter(wait, 1)).toBe(true)
  expect(clock.paused()).toBe(false)
})

test('listeners hear every pause, resume and rate change', () => {
  const clock = createDemoClock()
  const heard = vi.fn()
  const stop = clock.subscribe(heard)

  clock.pause()
  clock.resume()
  clock.setRate(2)
  stop()
  clock.setRate(1)

  expect(heard).toHaveBeenCalledTimes(3)
  expect(clock.rate()).toBe(1)
})
