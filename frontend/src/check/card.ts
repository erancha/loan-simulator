/**
 * Maps a check's stored engine results to the recommendation card the page renders.
 *
 * Every number on the card is read from an option's stored figures and simulation, or from the
 * recommendation's engine-computed bounds and sizing; none comes from the model's text.
 */
import type { OptionSaved, Track } from '../api/types.ts'
import {
  decimalText,
  formatDate,
  formatMonth,
  formatShekelRange,
  formatShekels,
  formatYearRange,
  isZero,
} from '../money.ts'
import {
  CHIP_UNCHANGING,
  CPI_LINKED,
  CUSHION_TEXT,
  HISTORY_LINE,
  LABEL_ALTERNATIVE,
  LABEL_PREFERRED,
  METHOD,
  OTHERS_TITLE,
  PUBLISHED_RATE_LINE,
  RATE_KIND,
  REASON_SENTENCES,
  SOURCE_PUBLISHED_AVERAGE,
  SPITZER_MOVING,
  balloonLine,
  chipText,
  dataDatesLine,
  decisionText,
  offerSource,
  termText,
  totalRangeText,
} from './copy.ts'
import type { CheckState } from './events.ts'

export interface OptionCard {
  id: string
  label: typeof LABEL_PREFERRED | typeof LABEL_ALTERNATIVE | null
  track: string
  source: string
  isExample: boolean
  paymentToday: string
  chip: { tone: 'green'; text: typeof CHIP_UNCHANGING } | { tone: 'amber'; text: string }
  balloon: string | null
  totalToday: string
  totalRange: string | null
}

export interface CardModel {
  decision: string | null
  /** The preferred option, then the alternative when there is one. */
  recommended: OptionCard[]
  others: { title: string; options: OptionCard[] } | null
  reasoning: string | null
  fold: {
    ceiling: { amount: string; reasons: string[] }
    cushion: { amount: string; text: string }
    assumptions: string[]
  } | null
}

const MINUS = '−'

/** A prime spread as " + 0.5%" or " − 0.5%"; empty when the spread is absent or zero. */
function spreadText(spread: Track['prime_spread']): string {
  if (spread === null) return ''
  const text = String(spread)
  const negative = text.startsWith('-')
  const magnitude = decimalText(negative ? text.slice(1) : text)
  if (isZero(magnitude)) return ''
  return ` ${negative ? MINUS : '+'} ${magnitude}%`
}

function trackText(track: Track): string {
  let rate: string
  if (track.rate_kind === 'prime') {
    rate = `${RATE_KIND.prime}${spreadText(track.prime_spread)}`
  } else {
    if (track.annual_rate === null) throw new Error('a fixed track has no annual_rate')
    rate = `${RATE_KIND.fixed} ${decimalText(track.annual_rate)}%`
  }
  const prime = track.rate_kind === 'prime'
  let method: string = METHOD[track.method]
  if (track.method === 'spitzer' && (prime || track.cpi_linked)) {
    method = SPITZER_MOVING[prime && track.cpi_linked ? 'both' : prime ? 'rate' : 'index']
  }
  const parts = [rate, method, termText(track.term_months)]
  if (track.cpi_linked) parts.push(CPI_LINKED)
  return parts.join(', ')
}

function chipOf(option: OptionSaved, track: Track): OptionCard['chip'] {
  const { worst_peak_payment: peak, worst_start: start, worst_end: end } = option.figures
  if (peak === null) return { tone: 'green', text: CHIP_UNCHANGING }
  if (start === null || end === null) {
    throw new Error(`option ${option.option_id} has a worst payment but no worst window`)
  }
  if (track.rate_kind !== 'prime' && !track.cpi_linked) {
    throw new Error(`option ${option.option_id} is a fixed unlinked track with a worst window`)
  }
  const text = chipText(
    formatShekels(peak, { approx: true }),
    formatYearRange(start, end),
    { prime: track.rate_kind === 'prime', cpiLinked: track.cpi_linked },
  )
  return { tone: 'amber', text }
}

function totalRangeOf(option: OptionSaved): string | null {
  const simulated = option.result.tracks[0]
  if (simulated.total_paid_range === null) return null
  const { low, high } = simulated.total_paid_range
  return totalRangeText(formatShekelRange(low, high), simulated.windows)
}

function sourceOf(option: OptionSaved): string {
  if (option.source === 'published_average') return SOURCE_PUBLISHED_AVERAGE
  const date = option.offer_date === null ? null : formatDate(option.offer_date)
  return offerSource(option.lender, date)
}

function optionCard(option: OptionSaved, label: OptionCard['label']): OptionCard {
  const track = option.loan.tracks[0]
  return {
    id: option.option_id,
    label,
    track: trackText(track),
    source: sourceOf(option),
    isExample: option.source === 'published_average',
    paymentToday: formatShekels(option.figures.first_payment),
    chip: chipOf(option, track),
    balloon:
      option.figures.balloon_due === null ? null : balloonLine(formatShekels(option.figures.balloon_due)),
    totalToday: formatShekels(option.figures.total_paid),
    totalRange: totalRangeOf(option),
  }
}

function storedOption(state: CheckState, id: string): OptionSaved {
  const option = state.options.get(id)
  if (option === undefined) throw new Error(`recommended option ${id} is not among the saved options`)
  return option
}

function reasonSentence(code: string): string {
  const sentence = REASON_SENTENCES[code]
  if (sentence === undefined) throw new Error(`no sentence for reason code ${code}`)
  return sentence
}

function assumptionsOf(dated: OptionSaved, shown: OptionSaved[]): string[] {
  const lines = [dataDatesLine(formatDate(dated.figures.rate_as_of), formatMonth(dated.figures.cpi_as_of))]
  if (shown.some((o) => o.source === 'published_average')) lines.push(PUBLISHED_RATE_LINE)
  lines.push(HISTORY_LINE)
  return lines
}

function othersTitle(state: CheckState, ids: string[]): string {
  if (state.recommendation === null) return OTHERS_TITLE.checked
  return ids.every((id) => state.optionsSinceRecommendation.includes(id))
    ? OTHERS_TITLE.newSinceRecommendation
    : OTHERS_TITLE.further
}

export function buildCard(state: CheckState): CardModel {
  const recommendation = state.recommendation
  const named: Array<{ option: OptionSaved; label: OptionCard['label'] }> = []
  if (recommendation !== null) {
    named.push({ option: storedOption(state, recommendation.preferred.option_id), label: LABEL_PREFERRED })
    if (recommendation.alternative !== null) {
      named.push({
        option: storedOption(state, recommendation.alternative.option_id),
        label: LABEL_ALTERNATIVE,
      })
    }
  }
  const namedIds = named.map(({ option }) => option.option_id)
  const otherOptions = [...state.options.values()].filter((o) => !namedIds.includes(o.option_id))
  const shown = [...named.map(({ option }) => option), ...otherOptions]

  const others =
    otherOptions.length === 0
      ? null
      : {
          title: othersTitle(
            state,
            otherOptions.map((o) => o.option_id),
          ),
          options: otherOptions.map((o) => optionCard(o, null)),
        }
  const recommendedCards = named.map(({ option, label }) => optionCard(option, label))

  if (recommendation === null) {
    return { decision: null, recommended: [], others, reasoning: null, fold: null }
  }

  const preferred = named[0].option
  const { bounds, sizing } = recommendation
  return {
    decision: decisionText(
      formatShekels(sizing.loan_amount),
      preferred.loan.tracks[0].term_months,
      formatShekels(preferred.figures.first_payment),
      formatShekels(sizing.cushion_kept),
      isZero(sizing.spare_savings) ? null : formatShekels(sizing.spare_savings),
    ),
    recommended: recommendedCards,
    others,
    reasoning: recommendation.reasoning,
    fold: {
      ceiling: { amount: formatShekels(bounds.payment_ceiling), reasons: bounds.reasons.map(reasonSentence) },
      cushion: { amount: formatShekels(bounds.min_cushion), text: CUSHION_TEXT },
      assumptions: assumptionsOf(preferred, shown),
    },
  }
}
