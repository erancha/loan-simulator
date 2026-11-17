import type { Pace } from './backend.ts'

/**
 * The pace demo.html replays its recording at: slow enough to read each bubble as it lands, quick
 * enough that the whole check plays in the minutes the landing page's demo link promises
 * (DEMO_MINUTES); a reply types at a pace a person reads at, and a typed answer stays in its box
 * long enough to read before it is sent.
 */
export const PACE: Pace = { pauseMs: 1400, typingMs: 60, typedChars: 6, entryMs: 1000 }
