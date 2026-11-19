import { useId } from 'react'
import type { CardModel, OptionCard } from './card.ts'
import {
  AWAITING_ONLY,
  DECISION_TITLE,
  EMPTY_CARD,
  EXAMPLES_NOTE,
  FOLD_TITLE,
  NEXT_STEP,
  NEXT_STEP_TITLE,
  NO_RANGE,
  OFFER_DETAILS,
  TOTALS_HEADINGS,
} from './copy.ts'
import { withValues } from './emphasis.tsx'
import { ExampleChip, OptionCardView, OptionLender } from './OptionCardView.tsx'

function OthersGroup({ title, options }: NonNullable<CardModel['others']>) {
  const titleId = useId()
  return (
    <section className="option-group" aria-labelledby={titleId}>
      <h3 id={titleId} className="option-group-title">
        {title}
      </h3>
      {options.map((option) => (
        <OptionCardView key={option.id} option={option} />
      ))}
    </section>
  )
}

interface FoldProps {
  fold: NonNullable<CardModel['fold']>
  options: OptionCard[]
}

// The card's one table of every option's figures, which a reply's link brings into view.
const FOLD_ID = 'recommendation-figures'

/**
 * Opens the table of the figures behind the recommendation, scrolls it into view and highlights it
 * for a moment. Runs after the pane that holds it is shown, so on a narrow screen it scrolls a
 * visible pane.
 */
export function revealFigures() {
  window.setTimeout(() => {
    const fold = document.getElementById(FOLD_ID)
    if (!(fold instanceof HTMLDetailsElement)) {
      throw new Error('the recommendation card shows no table of figures')
    }
    fold.open = true
    fold.scrollIntoView({ behavior: 'smooth', block: 'start' })
    fold.classList.remove('fold-flash')
    fold.classList.add('fold-flash')
    fold.addEventListener('animationend', () => fold.classList.remove('fold-flash'), {
      once: true,
    })
  }, 0)
}

/** The figures behind the recommendation; open when it first renders, closable by the person. */
function Fold({ fold, options }: FoldProps) {
  return (
    <details id={FOLD_ID} className="fold" open>
      <summary>{FOLD_TITLE}</summary>
      <table className="totals">
        <thead>
          <tr>
            <th scope="col">{TOTALS_HEADINGS.option}</th>
            <th scope="col">{TOTALS_HEADINGS.today}</th>
            <th scope="col">{TOTALS_HEADINGS.range}</th>
          </tr>
        </thead>
        <tbody>
          {options.map((option) => (
            <tr key={option.id}>
              <th scope="row">
                {option.isExample && <ExampleChip />}
                {withValues(option.track)}
                <span className="option-lender totals-lender">
                  <OptionLender lender={option.lender} isExample={option.isExample} />
                </span>
              </th>
              <td>{withValues(option.totalToday)}</td>
              {option.totalRange === null ? (
                <td>{NO_RANGE}</td>
              ) : (
                <td title={option.totalRange.basis}>{withValues(option.totalRange.range)}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="assumptions">
        {fold.assumptions.map((line) => (
          <li key={line}>{withValues(line)}</li>
        ))}
      </ul>
    </details>
  )
}

/**
 * The recommendation card: the decision with its ceiling check, the options grouped by the latest
 * recommendation, a note per offer still awaiting its lender, the model's reasoning and the fold
 * with the figures behind them. While every option is an example, a flashing next step says where
 * to bring real offers from. A check holding only awaiting offers shows a line saying the
 * recommendation follows the lender's answer.
 */
export function RecommendationCard({ model }: { model: CardModel }) {
  const { decision, checkNote, ceiling, recommended, others, awaiting, reasoning, fold } = model
  if (recommended.length === 0 && others === null) {
    if (awaiting.length > 0) return <p className="card-empty">{AWAITING_ONLY}</p>
    return <p className="card-empty">{EMPTY_CARD}</p>
  }
  const shown = others === null ? recommended : [...recommended, ...others.options]
  const showsExamples = shown.some((option) => option.isExample)
  const examplesOnly = shown.every((option) => option.isExample)
  return (
    <div className="card">
      {decision !== null && (
        <section className="decision">
          <h3 className="decision-title">{DECISION_TITLE}</h3>
          <p>{withValues(decision)}</p>
          {checkNote !== null && <p className="check-note">{withValues(checkNote)}</p>}
          <p className="ceiling-line">
            {ceiling.label}: {withValues(ceiling.amount)}
            {ceiling.source !== null && ` · ${ceiling.source}`}
          </p>
        </section>
      )}
      {showsExamples && <p className="examples-note">{EXAMPLES_NOTE}</p>}
      {recommended.map((option) => (
        <OptionCardView key={option.id} option={option} />
      ))}
      {others !== null && <OthersGroup title={others.title} options={others.options} />}
      {awaiting.map((note, i) => (
        <p key={`${i}-${note}`} className="awaiting-note">
          {withValues(note)}
        </p>
      ))}
      {reasoning !== null && <p className="reasoning">{withValues(reasoning)}</p>}
      {decision !== null && examplesOnly && (
        <section className="next-step">
          <h3 className="decision-title attention-flash">
            {NEXT_STEP_TITLE}
          </h3>
          <p>{NEXT_STEP}</p>
          <p>{OFFER_DETAILS}</p>
        </section>
      )}
      {fold !== null && <Fold fold={fold} options={shown} />}
    </div>
  )
}
