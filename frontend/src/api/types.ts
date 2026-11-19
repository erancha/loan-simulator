/** The agent API's JSON shapes. Every money field is a decimal string, never a number. */

export interface User {
  id: string
  email: string | null
  name: string | null
}

/** What the person wants to borrow; the purpose is absent when they named none. */
export interface LoanRequest {
  purpose: string | null
  amount: string
}

/** The two monthly figures of the help path; null until the person gives them. */
export interface Finances {
  net_fixed_income: string | null
  fixed_expenses: string | null
}

export type CeilingSource = 'stated' | 'finances'

/**
 * Engine Track arguments as the agent sent them: numbers or strings. A fee field is absent when the
 * model left it out; the engine then defaults it to 0.
 */
export interface Track {
  principal: string | number
  term_months: number
  rate_kind: 'fixed' | 'prime'
  annual_rate: string | number | null
  prime_spread: string | number | null
  cpi_linked: boolean
  method: 'spitzer' | 'equal_principal' | 'balloon'
  balloon_amount?: string | number
  one_time_fee?: string | number
  monthly_fee?: string | number
}

/** A loan's rate today against the Bank of Israel average rate on new unlinked consumer loans. */
export interface OptionPrice {
  /** Annual percent charged in the first month; on top of the CPI for a CPI-linked loan. */
  rate_today: string
  /** Similar within the engine's band of percentage points; null for a CPI-linked loan, whose
   * rate is not comparable with the unlinked average. */
  against_market: 'above' | 'similar' | 'below' | null
  market_rate: string
  market_rate_month: string
}

export interface OptionFigures {
  first_payment: string
  peak_payment: string
  worst_peak_payment: string | null
  worst_start: string | null
  worst_end: string | null
  balloon_due: string | null
  total_paid: string
  rate_as_of: string
  cpi_as_of: string
  /** Absent from an option.saved event stored before the engine reported the rates, and null
   * for an option saved then; the card then shows no rate line. */
  price?: OptionPrice | null
}

export interface OptionData {
  option_id: string
  /** The engine's Loan arguments as the agent sent them, not a normalised record. */
  loan: { tracks: Track[] }
  source: 'example' | 'offer'
  lender: string | null
  offer_date: string | null
  /** The longest term a real offer allows, when it leaves the term open. */
  max_term_months: number | null
  figures: OptionFigures
}

export interface TrackSimulation {
  first_payment: string
  max_base_payment: string
  balloon_due: string | null
  total_paid: string
  worst: {
    start: string
    end: string
    max_payment: string
    balloon_due: string | null
    total_paid: string
  } | null
  max_payment_range: { low: string; high: string } | null
  total_paid_range: { low: string; high: string } | null
  windows: number
  schedule: unknown[]
}

export interface LoanSimulation {
  tracks: TrackSimulation[]
  first_payment: string
  max_base_payment: string
  total_paid: string
  rate_as_of: string
  cpi_as_of: string
}

export type OptionSaved = OptionData & { result: LoanSimulation }

/** The examples a saved real offer removes from the check, and whether its recommendation, which
 * named one of them, is removed with them. */
export interface ExamplesRemoved {
  option_ids: string[]
  recommendation_removed: boolean
}

export interface OptionView {
  id: string
  source: OptionData['source']
  lender: string | null
  offer_date: string | null
  loan: OptionData['loan']
  figures: OptionFigures
  created_at: string
}

export interface RecommendationSummary {
  preferred_option_id: string
  alternative_option_id: string | null
  loan_amount: string
  /** Null when the recommendation was made without a ceiling. */
  payment_ceiling: string | null
  /** The recommendation was checked against the payment ceiling. */
  checked: boolean
  created_at: string
}

export interface RecommendationView extends RecommendationSummary {
  reasoning: string
}

/** An offer the person described whose loan type is still unclear, as the checks list shows it. */
export interface AwaitingSummary {
  id: string
  lender: string
  monthly_payment: string | null
}

export interface CheckSummary {
  id: string
  created_at: string
  loan: LoanRequest | null
  recommendation: RecommendationSummary | null
  /** Every option the recommendation names is an example nobody can take. */
  recommends_examples_only: boolean
  /** The recommendation's card shows more than one option, so it ranks them; one option alone
   * is evaluated, not recommended. False without a recommendation. */
  compares_options: boolean
  /** The term the person confirmed, in months; null until then. */
  term_months: number | null
  /** Closed by the person; the check is read-only until restored. */
  archived: boolean
  /** The person has sent the check a message; before that it shows only the opening card. */
  started: boolean
  /** The check's finances hold at least one figure. */
  has_finances: boolean
  /** Offers waiting on the lender's answer, oldest first. */
  awaiting_offers: AwaitingSummary[]
}

export interface CheckView {
  id: string
  created_at: string
  loan: LoanRequest | null
  term_months: number | null
  payment_ceiling: string | null
  ceiling_source: CeilingSource | null
  finances: Finances
  /** Oldest first. */
  options: OptionView[]
  recommendation: RecommendationView | null
  archived: boolean
}

export interface RecommendationPresented {
  loan_amount: string
  payment_ceiling: string | null
  ceiling_source: CeilingSource | null
  checked: boolean
  preferred: OptionData
  alternative: OptionData | null
  reasoning: string
}

/** The loan, finances or ceiling field the page asks for. */
export type QuestionField =
  | 'purpose'
  | 'amount'
  | 'own_capital'
  | 'net_fixed_income'
  | 'fixed_expenses'
  | 'payment_ceiling'

/**
 * How the term card's term was chosen: the shortest term whose first payment stays under an
 * assumed amount, or whose worst-case payment fits the check's ceiling, with fits false when even
 * the longest term does not; or a shorter term the recommendation suggests, at which its
 * preferred option still fits the ceiling (amount), with the term it shortens, the worst-case
 * payment there and what it saves in total; or the term the person typed.
 */
export type TermBasis =
  | { kind: 'first_payment_target' | 'ceiling'; amount: string; fits: boolean }
  | {
      kind: 'shorter'
      amount: string
      from_term_months: number
      worst_payment: string
      saving: string
    }
  | { kind: 'typed' }

/**
 * One term of the terms card, priced on the recommended option: the payment today, its highest at
 * today's rates, the highest the worst period in history would have raised it to (null for a
 * payment that never changes) and the total paid.
 */
export interface TermRow {
  term_months: number
  first_payment: string
  peak_payment: string
  worst_payment: string | null
  total_paid: string
}

/**
 * A field the page asks for, free text with optional choices, the offer to clone the check, which
 * the page words itself, the term to confirm with the first payment it gives, the recommended
 * option priced at its term and at the next terms shorter or longer, or a lender's offer
 * to fill in, with what the person already said about it. A stored
 * question of the first two kinds may carry no `offer_clone`: the log keeps each question as the
 * app version that asked it wrote it.
 */
export type Question =
  | { kind?: undefined; field: QuestionField; text: null; choices: null; offer_clone?: false }
  | { kind?: undefined; field: null; text: string; choices: string[] | null; offer_clone?: false }
  | { kind?: undefined; field: null; text: null; choices: null; offer_clone: true }
  | {
      kind: 'term'
      term_months: number
      first_payment: string
      /** Absent from a term card stored before the basis was sent; the card then states none. */
      basis?: TermBasis
    }
  | {
      kind: 'terms'
      direction: 'shorter' | 'longer'
      /** The recommended option's lender; null for an example. */
      lender: string | null
      source: OptionData['source']
      payment_ceiling: string | null
      /** The option's own term first, then the terms in the direction asked. */
      rows: TermRow[]
    }
  | {
      kind: 'offer'
      lender: string | null
      tracks: OfferTrackDraft[]
      max_term_months: number | null
    }
  /** The form that simulates a movement not yet simulated on the check's offers. */
  | { kind: 'scenario'; movement: ScenarioMovement }

/** A movement a scenario simulates: prime's yearly rise, or the CPI's. */
export type ScenarioMovement = 'prime' | 'cpi'

/**
 * A track of an offer as far as the person described it. `rate` is the annual percent of a fixed
 * track or the signed margin over prime of a prime track, as a decimal string; null when unsaid.
 */
export interface OfferTrackDraft {
  rate_kind: 'fixed' | 'prime'
  rate: string | null
  cpi_linked: boolean
}

/** Hands the source check's conversation over to its copy. */
export interface CheckCloned {
  clone_id: string
}

/** Ends the log of a check the person archived. */
export interface CheckArchived {
  archived_at: string
}

/** The two caps behind a ceiling derived from the finances; the ceiling is the lower of them. */
export interface CeilingBasis {
  income_percent: string
  ceiling_by_income_share: string
  disposable_percent: string
  ceiling_by_disposable_income: string
}

/** The check's finances after a save, what is still missing and the ceiling that follows. */
export interface FinancesUpdated {
  finances: Finances
  missing: string[]
  payment_ceiling: string | null
  ceiling_source: CeilingSource | null
  /** Set when this save derived the ceiling; absent from events stored before it was sent. */
  ceiling_basis?: CeilingBasis | null
}

/** How an offer's interest could be priced, in the order a card lists the readings. */
export type ReadingKind = 'prime_margin' | 'prime_total' | 'fixed_unlinked' | 'fixed_linked'

/** A word of the lender's that hints at the loan type. */
export type TypeWord = 'prime' | 'fixed' | 'linked'

/** One way to read an offer: the engine track it prices as, its first payment and the annual
 * percent charged today. `approximate` marks a rate derived from the payment alone. */
export interface Reading {
  kind: ReadingKind
  track: Track
  first_payment: string
  total_rate: string
  approximate: boolean
}

/** An offer whose loan type is unclear, with the readings the person can confirm one of. */
export interface AwaitingOffer {
  awaiting_id: string
  lender: string
  amount: string
  term_months: number
  monthly_payment: string | null
  /** The fixed rate that gives `monthly_payment`; null when no payment was given. */
  payment_rate: string | null
  type_words: TypeWord[]
  readings: Reading[]
  likely: ReadingKind | null
  /** Its quoted payment identified its one reading; only an offer quoted for less than the
   * check's loan awaits with an identified reading, for the lender's answer on the amount. */
  identified: boolean
  prime: string
  rate_as_of: string
}

/** An offer the agent priced from a reading it identified without asking. */
export interface OfferIdentified {
  option_id: string
  lender: string
  reading: Reading
  prime: string
  rate_as_of: string
  monthly_payment: string
  quoted_amount: string
  loan_amount: string
}

export interface OfferUnrecognized {
  lender: string | null
}

/** An awaiting offer became a saved offer, with the reading it was saved by, which its card may
 * not hold when a later detail identified the offer. */
export interface OfferSettled {
  awaiting_id: string
  kind: ReadingKind
  reading: Reading
}

/** An awaiting offer quoted for less than the check's loan left the check: its lender does not
 * lend the loan amount on the same terms. */
export interface OfferDropped {
  awaiting_id: string
  lender: string
  quoted_amount: string
  loan_amount: string
}

export type TurnStatus = 'running' | 'idle'

export const CHECK_EVENT_TYPES = [
  'message.user',
  'message.delta',
  'message.retracted',
  'message.assistant',
  'loan.set',
  'term.set',
  'ceiling.set',
  'finances.updated',
  'option.saved',
  'examples.removed',
  'recommendation.presented',
  'turn.status',
  'turn.failed',
  'question.asked',
  'chart.shown',
  'scenario.shown',
  'check.archived',
  'check.restored',
  'check.cloned',
  'offer.awaiting',
  'offer.identified',
  'offer.unrecognized',
  'offer.settled',
  'offer.dropped',
] as const

type EventTypeName = (typeof CHECK_EVENT_TYPES)[number]

interface Sequenced<Type extends EventTypeName, Data> {
  type: Type
  data: Data
  seq: number | null
  /** When the server stored the event, an ISO time; the demo's recording holds none. */
  at?: string
}

/** `message.delta` and `message.retracted` are the events without a sequence number; a delta's
 * text is cumulative. */
/** A market series to draw: the prime in annual percent, or the CPI's monthly change in percent;
 * values are decimal strings, oldest month first. */
export interface ChartShown {
  series: 'prime' | 'cpi'
  as_of: string
  points: { month: string; value: string }[]
}

/** Every saved option priced on a future the person named, beside its total in today's
 * calculation; the scenario holds both values, the engine's default filling the one not named. */
export interface ScenarioShown {
  /** Each movement as its yearly figure; a movement taken from the last years also names them. */
  scenario: {
    cpi_per_year: string
    prime_per_year: string
    cpi_like_last_years: number | null
    prime_like_last_years: number | null
  }
  /** The values the person named; the other kept the engine's default. */
  named: ('cpi_per_year' | 'prime_per_year' | 'cpi_like_last_years' | 'prime_like_last_years')[]
  rows: (Pick<OptionData, 'option_id' | 'source' | 'lender' | 'offer_date' | 'loan'> & {
    scenario: { first_payment: string; max_payment: string; total_paid: string }
    today: { max_payment: string; total_paid: string }
  })[]
}

export type CheckEvent =
  | Sequenced<'message.user', { text: string }>
  | { type: 'message.delta'; data: { message_id: string; text: string }; seq: null }
  /** Live only: a streamed reply the page drops, since the assistant rewrites it. */
  | { type: 'message.retracted'; data: { message_id: string }; seq: null }
  | Sequenced<'message.assistant', { message_id: string; text: string }>
  | Sequenced<'loan.set', LoanRequest>
  | Sequenced<'term.set', { term_months: number }>
  | Sequenced<'ceiling.set', { payment_ceiling: string; ceiling_source: CeilingSource }>
  | Sequenced<'finances.updated', FinancesUpdated>
  | Sequenced<'option.saved', OptionSaved>
  | Sequenced<'examples.removed', ExamplesRemoved>
  | Sequenced<'recommendation.presented', RecommendationPresented>
  | Sequenced<'turn.status', { status: TurnStatus }>
  | Sequenced<'turn.failed', { message: string }>
  | Sequenced<'question.asked', { question: Question; lead_in: string | null }>
  | Sequenced<'chart.shown', ChartShown>
  | Sequenced<'scenario.shown', ScenarioShown>
  | Sequenced<'check.archived', CheckArchived>
  | Sequenced<'check.cloned', CheckCloned>
  | Sequenced<'check.restored', Record<string, never>>
  | Sequenced<'offer.awaiting', AwaitingOffer>
  | Sequenced<'offer.identified', OfferIdentified>
  | Sequenced<'offer.unrecognized', OfferUnrecognized>
  | Sequenced<'offer.settled', OfferSettled>
  | Sequenced<'offer.dropped', OfferDropped>

type SameEventTypes = [CheckEvent['type']] extends [EventTypeName]
  ? [EventTypeName] extends [CheckEvent['type']]
    ? true
    : never
  : never
// Compile-time check that CHECK_EVENT_TYPES and CheckEvent name the same types.
export const EVENT_TYPES_MATCH_UNION: SameEventTypes = true
