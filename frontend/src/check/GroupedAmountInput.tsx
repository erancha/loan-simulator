import { type ChangeEvent, type InputHTMLAttributes, useLayoutEffect, useRef } from 'react'
import { groupTypedAmount } from '../money.ts'

/** The box's own attributes besides its text (its label, hint, placeholder, focus handlers). */
type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> & {
  /** The box's text, grouped. */
  value: string
  onChange: (text: string) => void
}

/** Where the caret stands in text after the given number of its characters other than commas. */
function caretAfter(text: string, characters: number): number {
  let seen = 0
  for (let index = 0; index < text.length; index++) {
    if (seen === characters) return index
    if (text[index] !== ',') seen++
  }
  return text.length
}

/**
 * A box for a shekel amount that groups its digits by thousands as the person types. Grouping
 * moves the digits, so the caret is put back after the digit it followed, and an edit in the
 * middle of the amount goes on where the person was typing.
 */
export function GroupedAmountInput({ value, onChange, ...attributes }: Props) {
  const input = useRef<HTMLInputElement>(null)
  // The caret to restore once the grouped text is rendered; null when there is none to restore.
  const caret = useRef<number | null>(null)

  useLayoutEffect(() => {
    if (caret.current === null) return
    if (input.current === null) throw new Error('the amount box renders with its caret')
    input.current.setSelectionRange(caret.current, caret.current)
    caret.current = null
  })

  function change(event: ChangeEvent<HTMLInputElement>) {
    const typed = event.target.value
    const grouped = groupTypedAmount(typed)
    const at = event.target.selectionStart
    // Null only for the kinds of input that have no caret, which a text box is not.
    if (at === null) throw new Error('a text box reports its caret')
    caret.current = caretAfter(grouped, typed.slice(0, at).replace(/,/g, '').length)
    onChange(grouped)
  }

  return (
    <input
      {...attributes}
      ref={input}
      type="text"
      inputMode="decimal"
      dir="ltr"
      value={value}
      onChange={change}
    />
  )
}
