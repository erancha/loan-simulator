import { type FormEvent, useId, useState } from 'react'
import { exceeds, normaliseMoneyInput, subtractAmounts } from '../money.ts'
import {
  CONTINUE,
  LOAN_MAX_AMOUNT,
  LOAN_MIN_AMOUNT,
  OPENING_AMOUNT_INVALID,
  OPENING_CAPITAL_COVERS,
  OPENING_CAPITAL_LABEL,
  OPENING_MODE,
  OPENING_MODE_LABEL,
  OPENING_PRICE_LABEL,
  OPENING_PURPOSE_LABEL,
  OPENING_PURPOSE_MISSING,
  OPENING_TITLE,
  openingLoanLine,
  PURPOSE_CHOICES,
} from './copy.ts'
import { GroupedAmountInput } from './GroupedAmountInput.tsx'
import { isRefusal } from './rejection.ts'

type Mode = keyof typeof OPENING_MODE

/** The decimal a box holds; null when it is empty or no number, which the card marks. */
function typedAmount(text: string): string | null {
  try {
    return normaliseMoneyInput(text)
  } catch (caught) {
    if (caught instanceof RangeError) return null
    throw caught
  }
}

function inLoanRange(amount: string): boolean {
  return !exceeds(LOAN_MIN_AMOUNT, amount) && !exceeds(amount, LOAN_MAX_AMOUNT)
}

interface Props {
  /**
   * Resolves true once the loan is sent, and the card then stays disabled until the conversation
   * replaces it; false when it was not sent, so the person may press again. Rejects with a 422
   * ApiException when the loan is refused. Its detail is the server's English reason for the
   * model, so the card logs it and shows its own line.
   */
  onSubmit: (purpose: string, amount: string) => Promise<boolean>
}

/**
 * The card a new check opens with, in two panels: the loan's goal, and its amount, typed directly
 * or worked out from the purchase price less the person's own capital. Pressing the button judges
 * every box and marks the ones that are empty or out of range, sending nothing; a valid card is
 * sent once, with the amount as a decimal string.
 */
export function OpeningCard({ onSubmit }: Props) {
  const id = useId()
  const [purpose, setPurpose] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>('loan')
  const [loanText, setLoanText] = useState('')
  const [priceText, setPriceText] = useState('')
  const [capitalText, setCapitalText] = useState('')
  // The boxes are judged once the person tries to send, not while they are still typing.
  const [tried, setTried] = useState(false)
  const [rejection, setRejection] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const price = typedAmount(priceText)
  const capital = typedAmount(capitalText)
  const covers = mode === 'price' && price !== null && capital !== null && !exceeds(price, capital)
  const priced = mode === 'price' && price !== null && capital !== null && !covers
  const amount =
    mode === 'loan' ? typedAmount(loanText) : priced ? subtractAmounts(price, capital) : null
  const amountValid = amount !== null && inLoanRange(amount)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setTried(true)
    if (purpose === null || amount === null || !amountValid) return
    setRejection(null)
    setBusy(true)
    try {
      if (!(await onSubmit(purpose, amount))) setBusy(false)
    } catch (caught) {
      setBusy(false)
      if (!isRefusal(caught)) throw caught
      console.warn(`the opening loan was refused: ${caught.message}`)
      setRejection(OPENING_AMOUNT_INVALID)
    }
  }

  const loanId = `${id}-loan`
  const priceId = `${id}-price`
  const capitalId = `${id}-capital`
  return (
    <form
      className="bubble bubble-assistant bubble-question opening-card"
      noValidate
      onSubmit={(event) => void submit(event)}
    >
      <p className="question-label">{OPENING_TITLE}</p>

      <div className="opening-panel">
        <fieldset className="opening-row">
          <legend>{OPENING_PURPOSE_LABEL}</legend>
          <span className="opening-choices">
            {PURPOSE_CHOICES.map((choice) => (
              <label key={choice} className="opening-choice">
                <input
                  type="radio"
                  name={`${id}-purpose`}
                  checked={purpose === choice}
                  onChange={() => setPurpose(choice)}
                />
                {choice}
              </label>
            ))}
          </span>
        </fieldset>
        {tried && purpose === null && <p className="field-error">{OPENING_PURPOSE_MISSING}</p>}
      </div>

      <div className="opening-panel">
        <fieldset className="opening-row">
          <legend>{OPENING_MODE_LABEL}</legend>
          <span className="opening-choices">
            {(Object.keys(OPENING_MODE) as Mode[]).map((choice) => (
              <label key={choice} className="opening-choice">
                <input
                  type="radio"
                  name={`${id}-mode`}
                  checked={mode === choice}
                  onChange={() => setMode(choice)}
                />
                {OPENING_MODE[choice]}
              </label>
            ))}
          </span>
        </fieldset>

        {mode === 'loan' ? (
          <div className="opening-row">
            <label htmlFor={loanId}>{OPENING_MODE.loan}</label>
            <span className="field-input">
              <GroupedAmountInput id={loanId} value={loanText} onChange={setLoanText} />
              <span className="unit">₪</span>
            </span>
          </div>
        ) : (
          <>
            <div className="opening-row">
              <label htmlFor={priceId}>{OPENING_PRICE_LABEL}</label>
              <span className="field-input">
                <GroupedAmountInput id={priceId} value={priceText} onChange={setPriceText} />
                <span className="unit">₪</span>
              </span>
            </div>
            <div className="opening-row">
              <label htmlFor={capitalId}>{OPENING_CAPITAL_LABEL}</label>
              <span className="field-input">
                <GroupedAmountInput id={capitalId} value={capitalText} onChange={setCapitalText} />
                <span className="unit">₪</span>
              </span>
            </div>
            {amount !== null && <p className="opening-hint">{openingLoanLine(amount)}</p>}
          </>
        )}
        {tried && covers && <p className="field-error">{OPENING_CAPITAL_COVERS}</p>}
        {tried && !covers && !amountValid && (
          <p className="field-error">{OPENING_AMOUNT_INVALID}</p>
        )}
        {rejection !== null && <p className="field-error">{rejection}</p>}
      </div>

      <div className="question-actions">
        <button type="submit" className="primary" disabled={busy}>
          {CONTINUE}
        </button>
      </div>
    </form>
  )
}
