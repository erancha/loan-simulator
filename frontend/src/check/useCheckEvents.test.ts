import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { SIGNED_OUT_EVENT } from '../api/client.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'
import { isMessage } from './events.ts'
import type { ChatEntry } from './events.ts'
import { useCheckEvents } from './useCheckEvents.ts'

/** Each message as its text; a question or a chart, which has none of its own, as its id. */
function entryTexts(entries: ChatEntry[]): string[] {
  return entries.map((m) => (isMessage(m) ? m.text : m.id))
}

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

test('frames reduce into state; deltas carry no seq', () => {
  const { result } = renderHook(() => useCheckEvents('c1'))
  const source = FakeEventSource.last()
  expect(source.url).toBe('/api/checks/c1/events')
  act(() => {
    source.emit('message.user', '{"text":"שלום"}', '1')
    source.emit('message.delta', '{"message_id":"a1","text":"הי"}')
  })
  expect(result.current.state.lastSeq).toBe(1)
  expect(entryTexts(result.current.state.messages)).toEqual(['שלום', 'הי'])
})

test('no source is opened without a check id', () => {
  renderHook(() => useCheckEvents(null))
  expect(FakeEventSource.instances).toHaveLength(0)
})

test('switching checks closes the old source and starts clean', () => {
  const { result, rerender } = renderHook(({ id }) => useCheckEvents(id), {
    initialProps: { id: 'c1' as string | null },
  })
  const first = FakeEventSource.last()
  act(() => first.emit('message.user', '{"text":"שלום"}', '1'))
  rerender({ id: 'c2' })
  expect(first.closed).toBe(true)
  expect(FakeEventSource.last().url).toBe('/api/checks/c2/events')
  expect(result.current.state.messages).toEqual([])
  act(() => first.emit('message.user', '{"text":"stale"}', '2'))
  expect(result.current.state.messages).toEqual([])
  rerender({ id: null })
  expect(result.current.state.messages).toEqual([])
})

test('a delta carrying the last stored id is applied', () => {
  const { result } = renderHook(() => useCheckEvents('c1'))
  const source = FakeEventSource.last()
  act(() => {
    source.emit('message.user', '{"text":"שלום"}', '7')
    source.emit('message.delta', '{"message_id":"a1","text":"הי"}', '7')
  })
  expect(entryTexts(result.current.state.messages)).toEqual(['שלום', 'הי'])
})

test('a malformed frame is logged and skipped', () => {
  const error = vi.spyOn(console, 'error').mockImplementation(() => undefined)
  const { result } = renderHook(() => useCheckEvents('c1'))
  const source = FakeEventSource.last()
  act(() => {
    source.emit('message.user', '{oops', '1')
    source.emit('message.user', '{"text":"no id"}')
    source.emit('message.user', '{"text":"ok"}', '3')
  })
  expect(error).toHaveBeenCalledTimes(2)
  expect(entryTexts(result.current.state.messages)).toEqual(['ok'])
  expect(error).toHaveBeenLastCalledWith('message.user frame without a sequence number', '')
  error.mockRestore()
})

test('an error with the source closed signals sign-out', () => {
  const signedOut = vi.fn()
  window.addEventListener(SIGNED_OUT_EVENT, signedOut)
  renderHook(() => useCheckEvents('c1'))
  const source = FakeEventSource.last()
  source.readyState = 0
  act(() => source.onerror?.())
  expect(signedOut).not.toHaveBeenCalled()
  source.readyState = FakeEventSource.CLOSED
  act(() => source.onerror?.())
  expect(signedOut).toHaveBeenCalledTimes(1)
  window.removeEventListener(SIGNED_OUT_EVENT, signedOut)
})

test("a stored frame's time is lifted out of its data onto the entry", () => {
  const { result } = renderHook(() => useCheckEvents('c1'))
  const at = '2026-11-14T09:30:05+00:00'
  act(() => {
    const source = FakeEventSource.last()
    source.emit('message.user', JSON.stringify({ text: 'שלום', at }), '1')
    source.emit('loan.set', JSON.stringify({ purpose: 'רכב', amount: '50000', at }), '2')
  })
  expect(result.current.state.messages).toEqual([
    { id: 'u-1', role: 'user', text: 'שלום', complete: true, at },
  ])
  expect(result.current.state.loan).toEqual({ purpose: 'רכב', amount: '50000' })
})
