import type { Pace } from './backend.ts'
import type { Rate } from './clock.ts'

/**
 * The pace of demo.html's replay at 1×: slow enough to read each bubble as it lands, quick enough
 * that, at the starting speed, the whole check plays in the seconds the landing page's demo link
 * promises (DEMO_SECONDS); a reply types at a pace a person reads at, and a typed answer stays in
 * its box long enough to read before it is sent.
 */
export const PACE: Pace = {
  pauseMs: 1400,
  quietMs: 300,
  typingMs: 60,
  typedChars: 6,
  entryMs: 1000,
}

/** The speed the demo starts at, so a first watch takes about a minute; the playback bar's 1×
 * slows it to the pace above. */
export const START_RATE: Rate = 2
