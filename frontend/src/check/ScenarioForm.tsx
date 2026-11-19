import { useState, type FormEvent } from 'react'
import type { Question } from '../api/types.ts'
import { SCENARIO_FORM, SCENARIO_RISE_REFUSED, SCENARIO_RUN, SKIP, scenarioLine } from './copy.ts'
import type { QuestionEntry } from './events.ts'
import type { Answer } from './QuestionBubble.tsx'

// A yearly rise as a person types it: a number, perhaps with a fraction or a minus for a fall.
const RISE = /^-?\d+(\.\d+)?$/

interface Props {
  entry: QuestionEntry
  question: Extract<Question, { kind: 'scenario' }>
  live: boolean
  onAnswer: (answer: Answer) => Promise<boolean>
  onSkip: (line: string) => Promise<boolean>
}

/**
 * The form that simulates the movement the agent offers after a scenario table: one box for its
 * yearly rise in percent, sent as a line the agent prices like any scenario the person names. A
 * closed form keeps only its title.
 */
export function ScenarioForm({ entry, question, live, onAnswer, onSkip }: Props) {
  const [rise, setRise] = useState('')
  const [refused, setRefused] = useState(false)
  const [busy, setBusy] = useState(false)
  const form = SCENARIO_FORM[question.movement]
  const boxId = `${entry.id}-rise`

  async function submit(event: FormEvent) {
    event.preventDefault()
    const typed = rise.trim()
    if (!RISE.test(typed)) {
      setRefused(true)
      return
    }
    setRefused(false)
    setBusy(true)
    try {
      await onAnswer({ line: scenarioLine(question.movement, typed), update: null })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bubble bubble-assistant bubble-question">
      <p className="question-label">{form.title}</p>
      {live && <p className="card-note">{form.intro}</p>}
      {live && (
        <form className="scenario-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor={boxId}>{form.label}</label>
          <span className="scenario-rise">
            <input
              id={boxId}
              type="text"
              inputMode="decimal"
              value={rise}
              onChange={(event) => setRise(event.target.value)}
              aria-invalid={refused}
            />
            %
          </span>
          {refused && (
            <p className="field-error" role="alert">
              {SCENARIO_RISE_REFUSED}
            </p>
          )}
          <button type="submit" className="primary" disabled={busy}>
            {SCENARIO_RUN}
          </button>
          <button
            type="button"
            className="underline-link"
            disabled={busy}
            onClick={() => void onSkip(SKIP)}
          >
            {SKIP}
          </button>
        </form>
      )}
    </div>
  )
}
