/**
 * Folds a check's event stream into the page's state.
 *
 * The stream replays stored events and then continues live, and a reconnect replays again, so
 * stored events (with a seq) are applied once. `message.delta` has no seq and carries the whole
 * reply so far; its complete `message.assistant` may arrive later, or already have been applied.
 * `message.retracted`, also without a seq, removes a reply that is still being written.
 *
 * An offer the person described becomes an entry of the conversation: a readings card while its
 * loan type, or the loan amount of an offer quoted for less, waits on the lender, or the reply
 * for an offer identified or not recognized at all.
 */
import type {
  AwaitingOffer,
  ChartShown,
  CheckArchived,
  CeilingBasis,
  CeilingSource,
  CheckEvent,
  Finances,
  LoanRequest,
  OfferDropped,
  OfferIdentified,
  OptionSaved,
  Question,
  Reading,
  RecommendationPresented,
} from '../api/types.ts'
import { exceeds } from '../money.ts'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  complete: boolean
  /** When the message was stored, an ISO time; a reply still streaming has none yet. */
  at?: string
}

/** A question the model asked; the page renders it as an input until the user answers. */
export interface QuestionEntry {
  id: string
  role: 'question'
  question: Question
  leadIn: string | null
  answered: boolean
  /** When the question was stored, an ISO time. */
  at?: string
}

/** A market chart the model showed; it sits in the conversation where it was shown. */
export interface ChartEntry {
  id: string
  role: 'chart'
  chart: ChartShown
}

/** The note that closes an archived check's conversation. */
export interface ArchiveEntry {
  id: string
  role: 'archived'
  archive: CheckArchived
}

/** The note that hands a check over to its copy, where the variant goes on. */
export interface CloneEntry {
  id: string
  role: 'cloned'
  cloneId: string
}

/** An offer whose loan type waits on the lender's answer: the card of its readings. */
export interface ReadingsEntry {
  /** `r-${awaiting_id}`, so a later emit of the same offer finds its card. */
  id: string
  role: 'readings'
  offer: AwaitingOffer
  /** The reading the offer was saved by; null while it still waits. */
  settled: Reading | null
  /** The lender's no to the loan amount of an offer quoted for less; null unless it said no. */
  dropped: OfferDropped | null
  at?: string
}

/** An offer whose reading the agent identified and saved, with its short reply. */
export interface IdentifiedEntry {
  id: string
  role: 'identified'
  offer: OfferIdentified
  at?: string
}

/** An offer whose loan type the agent could not tell, with what to ask the lender. */
export interface UnrecognizedEntry {
  id: string
  role: 'unrecognized'
  lender: string | null
  at?: string
}

export type ChatEntry =
  | ChatMessage
  | QuestionEntry
  | ChartEntry
  | ArchiveEntry
  | CloneEntry
  | ReadingsEntry
  | IdentifiedEntry
  | UnrecognizedEntry

/** A user message or a reply; a question and a chart are entries of their own kinds. */
export function isMessage(entry: ChatEntry): entry is ChatMessage {
  return entry.role === 'user' || entry.role === 'assistant'
}

/** False only for a reply still streaming, which its turn's end may drop. */
export function isSettled(entry: ChatEntry): boolean {
  return !isMessage(entry) || entry.complete
}

export interface CheckState {
  /** In arrival order; a user message's id is `u-${seq}` and a question's is `q-${seq}`. */
  messages: ChatEntry[]
  /** By option id; the last `option.saved` wins and the first save fixes the position. */
  options: Map<string, OptionSaved>
  /** By awaiting id, in arrival order; an offer leaves once it is saved by a reading, or dropped
   * when its lender does not lend the check's loan amount. */
  awaiting: Map<string, AwaitingOffer>
  recommendation: RecommendationPresented | null
  /** Ids of options saved after the latest recommendation, excluding the ones it names. */
  optionsSinceRecommendation: string[]
  loan: LoanRequest | null
  /** The term the person confirmed, in months. */
  termMonths: number | null
  /** The payment ceiling the check holds, with where it came from and, when derived from the
   * finances, the caps it was derived from; null while it has none. */
  ceiling: { amount: string; source: CeilingSource; basis: CeilingBasis | null } | null
  finances: Finances
  turn: 'idle' | 'running'
  /** How many times a running turn has gone idle in this stream, replay included. */
  turnsEnded: number
  /** The last `turn.failed` message; cleared by the next `message.user`. */
  failure: string | null
  /** Highest stored seq applied. */
  lastSeq: number
}

export const initialState: CheckState = {
  messages: [],
  options: new Map(),
  awaiting: new Map(),
  recommendation: null,
  optionsSinceRecommendation: [],
  loan: null,
  termMonths: null,
  ceiling: null,
  finances: { net_fixed_income: null, fixed_expenses: null },
  turn: 'idle',
  turnsEnded: 0,
  failure: null,
  lastSeq: 0,
}

function upsertAssistant(
  messages: ChatEntry[],
  id: string,
  text: string,
  complete: boolean,
  at?: string,
): ChatEntry[] {
  const message: ChatMessage = { id, role: 'assistant', text, complete, at }
  return messages.some((m) => m.id === id)
    ? messages.map((m) => (m.id === id ? message : m))
    : [...messages, message]
}

function apply(state: CheckState, event: CheckEvent): CheckState {
  switch (event.type) {
    case 'message.user': {
      const id = `u-${event.seq}`
      const asked = state.messages.findLastIndex((m) => m.role === 'question')
      const messages = state.messages.map((m, i) =>
        i === asked && m.role === 'question' ? { ...m, answered: true } : m,
      )
      return {
        ...state,
        messages: [
          ...messages,
          { id, role: 'user', text: event.data.text, complete: true, at: event.at },
        ],
        failure: null,
      }
    }
    case 'message.delta': {
      const { message_id, text } = event.data
      const stored = state.messages.some(
        (m) => m.id === message_id && isMessage(m) && m.complete,
      )
      if (stored) return state
      return {
        ...state,
        messages: upsertAssistant(state.messages, message_id, text, false),
      }
    }
    case 'message.retracted':
      return {
        ...state,
        messages: state.messages.filter(
          (m) => !(m.id === event.data.message_id && isMessage(m) && !m.complete),
        ),
      }
    case 'message.assistant':
      return {
        ...state,
        messages: upsertAssistant(
          state.messages,
          event.data.message_id,
          event.data.text,
          true,
          event.at,
        ),
      }
    case 'loan.set':
      return { ...state, loan: event.data }
    case 'term.set':
      return { ...state, termMonths: event.data.term_months }
    case 'ceiling.set':
      return {
        ...state,
        ceiling: {
          amount: event.data.payment_ceiling,
          source: event.data.ceiling_source,
          basis: null,
        },
      }
    case 'finances.updated': {
      const { finances, payment_ceiling, ceiling_source, ceiling_basis } = event.data
      const basis = ceiling_basis === undefined ? null : ceiling_basis
      const ceiling =
        payment_ceiling === null || ceiling_source === null
          ? null
          : { amount: payment_ceiling, source: ceiling_source, basis }
      return { ...state, finances, ceiling }
    }
    case 'option.saved': {
      const id = event.data.option_id
      const named = [state.recommendation?.preferred, state.recommendation?.alternative]
      const isNew =
        !named.some((o) => o?.option_id === id) && !state.optionsSinceRecommendation.includes(id)
      return {
        ...state,
        options: new Map(state.options).set(id, event.data),
        optionsSinceRecommendation: isNew
          ? [...state.optionsSinceRecommendation, id]
          : state.optionsSinceRecommendation,
      }
    }
    case 'examples.removed': {
      const { option_ids: removed, recommendation_removed } = event.data
      const options = new Map(state.options)
      for (const id of removed) options.delete(id)
      return {
        ...state,
        options,
        recommendation: recommendation_removed ? null : state.recommendation,
        optionsSinceRecommendation: state.optionsSinceRecommendation.filter(
          (id) => !removed.includes(id),
        ),
      }
    }
    case 'recommendation.presented':
      return {
        ...state,
        recommendation: event.data,
        optionsSinceRecommendation: [],
      }
    case 'turn.status': {
      if (event.data.status === 'running') return { ...state, turn: 'running' }
      // A reply still incomplete when its turn ends was never stored, so a reload never shows it.
      const settled = {
        ...state,
        messages: state.messages.filter(isSettled),
      }
      return {
        ...settled,
        turn: 'idle',
        turnsEnded: state.turn === 'running' ? state.turnsEnded + 1 : state.turnsEnded,
      }
    }
    case 'chart.shown':
      return {
        ...state,
        messages: [...state.messages, { id: `c-${event.seq}`, role: 'chart', chart: event.data }],
      }
    case 'question.asked':
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: `q-${event.seq}`,
            role: 'question',
            question: event.data.question,
            leadIn: event.data.lead_in,
            answered: false,
            at: event.at,
          },
        ],
      }
    case 'turn.failed':
      return { ...state, failure: event.data.message }
    case 'check.archived':
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: `x-${event.seq}`, role: 'archived', archive: event.data },
        ],
      }
    case 'check.cloned':
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: `c-${event.seq}`, role: 'cloned', cloneId: event.data.clone_id },
        ],
      }
    case 'check.restored':
      return { ...state, messages: state.messages.filter((entry) => entry.role !== 'archived') }
    case 'offer.awaiting': {
      const offer = event.data
      const id = `r-${offer.awaiting_id}`
      const shown = state.messages.some((entry) => entry.id === id)
      const messages: ChatEntry[] = shown
        ? state.messages.map((entry) =>
            entry.id === id && entry.role === 'readings' ? { ...entry, offer } : entry,
          )
        : [
            ...state.messages,
            { id, role: 'readings', offer, settled: null, dropped: null, at: event.at },
          ]
      return {
        ...state,
        messages,
        awaiting: new Map(state.awaiting).set(offer.awaiting_id, offer),
      }
    }
    case 'offer.settled':
      return closeAwaiting(state, event.type, event.data.awaiting_id, {
        settled: event.data.reading,
      })
    case 'offer.dropped':
      return closeAwaiting(state, event.type, event.data.awaiting_id, { dropped: event.data })
    case 'offer.identified':
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: `i-${event.seq}`, role: 'identified', offer: event.data, at: event.at },
        ],
      }
    case 'offer.unrecognized':
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: `n-${event.seq}`, role: 'unrecognized', lender: event.data.lender, at: event.at },
        ],
      }
  }
}

/** An awaiting offer leaves the check, and its card shows how: settled or dropped. */
function closeAwaiting(
  state: CheckState,
  type: 'offer.settled' | 'offer.dropped',
  awaitingId: string,
  closed: Pick<ReadingsEntry, 'settled'> | Pick<ReadingsEntry, 'dropped'>,
): CheckState {
  const id = `r-${awaitingId}`
  if (!state.messages.some((entry) => entry.id === id)) {
    throw new Error(`${type} for ${awaitingId}, which no offer.awaiting showed`)
  }
  const awaiting = new Map(state.awaiting)
  awaiting.delete(awaitingId)
  return {
    ...state,
    messages: state.messages.map((entry) =>
      entry.id === id && entry.role === 'readings' ? { ...entry, ...closed } : entry,
    ),
    awaiting,
  }
}

/** The offer was quoted for less than the check's loan, so it awaits the lender's answer on
 * lending the loan amount on the same terms. */
export function quotedBelowLoan(offer: AwaitingOffer, loanAmount: string): boolean {
  return exceeds(loanAmount, offer.amount)
}

/** An archived check takes no more messages. */
export function isArchived(state: Pick<CheckState, 'messages'>): boolean {
  return state.messages.some((entry) => entry.role === 'archived')
}

/** The check holds an option, example or offer, or an offer waiting on the lender's answer. */
export function holdsOption(state: CheckState): boolean {
  return state.options.size > 0 || state.awaiting.size > 0
}

// Last, unanswered and idle means no person's message follows the question: the backend stores
// the asking message's text before question.asked and ends the turn right after it.
export function liveQuestion(state: CheckState): QuestionEntry | null {
  const last = state.messages.at(-1)
  return last?.role === 'question' && !last.answered && state.turn === 'idle' ? last : null
}

export function reduce(state: CheckState, event: CheckEvent): CheckState {
  if (event.seq !== null && event.seq <= state.lastSeq) return state
  const next = apply(state, event)
  return event.seq === null ? next : { ...next, lastSeq: event.seq }
}
