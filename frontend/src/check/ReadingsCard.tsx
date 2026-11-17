import { type FormEvent, useState } from 'react'
import type { AwaitingOffer, Reading, ReadingKind } from '../api/types.ts'
import {
  amountGapText,
  amountQuestion,
  ANSWER,
  CONTINUE_TO_ANOTHER_OFFER,
  CONTINUE_TO_ANOTHER_OFFER_LINES,
  COPY_QUESTION,
  COVERS_SAME_TERMS,
  droppedText,
  equivalentRateText,
  identificationText,
  lenderQuestion,
  lenderQuestionTitle,
  MARKET_SAMPLE,
  MOST_LIKELY,
  NOT_COVERED,
  READING_BEHAVIOUR,
  READING_MISSING,
  READINGS_TITLE,
  readingsClosing,
  readingText,
  settledReadingText,
  wordsSuggestText,
} from './copy.ts'
import { withValues } from './emphasis.tsx'
import { quotedBelowLoan, type ReadingsEntry } from './events.ts'
import { rejectionText } from './rejection.ts'

interface Props {
  entry: ReadingsEntry
  /** The check's loan amount; null only before the check has a loan, when no card waits. */
  loanAmount: string | null
  /** False while a turn runs or the check is archived. */
  live: boolean
  onConfirm: (reading: Reading) => Promise<void>
  /** The lender's answer to an offer quoted for less than the loan, with the reading it lends
   * the loan amount by; null when it does not lend it. */
  onAnswerAmount: (covers: boolean, reading: Reading | null) => Promise<void>
  onContinue: () => Promise<boolean>
  onMarketChip: () => void
}

function readingOf(readings: Reading[], kind: ReadingKind): Reading {
  const reading = readings.find((r) => r.kind === kind)
  if (reading === undefined) throw new Error(`the offer has no ${kind} reading`)
  return reading
}

/** The one reading a quoted payment identified. */
function identifiedReading(offer: AwaitingOffer): Reading {
  const [reading, ...more] = offer.readings
  if (reading === undefined || more.length > 0) {
    throw new Error(`identified offer ${offer.awaiting_id} holds ${offer.readings.length} readings`)
  }
  return reading
}

/** The payment an identified offer was identified by; an offer is identified only by one. */
function quotedPayment(offer: AwaitingOffer): string {
  if (offer.monthly_payment === null) {
    throw new Error(`identified offer ${offer.awaiting_id} quotes no payment`)
  }
  return offer.monthly_payment
}

/**
 * The card of an offer that waits on its lender: what its payment is worth as a rate, what the
 * lender's words suggest, the question to put to the lender, and the readings the answer may
 * confirm, the likely one chosen. An offer quoted for less than the check's loan also asks the
 * lender for the loan amount on the same terms, answered yes or no; one its payment identified
 * shows that reading in place of the choices. Answering hands the chosen reading to the page; a
 * settled card shows the reading the offer was saved by, which may be one it never offered, and
 * a dropped card says the offer does not cover the loan, each in place of the questions. A
 * waiting card also has a button for describing another offer meanwhile and the market chip.
 */
export function ReadingsCard({
  entry,
  loanAmount,
  live,
  onConfirm,
  onAnswerAmount,
  onContinue,
  onMarketChip,
}: Props) {
  const { offer, settled, dropped } = entry
  const [chosen, setChosen] = useState<ReadingKind | null>(offer.likely)
  const [error, setError] = useState<string | null>(null)
  // True from a click until its request ends; an answer that went through keeps the card locked
  // until offer.settled or offer.dropped replaces its questions, so a second click sends nothing.
  const [busy, setBusy] = useState(false)
  // A later emit of the offer replaces it in place, and its readings or likely reading may differ,
  // so the choice starts over from the new offer's likely reading.
  const [choiceOffer, setChoiceOffer] = useState(offer)
  if (choiceOffer !== offer) {
    setChoiceOffer(offer)
    setChosen(offer.likely)
    setError(null)
  }

  if (dropped !== null) {
    return (
      <div id={`awaiting-${offer.awaiting_id}`} className="bubble bubble-assistant readings-card">
        <p className="readings-settled">{withValues(droppedText(dropped))}</p>
      </div>
    )
  }
  if (settled !== null) {
    return (
      <div id={`awaiting-${offer.awaiting_id}`} className="bubble bubble-assistant readings-card">
        {offer.payment_rate !== null && !offer.identified && (
          <p>{withValues(equivalentRateText(offer.payment_rate))}</p>
        )}
        <p className="readings-settled">{withValues(settledReadingText(settled))}</p>
      </div>
    )
  }

  if (loanAmount === null) throw new Error(`awaiting offer ${offer.awaiting_id} on a check with no loan`)
  const short = quotedBelowLoan(offer, loanAmount)
  // An identified offer's type is known, so only its amount is put to the lender; once the
  // check's loan is lowered to the quoted amount, the card asks nothing.
  const typeQuestion = offer.identified ? null : lenderQuestion(offer.monthly_payment)
  const question = [typeQuestion, short ? amountQuestion(loanAmount) : null]
    .filter((part) => part !== null)
    .join(' ')
  const suggests = wordsSuggestText(offer.likely, offer.type_words, offer.lender)
  const locked = !live || busy

  async function answer(send: () => Promise<void>) {
    setError(null)
    setBusy(true)
    try {
      await send()
    } catch (caught) {
      setError(rejectionText(caught))
      setBusy(false)
    }
  }

  function chosenReading(): Reading | null {
    if (offer.identified) return identifiedReading(offer)
    if (chosen === null) {
      setError(READING_MISSING)
      return null
    }
    return readingOf(offer.readings, chosen)
  }

  function confirm(event: FormEvent) {
    event.preventDefault()
    const reading = chosenReading()
    if (reading === null) return
    void answer(() => (short ? onAnswerAmount(true, reading) : onConfirm(reading)))
  }

  async function continueOffers() {
    setBusy(true)
    try {
      await onContinue()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div id={`awaiting-${offer.awaiting_id}`} className="bubble bubble-assistant readings-card">
      {offer.identified ? (
        <p>
          {withValues(
            identificationText(
              identifiedReading(offer),
              offer.prime,
              offer.rate_as_of,
              quotedPayment(offer),
            ),
          )}
        </p>
      ) : (
        <>
          {offer.payment_rate !== null && (
            <p>{withValues(equivalentRateText(offer.payment_rate))}</p>
          )}
          {suggests !== null && <p>{suggests}</p>}
        </>
      )}
      {short && <p>{withValues(amountGapText(offer.lender, offer.amount, loanAmount))}</p>}
      <form onSubmit={confirm}>
        {question !== '' && (
          <div className="readings-ask">
            <div className="readings-ask-caption">
              <span>{lenderQuestionTitle(offer.lender)}</span>
              <button
                type="button"
                className="link-button"
                onClick={() => void navigator.clipboard.writeText(question)}
              >
                {COPY_QUESTION}
              </button>
            </div>
            <p>{question}</p>
          </div>
        )}
        {!offer.identified && (
          <fieldset className="readings-choices" disabled={locked}>
            <legend>{READINGS_TITLE}</legend>
            {offer.readings.map((reading) => (
              <label
                key={reading.kind}
                className={reading.kind === offer.likely ? 'reading reading-likely' : 'reading'}
              >
                <input
                  type="radio"
                  name={`reading-${offer.awaiting_id}`}
                  checked={chosen === reading.kind}
                  onChange={() => setChosen(reading.kind)}
                />
                <span>{withValues(readingText(reading))}</span>{' '}
                <small>— {READING_BEHAVIOUR[reading.kind]}</small>
                {reading.kind === offer.likely && (
                  <span className="reading-tag">{MOST_LIKELY}</span>
                )}
              </label>
            ))}
          </fieldset>
        )}
        {error !== null && <p className="field-error">{error}</p>}
        <div className="question-actions">
          <button type="submit" className="primary" disabled={locked}>
            {short ? COVERS_SAME_TERMS : ANSWER}
          </button>
          {short && (
            <button
              type="button"
              disabled={locked}
              onClick={() => void answer(() => onAnswerAmount(false, null))}
            >
              {NOT_COVERED}
            </button>
          )}
          <button
            type="button"
            aria-label={CONTINUE_TO_ANOTHER_OFFER}
            disabled={locked}
            onClick={() => void continueOffers()}
          >
            {CONTINUE_TO_ANOTHER_OFFER_LINES[0]}
            <br />
            {CONTINUE_TO_ANOTHER_OFFER_LINES[1]}
          </button>
        </div>
        <p className="readings-hint">{readingsClosing(offer.lender)}</p>
        <div className="chat-samples">
          <button type="button" disabled={!live} onClick={onMarketChip}>
            {MARKET_SAMPLE.label}
          </button>
        </div>
      </form>
    </div>
  )
}
