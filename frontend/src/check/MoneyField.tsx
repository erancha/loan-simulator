import { useState } from 'react'
import { formatAmount, groupTypedAmount, normaliseMoneyInput } from '../money.ts'
import { GroupedAmountInput } from './GroupedAmountInput.tsx'
import { NOT_COUNTED_YET } from './copy.ts'
import { FieldHint } from './FieldHint.tsx'
import { rejectionText } from './rejection.ts'

/** The field's classes: a dashed outline while missing, a flash while the chat just filled it. */
export function fieldClass(missing: boolean, changed: boolean): string {
  return ['field', missing && 'missing', changed && 'changed'].filter(Boolean).join(' ')
}

interface Props {
  id: string
  label: string
  /** Shown on hover over the whole field. */
  title?: string
  hint: string
  value: string | null
  missing: boolean
  /** The chat just filled this field; it flashes once. */
  changed: boolean
  disabled?: boolean
  /** Saves the normalised amount; rejects with an ApiException when the server refuses it. */
  onCommit: (amount: string) => Promise<void>
}

/** A shekel input that groups its digits by thousands, at rest and while edited. */
export function MoneyField({
  id,
  label,
  title,
  hint,
  value,
  missing,
  changed,
  disabled,
  onCommit,
}: Props) {
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
        <GroupedAmountInput
          id={id}
          aria-describedby={`${id}-hint`}
          disabled={disabled}
          placeholder={NOT_COUNTED_YET}
          value={draft ?? (value === null ? '' : formatAmount(value))}
          onFocus={() =>
            setDraft((current) => current ?? (value === null ? '' : groupTypedAmount(value)))
          }
          onChange={setDraft}
          onBlur={(event) => void commit(event.target.value)}
        />
        <span className="unit">₪</span>
      </span>
      {error !== null && <p className="field-error">{error}</p>}
    </div>
  )
}
