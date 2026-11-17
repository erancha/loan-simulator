import type { OptionCard } from './card.ts'
import { CHIP_EXAMPLE, LABEL_PREFERRED, monthlyPayment } from './copy.ts'
import { withValues } from './emphasis.tsx'

/** The chip that marks an option nobody can take, on its card and on its row of the totals. */
export function ExampleChip() {
  return <span className="chip chip-example">{CHIP_EXAMPLE}</span>
}

/**
 * One saved option: its label when recommended, a chip when it is only an example, the track,
 * today's payment, a real offer's price under it, and the chip about how that payment can move.
 * Its figures take the colour of a value, as in the conversation.
 */
export function OptionCardView({ option }: { option: OptionCard }) {
  const className = [
    'option',
    ...(option.label === LABEL_PREFERRED ? ['option-preferred'] : []),
    ...(option.isExample ? ['option-example'] : []),
  ].join(' ')
  return (
    <article className={className}>
      {option.label !== null && <span className="option-label">{option.label}</span>}
      {option.isExample && <ExampleChip />}
      <p className="option-track">{withValues(option.track)}</p>
      <p className="option-source">{option.source}</p>
      {option.termNote !== null && <p className="option-source">{withValues(option.termNote)}</p>}
      <p className="option-payment">{withValues(monthlyPayment(option.paymentToday))}</p>
      {option.price !== null && <p className="option-price">{withValues(option.price.interest)}</p>}
      {option.price !== null && option.price.rate !== null && (
        <p className="option-price">{withValues(option.price.rate)}</p>
      )}
      <span className={`chip chip-${option.chip.tone}`}>{option.chip.text}</span>
      {option.balloon !== null && <p className="option-balloon">{option.balloon}</p>}
    </article>
  )
}
