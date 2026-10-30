/** The agent API's JSON shapes. Every money field is a decimal string, never a number. */

export interface User {
  id: string
  email: string | null
  name: string | null
}

export interface Goal {
  purpose: string
  price: string
}

export interface ProfileFields {
  savings: string | null
  net_fixed_income: string | null
  variable_income: string | null
  variable_income_minimum: string | null
  fixed_expenses: string | null
  existing_loan_payments: string | null
}

export interface ProfileView {
  profile: ProfileFields
  missing: string[]
}

export type ProfileUpdate = Partial<ProfileFields>

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
  payment_ceiling: string
  created_at: string
}

export interface RecommendationView extends RecommendationSummary {
  reasoning: string
  min_cushion: string
  cushion_kept: string
}

export interface CheckSummary {
  id: string
  created_at: string
  goal: Goal | null
  recommendation: RecommendationSummary | null
  /** Every option the recommendation names is an example nobody can take. */
  recommends_examples_only: boolean
  profile_stale: boolean
}

export interface CheckView
  extends Omit<CheckSummary, 'recommendation' | 'recommends_examples_only'> {
  options: OptionView[]
  recommendation: RecommendationView | null
}

export interface RecommendationPresented {
  bounds: {
    payment_ceiling: string
    min_cushion: string
    counted_income: string
    reasons: string[]
  }
  sizing: {
    loan_amount: string
    savings_used: string
    cushion_kept: string
    spare_savings: string
  }
  preferred: OptionData
  alternative: OptionData | null
  reasoning: string
}

export type QuestionField =
  | 'purpose'
  | 'price'
  | 'savings'
  | 'net_fixed_income'
  | 'variable_income'
  | 'variable_income_minimum'
  | 'fixed_expenses'
  | 'existing_loan_payments'

/** Either a profile or goal field the page asks for, or free text with optional choices. */
export type Question =
  | { field: QuestionField; text: null; choices: null }
  | { field: null; text: string; choices: string[] | null }

export type TurnStatus = 'running' | 'idle'

export const CHECK_EVENT_TYPES = [
  'message.user',
  'message.delta',
  'message.assistant',
  'profile.updated',
  'goal.set',
  'option.saved',
  'recommendation.presented',
  'turn.status',
  'turn.failed',
  'question.asked',
  'chart.shown',
] as const

type EventTypeName = (typeof CHECK_EVENT_TYPES)[number]

interface Sequenced<Type extends EventTypeName, Data> {
  type: Type
  data: Data
  seq: number | null
}

/** `message.delta` is the only event without a sequence number; its text is cumulative. */
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
  | Sequenced<'message.assistant', { message_id: string; text: string }>
  | Sequenced<'profile.updated', ProfileView>
  | Sequenced<'goal.set', Goal>
  | Sequenced<'option.saved', OptionSaved>
  | Sequenced<'recommendation.presented', RecommendationPresented>
  | Sequenced<'turn.status', { status: TurnStatus }>
  | Sequenced<'turn.failed', { message: string }>
  | Sequenced<'question.asked', { question: Question; lead_in: string | null }>
  | Sequenced<'chart.shown', ChartShown>

type SameEventTypes = [CheckEvent['type']] extends [EventTypeName]
  ? [EventTypeName] extends [CheckEvent['type']]
    ? true
    : never
  : never
// Compile-time check that CHECK_EVENT_TYPES and CheckEvent name the same types.
export const EVENT_TYPES_MATCH_UNION: SameEventTypes = true
