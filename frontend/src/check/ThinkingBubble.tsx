import { useEffect, useState } from 'react'
import type { TurnStep } from '../api/types.ts'
import { stepsHint, thinkingLine } from './copy.ts'
import { FieldHint } from './FieldHint.tsx'
import { TOOL_ACTIVITY } from './toolActivity.ts'

const TICK_MS = 1000
const HINT_ID = 'thinking-steps'

/** The activities of a step's tools; a tool the page has no text for shows as thinking and is
 * logged, so a tool added to the agent without its text surfaces. */
function activitiesOf(step: TurnStep): string[] {
  const activities = step.tools.map((tool) => TOOL_ACTIVITY[tool])
  if (activities.some((activity) => activity === undefined)) {
    console.error('turn.step names a tool with no activity text', step.tools)
    return []
  }
  return [...new Set(activities as string[])]
}

/**
 * The bubble shown while a turn runs and no reply streams yet. It says what the agent does now,
 * from the turn's live `turn.step` events (thinking, or the tools it runs), the seconds the turn
 * has run and the step it is on; its hint says what a step is and lists the turn's steps so far.
 * The seconds count from the turn's start by the server's clock, so leaving the check and coming
 * back, or reloading, shows the turn's true time; the demo, whose recording holds no times,
 * counts from the bubble's own appearance.
 */
export function ThinkingBubble({
  steps,
  startedAt,
}: {
  steps: TurnStep[]
  startedAt: string | null
}) {
  const [mounted] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [])
  const started = startedAt === null ? mounted : Date.parse(startedAt)
  // A device clock a little behind the server's would give a turn that just started negative
  // seconds; it reads as under a second instead.
  const seconds = Math.max(0, Math.floor((now - started) / TICK_MS))
  const described = steps.map((step) => ({ step: step.step, activities: activitiesOf(step) }))
  const current = described.at(-1)
  const line =
    current === undefined
      ? thinkingLine([], null, seconds)
      : thinkingLine(current.activities, current.step, seconds)
  return (
    <p className="bubble bubble-thinking" aria-describedby={HINT_ID}>
      {line} <FieldHint id={HINT_ID} text={stepsHint(described)} />
    </p>
  )
}
