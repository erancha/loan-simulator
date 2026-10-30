import { useState } from 'react'
import { formatAmount, normaliseMoneyInput } from '../money.ts'
import { NOT_COUNTED_YET } from './copy.ts'
import { FieldHint } from './FieldHint.tsx'
import { fieldClass } from './ProfilePanel.tsx'
import { rejectionText } from './rejection.ts'

interface Props {
  id: string
  label: string
  /** Shown on hover over the whole field. */
  title: string | undefined
  hint: string
  value: string | null
  missing: boolean
  /** The chat just filled this field; it flashes once. */
  changed: boolean
  /** Saves the normalised amount; rejects with an ApiException when the server refuses it. */
  onCommit: (amount: string) => Promise<void>
}

/** A shekel input that shows grouped digits at rest and the typed text while editing. */
export function MoneyField({ id, label, title, hint, value, missing, changed, onCommit }: Props) {
  // null while the field shows the stored value; a string while the person's text is kept.
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function commit(text: string) {
    try {
      const amount = normaliseMoneyInput(text)
      if (amount !== null && amount !== value) await onCommit(amount)
      setDraft(null)
      setError(null)
    } catch (caught) {
      setError(rejectionText(caught))
    }
  }

  return (
    <div className={fieldClass(missing, changed)} title={title}>
      <span className="field-head">
        <label htmlFor={id}>{label}</label>
        <FieldHint id={`${id}-hint`} text={hint} />
      </span>
      <span className="field-input">
        <input
          id={id}
          aria-describedby={`${id}-hint`}
          type="text"
          inputMode="decimal"
          placeholder={NOT_COUNTED_YET}
          value={draft ?? (value === null ? '' : formatAmount(value))}
          onFocus={() => setDraft((current) => current ?? value ?? '')}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={(event) => void commit(event.target.value)}
        />
        <span className="unit">₪</span>
      </span>
      {error !== null && <p className="field-error">{error}</p>}
    </div>
  )
}
