import { useState } from 'react'

/**
 * Numbers requests when they are sent, so an answer older than one already applied is dropped.
 * `begin` numbers a request; `accept` tells whether its answer may be applied and, when it may,
 * makes it the newest applied.
 */
export interface Latest {
  begin(): number
  accept(request: number): boolean
}

export function latestOnly(): Latest {
  let sent = 0
  let applied = 0
  return {
    begin: () => ++sent,
    accept(request) {
      if (request < applied) return false
      applied = request
      return true
    },
  }
}

/** One numbering for the life of a component. */
export function useLatest(): Latest {
  return useState(latestOnly)[0]
}
