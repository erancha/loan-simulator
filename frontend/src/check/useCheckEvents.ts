import { useEffect, useState } from 'react'
import { SIGNED_OUT_EVENT } from '../api/client.ts'
import { CHECK_EVENT_TYPES } from '../api/types.ts'
import type { CheckEvent } from '../api/types.ts'
import { initialState, reduce } from './events.ts'
import type { CheckState } from './events.ts'

interface Stream {
  checkId: string
  state: CheckState
}

function parseSeq(lastEventId: string): number | null {
  const seq = Number(lastEventId)
  return Number.isInteger(seq) && seq > 0 ? seq : null
}

function streamOf(stream: Stream | null, checkId: string): Stream {
  return stream?.checkId === checkId ? stream : { checkId, state: initialState }
}

/**
 * Subscribes to one check's event stream and folds its frames into a CheckState.
 *
 * The browser owns reconnection: after a dropped connection it resends Last-Event-ID, so the
 * backend replays only the stored events that followed. Every event frame except message.delta
 * carries its own id, which becomes its sequence number. A message.delta frame has no id of its
 * own, so the browser reports the last stored frame's id on it; the hook ignores that id and never
 * deduplicates deltas. A frame that is not JSON or that should carry an id and has none is logged
 * with console.error and skipped; the stream keeps going. The browser retries a dropped
 * connection by itself but closes the source for good on a response it will not retry (a 401
 * among them); the hook treats any such close as signed out and dispatches SIGNED_OUT_EVENT.
 */
export function useCheckEvents(checkId: string | null) {
  const [stream, setStream] = useState<Stream | null>(null)

  useEffect(() => {
    if (checkId === null) return
    const source = new EventSource(`/api/checks/${checkId}/events`)
    const update = (change: (current: Stream) => Stream) =>
      setStream((current) => change(streamOf(current, checkId)))
    const onFrame = (type: CheckEvent['type']) => (frame: MessageEvent<string>) => {
      let data: unknown
      try {
        data = JSON.parse(frame.data)
      } catch (error) {
        console.error(`malformed ${type} frame`, frame.data, error)
        return
      }
      const seq = type === 'message.delta' ? null : parseSeq(frame.lastEventId)
      if (type !== 'message.delta' && seq === null) {
        console.error(`${type} frame without a sequence number`, frame.lastEventId)
        return
      }
      const event = { type, data, seq } as CheckEvent
      update((current) => ({ ...current, state: reduce(current.state, event) }))
    }
    const listeners = CHECK_EVENT_TYPES.map((type) => [type, onFrame(type)] as const)
    for (const [type, listener] of listeners) source.addEventListener(type, listener)
    source.onerror = () => {
      if (source.readyState !== EventSource.CLOSED) return
      window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
    }
    return () => {
      for (const [type, listener] of listeners) source.removeEventListener(type, listener)
      source.onerror = null
      source.close()
      setStream(null)
    }
  }, [checkId])

  return { state: checkId === null ? initialState : streamOf(stream, checkId).state }
}
