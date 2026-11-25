import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { MessageStatus } from '../api/types.ts'
import { useMessageStatusRefresh } from './useMessageStatusRefresh.ts'

const NOW = new Date('2026-11-25T10:00:00Z')

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})

afterEach(() => {
  vi.useRealTimers()
})

function showTab(state: DocumentVisibilityState) {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue(state)
  document.dispatchEvent(new Event('visibilitychange'))
}

test('the status is asked again once the next message frees', () => {
  const refresh = vi.fn()
  const out: MessageStatus = { limit: 20, left: 4, next_free: '2026-11-25T10:05:00Z' }
  renderHook(() => useMessageStatusRefresh(out, refresh))

  vi.advanceTimersByTime(5 * 60 * 1000 - 1)
  expect(refresh).not.toHaveBeenCalled()
  vi.advanceTimersByTime(2000)
  expect(refresh).toHaveBeenCalledTimes(1)
})

test('with no message used no timer runs', () => {
  const refresh = vi.fn()
  renderHook(() => useMessageStatusRefresh({ limit: 20, left: 20, next_free: null }, refresh))

  vi.advanceTimersByTime(48 * 60 * 60 * 1000)
  expect(refresh).not.toHaveBeenCalled()
})

test('the status is asked again when the tab is shown again, and not when it is hidden', () => {
  const refresh = vi.fn()
  renderHook(() => useMessageStatusRefresh({ limit: 20, left: 20, next_free: null }, refresh))

  showTab('hidden')
  expect(refresh).not.toHaveBeenCalled()
  showTab('visible')
  expect(refresh).toHaveBeenCalledTimes(1)
})

test('a page with no cap asks for nothing', () => {
  const refresh = vi.fn()
  renderHook(() => useMessageStatusRefresh(null, refresh))

  showTab('visible')
  expect(refresh).not.toHaveBeenCalled()
})
