/**
 * The reference case as check events. Only `optionPrime36`, `optionFixed36` and
 * `recommendationPrime` carry figures from an engine run; the other options are hand-made.
 */
import type {
  AwaitingOffer,
  ChartShown,
  ScenarioShown,
  CheckEvent,
  Finances,
  LoanRequest,
  LoanSimulation,
  OfferIdentified,
  OptionPrice,
  OptionSaved,
  Question,
  Reading,
  ReadingKind,
  RecommendationPresented,
  Track,
  TrackSimulation,
} from '../api/types.ts'

type EventOf<Type extends CheckEvent['type']> = Extract<CheckEvent, { type: Type }>

export function withSeq<E extends CheckEvent>(event: E, seq: number): E {
  return { ...event, seq }
}

export function userMessage(seq: number, text: string): EventOf<'message.user'> {
  return { type: 'message.user', data: { text }, seq }
}

export function assistantMessage(
  seq: number,
  message_id: string,
  text: string,
): EventOf<'message.assistant'> {
  return { type: 'message.assistant', data: { message_id, text }, seq }
}

export function delta(message_id: string, text: string): EventOf<'message.delta'> {
  return { type: 'message.delta', data: { message_id, text }, seq: null }
}

export function turnStatus(seq: number, status: 'idle' | 'running'): EventOf<'turn.status'> {
  return { type: 'turn.status', data: { status }, seq }
}

export function turnFailed(seq: number, message: string): EventOf<'turn.failed'> {
  return { type: 'turn.failed', data: { message }, seq }
}

export function questionAsked(
  seq: number,
  question: Question,
  lead_in: string | null = null,
): EventOf<'question.asked'> {
  return { type: 'question.asked', data: { question, lead_in }, seq }
}

export const cpiChart: ChartShown = {
  series: 'cpi',
  as_of: '2026-09-01',
  points: [
    { month: '2026-07-01', value: '0.3' },
    { month: '2026-08-01', value: '0.7' },
    { month: '2026-09-01', value: '-0.5' },
  ],
}

export function chartShown(seq: number, chart: ChartShown = cpiChart): EventOf<'chart.shown'> {
  return { type: 'chart.shown', data: chart, seq }
}

export const loan: LoanRequest = {
  purpose: 'רכב',
  amount: '29000',
}

export const finances: Finances = {
  net_fixed_income: '9300',
  fixed_expenses: '4500',
}

export const loanSet: EventOf<'loan.set'> = {
  type: 'loan.set',
  data: loan,
  seq: 3,
}

export const termSet: EventOf<'term.set'> = {
  type: 'term.set',
  data: { term_months: 36 },
  seq: 3,
}

export const ceilingSet: EventOf<'ceiling.set'> = {
  type: 'ceiling.set',
  data: { payment_ceiling: '1900', ceiling_source: 'stated' },
  seq: 3,
}

export const financesUpdated: EventOf<'finances.updated'> = {
  type: 'finances.updated',
  data: { finances, missing: [], payment_ceiling: '1900', ceiling_source: 'finances' },
  seq: 2,
}

const RATES_AS_OF = '2026-10-28'
const CPI_AS_OF = '2026-09-01'

interface OptionSpec {
  option_id: string
  source: OptionSaved['source']
  lender: string | null
  offer_date: string | null
  max_term_months?: number
  track: Track
  simulation: Omit<TrackSimulation, 'schedule' | 'balloon_due'> & {
    balloon_due?: string | null
  }
  price?: OptionPrice
  seq: number
}

function savedOption(spec: OptionSpec): EventOf<'option.saved'> {
  const track: TrackSimulation = {
    balloon_due: null,
    ...spec.simulation,
    schedule: [],
  }
  const result: LoanSimulation = {
    tracks: [track],
    first_payment: track.first_payment,
    max_base_payment: track.max_base_payment,
    total_paid: track.total_paid,
    rate_as_of: RATES_AS_OF,
    cpi_as_of: CPI_AS_OF,
  }
  const data: OptionSaved = {
    option_id: spec.option_id,
    loan: { tracks: [spec.track] },
    source: spec.source,
    lender: spec.lender,
    offer_date: spec.offer_date,
    max_term_months: spec.max_term_months ?? null,
    figures: {
      first_payment: track.first_payment,
      peak_payment: track.max_base_payment,
      worst_peak_payment: track.worst?.max_payment ?? null,
      worst_start: track.worst?.start ?? null,
      worst_end: track.worst?.end ?? null,
      balloon_due: track.balloon_due,
      total_paid: track.total_paid,
      rate_as_of: RATES_AS_OF,
      cpi_as_of: CPI_AS_OF,
      price: spec.price ?? null,
    },
    result,
  }
  return { type: 'option.saved', data, seq: spec.seq }
}

const primeTrack: Track = {
  principal: '29000.00',
  term_months: 36,
  rate_kind: 'prime',
  annual_rate: null,
  prime_spread: '-0.5',
  cpi_linked: false,
  method: 'spitzer',
}

export const optionPrime36 = savedOption({
  option_id: 'prime-36',
  source: 'example',
  lender: null,
  offer_date: null,
  track: primeTrack,
  seq: 4,
  simulation: {
    first_payment: '904.08',
    max_base_payment: '904.08',
    total_paid: '32546.86',
    worst: {
      start: '2022-04-01',
      end: '2025-03-01',
      max_payment: '955.37',
      balloon_due: null,
      total_paid: '34025.57',
    },
    max_payment_range: { low: '861.20', high: '955.37' },
    total_paid_range: { low: '32432.14', high: '34025.57' },
    windows: 85,
  },
})

const fixedTrack: Track = {
  principal: '29000.00',
  term_months: 36,
  rate_kind: 'fixed',
  annual_rate: '6.9',
  prime_spread: null,
  cpi_linked: false,
  method: 'spitzer',
}

export const optionFixed36 = savedOption({
  option_id: 'fixed-36',
  source: 'example',
  lender: null,
  offer_date: null,
  track: fixedTrack,
  seq: 5,
  simulation: {
    first_payment: '907.42',
    max_base_payment: '907.42',
    total_paid: '32667.03',
    worst: null,
    max_payment_range: null,
    total_paid_range: null,
    windows: 0,
  },
})

export const optionOfferFixed = savedOption({
  option_id: 'offer-hapoalim',
  source: 'offer',
  lender: 'בנק הפועלים',
  offer_date: '2026-11-02',
  track: fixedTrack,
  seq: 7,
  price: {
    rate_today: '6.9',
    against_market: 'below',
    market_rate: '7.9',
    market_rate_month: '2026-08-01',
  },
  simulation: {
    first_payment: '890.00',
    max_base_payment: '890.00',
    total_paid: '32040.00',
    worst: null,
    max_payment_range: null,
    total_paid_range: null,
    windows: 0,
  },
})

export const optionBalloon = savedOption({
  option_id: 'balloon-36',
  source: 'example',
  lender: null,
  offer_date: null,
  track: { ...primeTrack, method: 'balloon', balloon_amount: '10000' },
  seq: 8,
  simulation: {
    first_payment: '640.50',
    max_base_payment: '640.50',
    balloon_due: '10000',
    total_paid: '33058.00',
    worst: {
      start: '2022-04-01',
      end: '2025-03-01',
      max_payment: '688.30',
      balloon_due: '10000',
      total_paid: '34780.00',
    },
    max_payment_range: { low: '610.40', high: '688.30' },
    total_paid_range: { low: '32910.00', high: '34780.00' },
    windows: 85,
  },
})

export const recommendationPrime: EventOf<'recommendation.presented'> = {
  type: 'recommendation.presented',
  seq: 6,
  data: {
    loan_amount: '29000.00',
    payment_ceiling: '1900.00',
    ceiling_source: 'stated',
    checked: true,
    preferred: optionPrime36.data,
    alternative: optionFixed36.data,
    reasoning: 'ריבית פריים עם מרווח שלילי זולה יותר, והתשלום הגרוע ביותר נשאר מתחת לתקרה.',
  } satisfies RecommendationPresented,
}

/** The card's decision sentence for `recommendationPrime`; its last month follows the date the
 * test runs on. */
export const REFERENCE_DECISION =
  /^הלוואה של 29,000 ₪ ל-36 חודשים \(עד \d{2}\/\d{4}\), כ-904 ₪ בחודש\.$/

export function examplesRemoved(
  seq: number,
  option_ids: string[],
  recommendation_removed: boolean,
): EventOf<'examples.removed'> {
  return { type: 'examples.removed', data: { option_ids, recommendation_removed }, seq }
}

export function checkArchived(seq: number): EventOf<'check.archived'> {
  return {
    type: 'check.archived',
    data: { archived_at: '2026-11-14T09:30:00+00:00' },
    seq,
  }
}

const AVIS_TRACK: Track = {
  principal: '45000',
  term_months: 60,
  rate_kind: 'fixed',
  annual_rate: '10.58',
  prime_spread: null,
  cpi_linked: false,
  method: 'spitzer',
}

/** An offer of 45,000 over 60 months known by its payment alone, so the readings are the fixed
 * rate that gives 969, the matching prime margin and the same rate linked to the index. */
export const awaitingAvis: AwaitingOffer = {
  awaiting_id: 'a-1',
  lender: 'סוכנות אוויס רכבים',
  amount: '45000',
  term_months: 60,
  monthly_payment: '969',
  payment_rate: '10.58',
  type_words: [],
  readings: [
    {
      kind: 'fixed_unlinked',
      track: AVIS_TRACK,
      first_payment: '969',
      total_rate: '10.58',
      approximate: false,
    },
    {
      kind: 'prime_margin',
      track: { ...AVIS_TRACK, rate_kind: 'prime', annual_rate: null, prime_spread: '5.83' },
      first_payment: '969',
      total_rate: '10.58',
      approximate: false,
    },
    {
      kind: 'fixed_linked',
      track: { ...AVIS_TRACK, cpi_linked: true },
      first_payment: '969',
      total_rate: '10.58',
      approximate: true,
    },
  ],
  likely: null,
  identified: false,
  prime: '4.75',
  rate_as_of: '2026-11-15',
}

/** An offer of prime + 6.45 quoted on 20,000 that the check prices on its 45,000 loan. */
export const identifiedMax: OfferIdentified = {
  option_id: 'offer-max',
  lender: 'מקס',
  reading: {
    kind: 'prime_margin',
    track: { ...AVIS_TRACK, rate_kind: 'prime', annual_rate: null, prime_spread: '6.45' },
    first_payment: '934',
    total_rate: '11.2',
    approximate: false,
  },
  prime: '4.75',
  rate_as_of: '2026-11-15',
  monthly_payment: '934',
  quoted_amount: '20000',
  loan_amount: '45000',
}

/** Max's prime + 6.45 at 934 a month, identified on its 20,000 and awaiting Max's answer on a
 * check whose loan is larger. */
export const awaitingMaxShort: AwaitingOffer = {
  awaiting_id: 'a-max',
  lender: 'מקס',
  amount: '20000',
  term_months: 24,
  monthly_payment: '934',
  payment_rate: '11.17',
  type_words: ['prime'],
  readings: [identifiedMax.reading],
  likely: null,
  identified: true,
  prime: '4.75',
  rate_as_of: '2026-11-15',
}

export function offerDropped(
  seq: number,
  offer: AwaitingOffer,
  loanAmount: string,
): EventOf<'offer.dropped'> {
  return {
    type: 'offer.dropped',
    data: {
      awaiting_id: offer.awaiting_id,
      lender: offer.lender,
      quoted_amount: offer.amount,
      loan_amount: loanAmount,
    },
    seq,
  }
}

export function offerAwaiting(seq: number, offer: AwaitingOffer): EventOf<'offer.awaiting'> {
  return { type: 'offer.awaiting', data: offer, seq }
}

export function offerIdentified(seq: number, offer: OfferIdentified): EventOf<'offer.identified'> {
  return { type: 'offer.identified', data: offer, seq }
}

export function offerUnrecognized(
  seq: number,
  lender: string | null,
): EventOf<'offer.unrecognized'> {
  return { type: 'offer.unrecognized', data: { lender }, seq }
}

export function offerSettled(
  seq: number,
  awaiting_id: string,
  reading: Reading,
): EventOf<'offer.settled'> {
  return { type: 'offer.settled', data: { awaiting_id, kind: reading.kind, reading }, seq }
}

/** The reading of the given kind on Avis's card. */
export function avisReading(kind: ReadingKind): Reading {
  const reading = awaitingAvis.readings.find((r) => r.kind === kind)
  if (reading === undefined) throw new Error(`Avis's card has no ${kind} reading`)
  return reading
}

/** Two offers in a scenario of the index rising 5% a year with prime unchanged: Bank Hapoalim's
 * fixed-rate offer, which the scenario moves, and a second lender's prime offer, which it does
 * not. */
export const scenarioCpi5: ScenarioShown = {
  scenario: {
    cpi_per_year: '5',
    prime_per_year: '0',
    cpi_like_last_years: null,
    prime_like_last_years: null,
  },
  named: ['cpi_per_year'],
  rows: [
    {
      option_id: 'offer-hapoalim',
      source: 'offer',
      lender: 'בנק הפועלים',
      offer_date: '2026-11-02',
      loan: optionOfferFixed.data.loan,
      scenario: { first_payment: '1800.00', max_payment: '2210.40', total_paid: '121004.50' },
      today: { max_payment: '1985.20', total_paid: '113424.00' },
    },
    {
      option_id: 'prime-36',
      source: 'offer',
      lender: 'פריסבי',
      offer_date: '2026-11-02',
      loan: optionPrime36.data.loan,
      scenario: { first_payment: '1899.00', max_payment: '1899.00', total_paid: '113916.00' },
      today: { max_payment: '1899.00', total_paid: '113916.00' },
    },
  ],
}

export function scenarioShown(
  seq: number,
  scenario: ScenarioShown = scenarioCpi5,
): EventOf<'scenario.shown'> {
  return { type: 'scenario.shown', data: scenario, seq }
}

