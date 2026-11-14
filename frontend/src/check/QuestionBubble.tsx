import { type FormEvent, useState } from 'react'
import type { ProfileFields, ProfileUpdate, Question, QuestionField } from '../api/types.ts'
import { formatAmount, formatShekels, normaliseMoneyInput } from '../money.ts'
import { FieldHint } from '../profile/FieldHint.tsx'
import { rejectionText } from '../profile/rejection.ts'
import {
  ANSWER,
  CLONE_CHOICE,
  STAY_CHOICE,
  answerLine,
  isGoalField,
  profileValueText,
  PURPOSE_CHOICES,
  questionHint,
  questionLabel,
  questionText,
  SKIP,
  skipAsZeroLine,
  skipLine,
} from './copy.ts'
import type { QuestionEntry } from './events.ts'

/**
 * Profile amounts for which "none" is a common answer: a skip saves 0, since the calculation
 * cannot go on with them missing, and the chat line says so.
 */
const ZERO_SKIP_FIELDS: ReadonlySet<QuestionField> = new Set([
  'variable_income',
  'variable_income_minimum',
  'existing_loan_payments',
  'savings',
])


/** The person's message for the question, and the profile save that goes before it. */
export interface Answer {
  line: string
  update: ProfileUpdate | null
}

interface Props {
  entry: QuestionEntry
  /** Only a live bubble shows its control; a closed one keeps the question as text. */
  live: boolean
  profile: ProfileFields | null
  /** Resolves false when nothing was sent; rejects with an ApiException on a refused save. */
  onAnswer: (answer: Answer) => Promise<boolean>
  onSkip: (line: string) => Promise<boolean>
  /** Clones the check and sends the line to the copy. */
  onClone: (line: string) => Promise<void>
}

/** The text box's starting value: a profile amount the person already gave, grouped. */
function initialDraft(question: Question, profile: ProfileFields | null): string {
  const { field } = question
  if (field === null || isGoalField(field)) return ''
  if (profile === null) return ''
  const stored = profile[field]
  return stored === null ? '' : formatAmount(stored)
}

/** Whether the control has a text box, answered with the confirm button, besides any taps. */
function takesText(question: Question): boolean {
  if (question.offer_clone === true || question.field === 'purpose') return false
  return question.field !== null || question.choices === null
}

/**
 * Whether the bubble shows a skip. A question with choices of its own (the purpose, the clone
 * offer, or a free question the model gave choices) leaves the person the chat box for any other
 * answer, and a skip there only makes the model ask again.
 */
function offersSkip(question: Question): boolean {
  if (question.offer_clone === true || question.field === 'purpose') return false
  return !(question.field === null && question.choices !== null)
}

function MoneyBox(props: {
  label: string
  describedBy: string | undefined
  value: string
  onChange: (text: string) => void
}) {
  return (
    <span className="field-input">
      <input
        type="text"
        inputMode="decimal"
        aria-label={props.label}
        aria-describedby={props.describedBy}
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
      />
      <span className="unit">₪</span>
    </span>
  )
}

/**
 * A question the model asked, as an assistant bubble: the lead-in, the label and, while live, a
 * control fitted to the field, a confirm button for typed answers and, where offersSkip allows,
 * a skip. It builds the answer and hands it to its owner, which saves and sends it. The clone
 * offer's two choices clone the check, or send the other choice to this one.
 */
export function QuestionBubble({ entry, live, profile, onAnswer, onSkip, onClone }: Props) {
  const { question } = entry
  const label = questionLabel(question)
  const hint = questionHint(question)
  const hintId = `${entry.id}-hint`
  const describedBy = hint === null ? undefined : hintId
  const [draft, setDraft] = useState(() => initialDraft(question, profile))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reply = (value: string, update: ProfileUpdate | null = null): Answer => ({
    line: answerLine(label, value),
    update,
  })

  async function answer(build: () => Answer | null) {
    try {
      const built = build()
      if (built === null) return
      setError(null)
      setBusy(true)
      await onAnswer(built)
    } catch (caught) {
      setError(rejectionText(caught))
    } finally {
      setBusy(false)
    }
  }

  async function skip() {
    const { field } = question
    if (field !== null && ZERO_SKIP_FIELDS.has(field)) {
      return answer(() => ({ line: skipAsZeroLine(label), update: { [field]: '0' } }))
    }
    await settle(() => onSkip(skipLine(label)))
  }

  function typedAnswer(field: QuestionField | null): Answer | null {
    if (field === 'purpose') throw new Error('the purpose question has no text box')
    if (field === null) {
      const text = draft.trim()
      return text === '' ? null : reply(text)
    }
    const amount = normaliseMoneyInput(draft)
    if (amount === null) return null
    if (field === 'price') return reply(formatShekels(amount))
    return reply(profileValueText(amount), { [field]: amount })
  }

  function tap(value: string, update: ProfileUpdate | null = null) {
    void answer(() => reply(value, update))
  }

  function choiceButtons(choices: string[]) {
    return choices.map((choice) => (
      <button key={choice} type="button" disabled={busy} onClick={() => tap(choice)}>
        {choice}
      </button>
    ))
  }

  async function settle(send: () => Promise<unknown>) {
    setBusy(true)
    try {
      await send()
    } finally {
      setBusy(false)
    }
  }

  function control() {
    if (question.offer_clone === true) {
      const clone = () => void settle(() => onClone(CLONE_CHOICE))
      const stay = () => void settle(() => onSkip(STAY_CHOICE))
      return (
        <>
          <button type="button" disabled={busy} onClick={clone}>
            {CLONE_CHOICE}
          </button>
          <button type="button" disabled={busy} onClick={stay}>
            {STAY_CHOICE}
          </button>
        </>
      )
    }
    const { field } = question
    if (field === null) {
      return question.choices === null ? (
        <input
          type="text"
          aria-label={label}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      ) : (
        choiceButtons(question.choices)
      )
    }
    if (field === 'purpose') {
      return choiceButtons(PURPOSE_CHOICES)
    }
    return <MoneyBox label={label} describedBy={describedBy} value={draft} onChange={setDraft} />
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const { field } = question
    void answer(() => typedAnswer(field))
  }

  return (
    <div className="bubble bubble-assistant bubble-question">
      {entry.leadIn !== null && <p className="question-lead-in">{entry.leadIn}</p>}
      <p className="question-label">
        {questionText(question)}
        {live && hint !== null && <FieldHint id={hintId} text={hint} />}
      </p>
      {live && (
        <form onSubmit={submit}>
          <div className="question-control">{control()}</div>
          {error !== null && <p className="field-error">{error}</p>}
          <div className="question-actions">
            {takesText(question) && (
              <button type="submit" className="primary" disabled={busy}>
                {ANSWER}
              </button>
            )}
            {offersSkip(question) && (
              <button type="button" disabled={busy} onClick={() => void skip()}>
                {SKIP}
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  )
}
