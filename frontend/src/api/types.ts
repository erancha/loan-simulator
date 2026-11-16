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
}

export interface OptionData {
  option_id: string
  /** The engine's Loan arguments as the agent sent them, not a normalised record. */
  loan: { tracks: Track[] }
  source: 'published_average' | 'offer'
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

export interface CheckSummary {
  id: string
  created_at: string
  loan: LoanRequest | null
  recommendation: RecommendationSummary | null
  /** Every option the recommendation names is an example nobody can take. */
  recommends_examples_only: boolean
  /** The term the person confirmed, in months; null until then. */
  term_months: number | null
  /** Closed by the person; the check is read-only until restored. */
  archived: boolean
  /** The person has sent the check a message; before that it holds only the opening line. */
  started: boolean
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
 * A field the page asks for, free text with optional choices, the offer to clone the check, which
 * the page words itself, the term to confirm with the first payment it gives, or a lender's offer
 * to fill in, with what the person already said about it. A stored
 * question of the first two kinds may carry no `offer_clone`: the log keeps each question as the
 * app version that asked it wrote it.
 */
export type Question =
  | { kind?: undefined; field: QuestionField; text: null; choices: null; offer_clone?: false }
  | { kind?: undefined; field: null; text: string; choices: string[] | null; offer_clone?: false }
  | { kind?: undefined; field: null; text: null; choices: null; offer_clone: true }
  | { kind: 'term'; term_months: number; first_payment: string }
  | {
      kind: 'offer'
      lender: string | null
      tracks: OfferTrackDraft[]
      max_term_months: number | null
    }

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

/** The check's finances after a save, what is still missing and the ceiling that follows. */
export interface FinancesUpdated {
  finances: Finances
  missing: string[]
  payment_ceiling: string | null
  ceiling_source: CeilingSource | null
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
  'recommendation.presented',
  'turn.status',
  'turn.failed',
  'question.asked',
  'chart.shown',
  'check.archived',
  'check.restored',
  'check.cloned',
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
  | Sequenced<'recommendation.presented', RecommendationPresented>
  | Sequenced<'turn.status', { status: TurnStatus }>
  | Sequenced<'turn.failed', { message: string }>
  | Sequenced<'question.asked', { question: Question; lead_in: string | null }>
  | Sequenced<'chart.shown', ChartShown>
  | Sequenced<'check.archived', CheckArchived>
  | Sequenced<'check.cloned', CheckCloned>
  | Sequenced<'check.restored', Record<string, never>>

type SameEventTypes = [CheckEvent['type']] extends [EventTypeName]
  ? [EventTypeName] extends [CheckEvent['type']]
    ? true
    : never
  : never
// Compile-time check that CHECK_EVENT_TYPES and CheckEvent name the same types.
export const EVENT_TYPES_MATCH_UNION: SameEventTypes = true
