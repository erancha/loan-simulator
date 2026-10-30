import type { OptionCard } from './card.ts'
import { CHIP_EXAMPLE, LABEL_PREFERRED, monthlyPayment } from './copy.ts'

/**
 * One saved option: its label when recommended, a chip when it is only an example, the track,
 * today's payment and the chip about how that payment can move.
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
      {option.isExample && <span className="chip chip-example">{CHIP_EXAMPLE}</span>}
      <p className="option-track">{option.track}</p>
      <p className="option-source">{option.source}</p>
      <p className="option-payment">{monthlyPayment(option.paymentToday)}</p>
      <span className={`chip chip-${option.chip.tone}`}>{option.chip.text}</span>
      {option.balloon !== null && <p className="option-balloon">{option.balloon}</p>}
    </article>
  )
}
