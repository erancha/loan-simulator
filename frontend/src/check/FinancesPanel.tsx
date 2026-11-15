import { useState } from 'react'
import type { CeilingSource, Finances } from '../api/types.ts'
import { formatShekels } from '../money.ts'
import type { Answer } from './QuestionBubble.tsx'
import {
  CEILING_LABEL,
  EDIT_FINANCES,
  EXPENSES_HINT,
  EXPENSES_LABEL,
  INCOME_HINT,
  INCOME_LABEL,
  NOT_COUNTED_YET,
  updateLine,
} from './copy.ts'
import { MoneyField } from './MoneyField.tsx'

interface Props {
  finances: Finances
  ceiling: { amount: string; source: CeilingSource } | null
  /** A turn is running or the check is archived: the figures show but cannot be saved. */
  readOnly: boolean
  /** Saves the update, then sends the line; rejects when the server refuses the save. */
  onAnswer: (answer: Answer) => Promise<boolean>
}

const FIELDS = [
  { key: 'net_fixed_income', label: INCOME_LABEL, hint: INCOME_HINT },
  { key: 'fixed_expenses', label: EXPENSES_LABEL, hint: EXPENSES_HINT },
] as const

/** The check has figures only once the person took the help path for the payment ceiling. */
export function hasFinances(finances: Finances): boolean {
  return finances.net_fixed_income !== null || finances.fixed_expenses !== null
}

/**
 * The check's two finances figures as one summary line, with the ceiling they give when the
 * check's ceiling comes from them; an edit link opens the two fields in place.
 */
export function FinancesPanel({ finances, ceiling, readOnly, onAnswer }: Props) {
  const [editing, setEditing] = useState(false)
  const open = editing && !readOnly
  return (
    <section className="finances-panel" aria-label={`${INCOME_LABEL} ו${EXPENSES_LABEL}`}>
      <p className="finances-summary">
        {FIELDS.map(({ key, label }) => (
          <span key={key}>
            {label}{' '}
            <b>{finances[key] === null ? NOT_COUNTED_YET : formatShekels(finances[key])}</b>
          </span>
        ))}
        {ceiling !== null && ceiling.source === 'finances' && (
          <span>
            {CEILING_LABEL} <b>{formatShekels(ceiling.amount)}</b>
          </span>
        )}
        {!readOnly && (
          <button
            type="button"
            className="link-button"
            aria-expanded={open}
            onClick={() => setEditing(!editing)}
          >
            {EDIT_FINANCES}
          </button>
        )}
      </p>
      {open && (
        <div className="finances-fields">
          {FIELDS.map(({ key, label, hint }) => (
            <MoneyField
              key={key}
              id={`finances-${key}`}
              label={label}
              hint={hint}
              value={finances[key]}
              missing={false}
              changed={false}
              onCommit={async (amount) => {
                await onAnswer({ line: updateLine(label, amount), update: { [key]: amount } })
              }}
            />
          ))}
        </div>
      )}
    </section>
  )
}
