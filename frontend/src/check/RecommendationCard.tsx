import { useId } from 'react'
import type { CardModel, OptionCard } from './card.ts'
import {
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
import { ExampleChip, OptionCardView } from './OptionCardView.tsx'

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

/** The figures behind the recommendation; open when it first renders, closable by the person. */
function Fold({ fold, options }: FoldProps) {
  return (
    <details className="fold" open>
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
                {option.track}
                <span className="option-source totals-source">{option.source}</span>
              </th>
              <td>{option.totalToday}</td>
              <td>{option.totalRange === null ? NO_RANGE : option.totalRange}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="assumptions">
        {fold.assumptions.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </details>
  )
}

/**
 * The recommendation card: the decision with its ceiling check, the options grouped by the latest
 * recommendation, the model's reasoning and the fold with the figures behind them.
 */
export function RecommendationCard({ model }: { model: CardModel }) {
  const { decision, checkNote, ceiling, recommended, others, reasoning, fold } = model
  if (recommended.length === 0 && others === null) {
    return <p className="card-empty">{EMPTY_CARD}</p>
  }
  const shown = others === null ? recommended : [...recommended, ...others.options]
  return (
    <div className="card">
      {decision !== null && (
        <section className="decision">
          <h3 className="decision-title">{DECISION_TITLE}</h3>
          <p>{decision}</p>
          {checkNote !== null && <p className="check-note">{checkNote}</p>}
          <p className="ceiling-line">
            {ceiling.label}: {ceiling.amount}
            {ceiling.source !== null && ` · ${ceiling.source}`}
          </p>
        </section>
      )}
      {shown.some((option) => option.isExample) && <p className="examples-note">{EXAMPLES_NOTE}</p>}
      {recommended.map((option) => (
        <OptionCardView key={option.id} option={option} />
      ))}
      {others !== null && <OthersGroup title={others.title} options={others.options} />}
      {reasoning !== null && <p className="reasoning">{reasoning}</p>}
      {decision !== null && (
        <section className="next-step">
          <h3 className="decision-title">{NEXT_STEP_TITLE}</h3>
          <p>{NEXT_STEP}</p>
          <p>{OFFER_DETAILS}</p>
        </section>
      )}
      {fold !== null && <Fold fold={fold} options={shown} />}
    </div>
  )
}
