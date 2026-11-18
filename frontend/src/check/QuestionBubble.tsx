import { type FormEvent, useState } from 'react'
import type { Finances, Question, QuestionField, TermBasis, TermRow } from '../api/types.ts'
import { exceeds, formatAmount, formatShekels, normaliseMoneyInput } from '../money.ts'
import {
  ANSWER,
  CHOOSE_TERM,
  CURRENT_TERM,
  STEADY_PAYMENT,
  TERMS_HEADINGS,
  termsCeilingNote,
  amountText,
  answerLine,
  CEILING_CLEARED,
  CEILING_LABEL,
  CLONE_CHOICE,
  confirmedTermLine,
  DONT_KNOW,
  NOT_A_NUMBER,
  PAYMENT_PLANNING,
  PURPOSE_CHOICES,
  questionHint,
  questionLabel,
  questionText,
  SKIP,
  skipLine,
  STAY_CHOICE,
  termBasisLine,
  TERM_BOX_LABEL,
  TERM_BOX_PLACEHOLDER,
  TERM_MAX_MONTHS,
  TERM_MIN_MONTHS,
  TERM_OUT_OF_RANGE,
} from './copy.ts'
import { withValues } from './emphasis.tsx'
import type { QuestionEntry } from './events.ts'
import { FieldHint } from './FieldHint.tsx'
import { hasBothFinances } from './FinancesPanel.tsx'
import { OfferForm } from './OfferForm.tsx'
import { rejectionText } from './rejection.ts'

/**
 * The person's message for the question and what goes with it: finances figures, or a confirmed
 * term with any ceiling typed beside it, saved before the line; or a new ceiling alone from the
 * term card, which the server saves and answers with a term card for it. The offer form's answer
 * is its line alone, with no update: the model saves the offer from the line.
 */
export type Answer =
  | { line: string; update: Partial<Finances> | null }
  | { line: string; term: number; ceiling: string | null }
  | { line: string; ceiling: string }

/**
 * The answer that confirms a term, and a new ceiling when one is given: saved by the page, so
 * the model reads them as set.
 */
export function termConfirmation(months: number, ceiling: string | null): Answer {
  return { line: confirmedTermLine(months, ceiling), term: months, ceiling }
}

/** The months in a typed term, "78" or "78 חודשים"; null for any other text. */
export function typedTerm(text: string): number | null {
  const match = /^\s*(\d+)\s*(חודשים)?\s*[.!]?\s*$/.exec(text)
  return match === null ? null : Number(match[1])
}

const FINANCES_FIELDS: ReadonlySet<QuestionField> = new Set(['net_fixed_income', 'fixed_expenses'])

function isFinancesField(field: QuestionField): field is keyof Finances {
  return FINANCES_FIELDS.has(field)
}

/**
 * A question with a field of its own or the model's own sentence: everything but the term card,
 * the terms card and the offer form.
 */
type FieldQuestion = Exclude<Question, { kind: 'term' | 'terms' | 'offer' }>

interface Props {
  entry: QuestionEntry
  /** Only a live bubble shows its control; a closed one keeps the question as text. */
  live: boolean
  finances: Finances | null
  /** The payment ceiling the check holds, which the term card starts its box with. */
  ceiling: string | null
  /** How the ceiling was derived from the finances; null for a stated ceiling or none. */
  ceilingFormula: string | null
  /** Resolves false when nothing was sent; rejects with an ApiException on a refused save. */
  onAnswer: (answer: Answer) => Promise<boolean>
  onSkip: (line: string) => Promise<boolean>
  /** Clones the check and sends the copy the request the clone offer answers. */
  onClone: () => Promise<void>
}

/** The text box's starting value: a finances figure the person already gave, grouped. */
function initialDraft(question: FieldQuestion, finances: Finances | null): string {
  const { field } = question
  if (field === null || finances === null || !isFinancesField(field)) return ''
  const stored = finances[field]
  return stored === null ? '' : formatAmount(stored)
}

/** Whether the control has a text box, answered with the confirm button, besides any taps. */
function takesText(question: FieldQuestion): boolean {
  if (question.offer_clone === true || question.field === 'purpose') return false
  return question.field !== null || question.choices === null
}

/**
 * Whether the bubble shows a skip. A question with choices of its own (the purpose, the clone
 * offer, or a free question the model gave choices) leaves the person the chat box for any other
 * answer, and a skip there only makes the model ask again.
 */
function offersSkip(question: FieldQuestion): boolean {
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
 * control fitted to the question. The term card confirms or changes the calculated term, the
 * terms card chooses among the recommendation's term and the terms beside it, and the offer form
 * takes a lender's offer; every other question is a field's, handled by FieldBubble.
 */
export function QuestionBubble(props: Props) {
  const { question } = props.entry
  if (question.kind === 'term') {
    return (
      <TermBubble
        {...props}
        termMonths={question.term_months}
        firstPayment={question.first_payment}
        basis={question.basis}
      />
    )
  }
  if (question.kind === 'terms') {
    return <TermsBubble {...props} question={question} />
  }
  if (question.kind === 'offer') {
    return (
      <OfferForm
        entry={props.entry}
        question={question}
        live={props.live}
        onAnswer={props.onAnswer}
        onSkip={props.onSkip}
      />
    )
  }
  return <FieldBubble {...props} question={question} />
}

/** The ceiling box's text for an amount: whole shekels, grouped; empty for none. */
function ceilingDraft(ceiling: string | null): string {
  return ceiling === null ? '' : formatAmount(ceiling)
}

/**
 * The term card: a first calculation of a term with its first payment, the assumption it was
 * worked out from when the stored question carries one, both with their amounts and months in the
 * colour of a value as a reply shows them, and one form with the term and the payment ceiling,
 * each starting at the check's value, and one confirm button. Beside the ceiling
 * box a link sends that the person wants to plan the monthly payment first; nothing is saved. Once
 * the check holds both finances figures that planning is done, so the link is not offered. A new
 * ceiling with the term left as calculated asks for a card worked out from that ceiling; anything
 * else confirms the term in the box, with the new ceiling when there is one.
 */
function TermBubble({
  entry,
  live,
  finances,
  ceiling,
  ceilingFormula,
  onAnswer,
  onSkip,
  termMonths,
  firstPayment,
  basis,
}: Props & { termMonths: number; firstPayment: string; basis: TermBasis | undefined }) {
  const [termDraft, setTermDraft] = useState(String(termMonths))
  const [ceilingText, setCeilingText] = useState(() => ceilingDraft(ceiling))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  /** The answer the form holds, or the text of what is wrong with it. */
  function built(): Answer | string {
    const months = typedTerm(termDraft)
    if (months === null || months < TERM_MIN_MONTHS || months > TERM_MAX_MONTHS) {
      return TERM_OUT_OF_RANGE
    }
    const typed = normaliseMoneyInput(ceilingText)
    if (typed === null && ceiling !== null) return CEILING_CLEARED
    const held = ceiling === null ? null : normaliseMoneyInput(ceilingDraft(ceiling))
    const newCeiling = typed === held ? null : typed
    if (newCeiling !== null && months === termMonths) {
      return { line: answerLine(CEILING_LABEL, amountText(newCeiling)), ceiling: newCeiling }
    }
    return termConfirmation(months, newCeiling)
  }

  async function plan() {
    setBusy(true)
    try {
      await onSkip(PAYMENT_PLANNING)
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    let answer: Answer | string
    try {
      answer = built()
    } catch (caught) {
      if (!(caught instanceof RangeError)) throw caught
      answer = NOT_A_NUMBER
    }
    if (typeof answer === 'string') {
      setError(answer)
      return
    }
    setError(null)
    setBusy(true)
    try {
      await onAnswer(answer)
    } catch (caught) {
      setError(rejectionText(caught))
    } finally {
      setBusy(false)
    }
  }

  const termId = `${entry.id}-term`
  const ceilingId = `${entry.id}-ceiling`
  return (
    <div className="bubble bubble-assistant bubble-question">
      {entry.leadIn !== null && <p className="question-lead-in">{entry.leadIn}</p>}
      <p className="question-label">{withValues(questionText(entry.question))}</p>
      {live && basis !== undefined && (
        <p className="card-note">{withValues(termBasisLine(basis, firstPayment))}</p>
      )}
      {live && (
        <form className="term-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor={termId}>{TERM_BOX_LABEL}</label>
          <input
            id={termId}
            type="text"
            inputMode="numeric"
            placeholder={TERM_BOX_PLACEHOLDER}
            value={termDraft}
            onChange={(event) => setTermDraft(event.target.value)}
          />
          <label htmlFor={ceilingId}>{CEILING_LABEL}</label>
          <span className="field-input">
            <input
              id={ceilingId}
              type="text"
              inputMode="decimal"
              value={ceilingText}
              onChange={(event) => setCeilingText(event.target.value)}
            />
            <span className="unit">₪</span>
            {ceilingFormula !== null && ceilingText === ceilingDraft(ceiling) && (
              <span className="ceiling-formula">{ceilingFormula}</span>
            )}
            {(finances === null || !hasBothFinances(finances)) && (
              <button
                type="button"
                className="underline-link term-planning"
                disabled={busy}
                onClick={() => void plan()}
              >
                {PAYMENT_PLANNING}
              </button>
            )}
          </span>
          {error !== null && <p className="field-error">{error}</p>}
          <div className="question-actions">
            <button type="submit" className="primary" disabled={busy}>
              {ANSWER}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

type TermsQuestion = Extract<Question, { kind: 'terms' }>

/**
 * The terms card: the recommended option at its own term and at the terms shorter or longer, one
 * row each with the payment today and the highest the worst period in history would have raised
 * it to, marked when that passes the ceiling. Such a term stays a choice: the mark informs the
 * person, who decides. While live, each other term has a button that confirms it, saved by the
 * page like a confirmed term card; the person may also go on in the chat.
 */
function TermsBubble({ entry, live, onAnswer, question }: Props & { question: TermsQuestion }) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const ceiling = question.payment_ceiling

  function aboveInTheWorstPeriod(row: TermRow): boolean {
    return ceiling !== null && row.worst_payment !== null && exceeds(row.worst_payment, ceiling)
  }

  async function choose(months: number) {
    setError(null)
    setBusy(true)
    try {
      await onAnswer(termConfirmation(months, null))
    } catch (caught) {
      setError(rejectionText(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bubble bubble-assistant bubble-question">
      {entry.leadIn !== null && <p className="question-lead-in">{entry.leadIn}</p>}
      <p className="question-label">{withValues(questionText(question))}</p>
      <table className="terms-table">
        <thead>
          <tr>
            <th scope="col">{TERMS_HEADINGS.term}</th>
            <th scope="col">{TERMS_HEADINGS.today}</th>
            <th scope="col">{TERMS_HEADINGS.worst}</th>
            {live && <td />}
          </tr>
        </thead>
        <tbody>
          {question.rows.map((row, index) => (
            <tr key={row.term_months} className={index === 0 ? 'terms-current' : undefined}>
              <th scope="row">{row.term_months}</th>
              <td>{formatShekels(row.first_payment)}</td>
              <td>
                {row.worst_payment === null ? (
                  STEADY_PAYMENT
                ) : (
                  <span className={aboveInTheWorstPeriod(row) ? 'chip chip-amber' : undefined}>
                    {formatShekels(row.worst_payment)}
                  </span>
                )}
              </td>
              {live && (
                <td>
                  {index === 0 ? (
                    <span className="terms-current-label">{CURRENT_TERM}</span>
                  ) : (
                    <button
                      type="button"
                      className="primary"
                      disabled={busy}
                      onClick={() => void choose(row.term_months)}
                    >
                      {CHOOSE_TERM}
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {ceiling !== null && question.rows.some(aboveInTheWorstPeriod) && (
        <p className="card-note">{withValues(termsCeilingNote(ceiling))}</p>
      )}
      {error !== null && <p className="field-error">{error}</p>}
    </div>
  )
}

/**
 * A field's question or the model's own: the label and, while live, a control fitted to the
 * field, a confirm button for typed answers and, where offersSkip allows, a skip. It builds the
 * answer and hands it to its owner, which saves and sends it. The clone offer's two choices
 * clone the check, or send the other choice to this one.
 */
function FieldBubble({
  entry,
  live,
  finances,
  onAnswer,
  onSkip,
  onClone,
  question,
}: Props & { question: FieldQuestion }) {
  const label = questionLabel(question)
  const hint = questionHint(question)
  const hintId = `${entry.id}-hint`
  const describedBy = hint === null ? undefined : hintId
  const [draft, setDraft] = useState(() => initialDraft(question, finances))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reply = (value: string, update: Partial<Finances> | null = null): Answer => ({
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
    return reply(amountText(amount), isFinancesField(field) ? { [field]: amount } : null)
  }

  function tap(value: string) {
    void answer(() => reply(value))
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
      const clone = () => void settle(onClone)
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
            {question.field === 'payment_ceiling' && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void settle(() => onSkip(DONT_KNOW))}
              >
                {DONT_KNOW}
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  )
}
