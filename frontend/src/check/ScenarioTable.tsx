import { useId } from 'react'
import type { ScenarioShown } from '../api/types.ts'
import { exceeds, formatShekels } from '../money.ts'
import { optionName } from './card.ts'
import { SCENARIO_HEADINGS, SCENARIO_SAME, scenarioTitle } from './copy.ts'
import { withValues } from './emphasis.tsx'
import { OptionLender } from './OptionCardView.tsx'

/**
 * A scenario's figure beside today's: in red when higher, in green when lower, and only the
 * unchanged mark when it rounds to the same shekel, since repeating the number says nothing.
 */
function ScenarioCell({ today, scenario }: { today: string; scenario: string }) {
  const shown = formatShekels(scenario)
  if (shown === formatShekels(today)) {
    return (
      <td className="scenario-same">
        <span role="img" aria-label={SCENARIO_SAME.label}>
          {SCENARIO_SAME.mark}
        </span>
      </td>
    )
  }
  return (
    <td className={exceeds(scenario, today) ? 'scenario-higher' : 'scenario-lower'}>{shown}</td>
  )
}

interface Props {
  scenario: ScenarioShown
  onShowOption: (optionId: string) => void
}

/**
 * Every saved option priced on a future the person named, as a table in the conversation: its
 * name as its card shows it, then its highest payment and its total, each today and on the
 * scenario. The title names the scenario, so its figures are never read as the options' own. A
 * narrow screen names an option by its lender alone, the full track on its title. A real offer's
 * lender chip opens that offer's card.
 */
export function ScenarioTable({ scenario, onShowOption }: Props) {
  const titleId = useId()
  return (
    <div className="bubble bubble-assistant scenario">
      <p id={titleId} className="scenario-title">
        {withValues(scenarioTitle(scenario.scenario))}
      </p>
      <table className="totals" aria-labelledby={titleId}>
        <thead>
          <tr>
            <th scope="col" rowSpan={2}>
              {SCENARIO_HEADINGS.option}
            </th>
            <th scope="colgroup" colSpan={2}>
              {SCENARIO_HEADINGS.highest}
            </th>
            <th scope="colgroup" colSpan={2}>
              {SCENARIO_HEADINGS.total}
            </th>
          </tr>
          <tr>
            <th scope="col">{SCENARIO_HEADINGS.today}</th>
            <th scope="col">{SCENARIO_HEADINGS.scenario}</th>
            <th scope="col">{SCENARIO_HEADINGS.today}</th>
            <th scope="col">{SCENARIO_HEADINGS.scenario}</th>
          </tr>
        </thead>
        <tbody>
          {scenario.rows.map((row) => {
            const { track, lender } = optionName(row)
            return (
              <tr key={row.option_id}>
                <th scope="row" className="scenario-name" title={`${track}\n${lender}`}>
                  <span className="scenario-track">{withValues(track)}</span>
                  <span className="option-lender totals-lender scenario-lender">
                    <OptionLender
                      lender={lender}
                      isExample={row.source === 'example'}
                      onOpen={() => onShowOption(row.option_id)}
                    />
                  </span>
                </th>
                <td>{formatShekels(row.today.max_payment)}</td>
                <ScenarioCell today={row.today.max_payment} scenario={row.scenario.max_payment} />
                <td>{formatShekels(row.today.total_paid)}</td>
                <ScenarioCell today={row.today.total_paid} scenario={row.scenario.total_paid} />
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
