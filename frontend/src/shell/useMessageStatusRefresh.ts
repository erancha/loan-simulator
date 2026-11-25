import { useEffect } from 'react'
import type { MessageStatus } from '../api/types.ts'

/**
 * Asks for the person's message status again at the two moments it changes with no send from
 * this page: when a used message frees, and when the tab is shown again, since a message may
 * have been sent elsewhere or have left the window meanwhile. A page with no cap asks for nothing.
 */
export function useMessageStatusRefresh(status: MessageStatus | null, refresh: () => void) {
  const capped = status !== null
  const nextFree = status === null ? null : status.next_free

  useEffect(() => {
    if (nextFree === null) return
    // A second past the time, so the server's clock has passed it too.
    const timer = setTimeout(refresh, Math.max(0, Date.parse(nextFree) - Date.now()) + 1000)
    return () => clearTimeout(timer)
  }, [nextFree, refresh])

  useEffect(() => {
    if (!capped) return
    const onVisibility = () => {
      if (document.visibilityState === 'visible') refresh()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [capped, refresh])
}
