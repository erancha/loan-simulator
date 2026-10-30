/**
 * Folds a check's event stream into the page's state.
 *
 * The stream replays stored events and then continues live, and a reconnect replays again, so
 * stored events (with a seq) are applied once. `message.delta` has no seq and carries the whole
 * reply so far; its complete `message.assistant` may arrive later, or already have been applied.
 */
import type {
  ChartShown,
  CheckEvent,
  Goal,
  OptionSaved,
  Question,
  RecommendationPresented,
} from '../api/types.ts'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  complete: boolean
}

/** A question the model asked; the page renders it as an input until the user answers. */
export interface QuestionEntry {
  id: string
  role: 'question'
  question: Question
  leadIn: string | null
  answered: boolean
}

/** A market chart the model showed; it sits in the conversation where it was shown. */
export interface ChartEntry {
  id: string
  role: 'chart'
  chart: ChartShown
}

export type ChatEntry = ChatMessage | QuestionEntry | ChartEntry

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
  recommendation: RecommendationPresented | null
  /** Ids of options saved after the latest recommendation, excluding the ones it names. */
  optionsSinceRecommendation: string[]
  goal: Goal | null
  /** How many `profile.updated` events were applied; each tells the profile panel to refetch. */
  profileVersion: number
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
  recommendation: null,
  optionsSinceRecommendation: [],
  goal: null,
  profileVersion: 0,
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
): ChatEntry[] {
  const message: ChatMessage = { id, role: 'assistant', text, complete }
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
        messages: [...messages, { id, role: 'user', text: event.data.text, complete: true }],
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
    case 'message.assistant':
      return {
        ...state,
        messages: upsertAssistant(state.messages, event.data.message_id, event.data.text, true),
      }
    case 'profile.updated':
      return {
        ...state,
        profileVersion: state.profileVersion + 1,
      }
    case 'goal.set':
      return { ...state, goal: event.data }
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
          },
        ],
      }
    case 'turn.failed':
      return { ...state, failure: event.data.message }
  }
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
