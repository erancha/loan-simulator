import { useState } from 'react'
import { HINT_LABEL } from './copy.ts'

interface Props {
  /** The id the field points its aria-describedby at, so a screen reader reads the hint too. */
  id: string
  text: string
}

/**
 * A small i beside a field's label that shows what goes in the field: on hover and keyboard focus
 * through CSS, and on tap through state, since a touch screen has neither.
 */
export function FieldHint({ id, text }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <span className="hint">
      <button
        type="button"
        className="hint-button"
        aria-label={HINT_LABEL}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => event.key === 'Escape' && setOpen(false)}
      >
        i
      </button>
      <span id={id} role="tooltip" className={open ? 'hint-text open' : 'hint-text'}>
        {text}
      </span>
    </span>
  )
}
