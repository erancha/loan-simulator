import type {
  CheckEvent,
  CheckSummary,
  ProfileFields,
  ProfileView,
  Question,
  RecommendationPresented,
  User,
} from '../api/types.ts'
import { answerLine, INPUT_LABEL, questionLabel } from '../check/copy.ts'

/** Every event the server stores for a check; deltas are live only, so a recording has none. */
export type StoredEvent = Exclude<CheckEvent, { type: 'message.delta' }>

/** One check's stored events in seq order, as scripts/tools/export-demo-check.sh writes them. */
export interface Recording {
  events: StoredEvent[]
}

/** How the replay paces a recording: the pause before each event, how a reply is typed, and how
 * long what the person typed stays in its box before their message is sent. */
export interface Pace {
  pauseMs: number
  typingMs: number
  typedChars: number
  entryMs: number
}

/** What the person typed before sending a message, and the label of the box it went into. */
export interface Entry {
  box: string
  value: string
}

/** Shows an entry in its box; the returned call empties the box again. */
export type ShowEntry = (entry: Entry) => () => void

const DEMO_CHECK_ID = 'demo'
const DEMO_USER: User = { id: 'demo', email: 'demo@example.com', name: 'הדגמה' }
// A first visit's profile: every field unset, so missing lists all of them in the panel's order.
const PROFILE_KEYS: (keyof ProfileFields)[] = [
  'savings',
  'net_fixed_income',
  'variable_income',
  'variable_income_minimum',
  'fixed_expenses',
  'existing_loan_payments',
]
const EMPTY_PROFILE: ProfileView = {
  profile: Object.fromEntries(PROFILE_KEYS.map((key) => [key, null])) as unknown as ProfileFields,
  missing: PROFILE_KEYS,
}
// The checks list's created_at, which the list shows; the replay starts the check now.
const STARTED_AT = new Date().toISOString()

type Listener = (frame: MessageEvent<string>) => void

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

/** An example nobody can take is a published average; the list marks a check that names only
 * those. */
function examplesOnly({ preferred, alternative }: RecommendationPresented): boolean {
  return [preferred, alternative].every(
    (option) => option === null || option.source === 'published_average',
  )
}

/**
 * What the person typed for a message, or null for a tap (a skip or a choice), which types nothing.
 * An answer to a live question was typed into the question's own box, as its value alone: the
 * money box shows its own ₪. Any other message was typed into the chat's composer.
 */
function entryOf(text: string, live: Question | null): Entry | null {
  if (live === null) return { box: INPUT_LABEL, value: text }
  const label = questionLabel(live)
  const prefix = answerLine(label, '')
  if (!text.startsWith(prefix)) return null
  const value = text.slice(prefix.length)
  if (live.choices !== null && live.choices.includes(value)) return null
  const typed = live.field === null || live.field === 'purpose' ? value : value.replace(/ ₪$/, '')
  return { box: label, value: typed }
}

/**
 * The page's backend for the demo: one recorded check replayed on a timer, served through a fetch
 * and an EventSource that demo/main.tsx installs before the real app renders.
 *
 * - One timeline starts when the backend is created. A stream that connects later first gets the
 *   events already played, as the server's replay does, then the rest as they play.
 * - A recorded reply is stored whole, so the timeline types it out as cumulative deltas first.
 * - Before a message the person typed, showEntry puts the typed value in its box for a moment.
 * - The profile and the checks list answer what the events played so far imply.
 * - A message sent from the page is accepted and answered by nothing; a request the page is not
 *   known to make is refused, so a new call surfaces instead of hanging the demo.
 */
export function createDemoBackend(recording: Recording, pace: Pace, showEntry: ShowEntry) {
  const played: StoredEvent[] = []
  const listeners = new Set<(event: CheckEvent) => void>()
  const broadcast = (event: CheckEvent) => {
    for (const listener of listeners) listener(event)
  }

  async function play() {
    // The question a message from the person answers: the latest one asked since they last wrote.
    let live: Question | null = null
    for (const event of recording.events) {
      await wait(pace.pauseMs)
      if (event.type === 'question.asked') live = event.data.question
      if (event.type === 'message.user') {
        const entry = entryOf(event.data.text, live)
        live = null
        if (entry !== null) {
          const clear = showEntry(entry)
          await wait(pace.entryMs)
          clear()
        }
      }
      if (event.type === 'message.assistant') {
        const { message_id, text } = event.data
        for (let end = pace.typedChars; end < text.length; end += pace.typedChars) {
          const typed = text.slice(0, end)
          broadcast({ type: 'message.delta', data: { message_id, text: typed }, seq: null })
          await wait(pace.typingMs)
        }
      }
      played.push(event)
      broadcast(event)
    }
  }
  void play()

  const latest = <Type extends StoredEvent['type']>(type: Type) =>
    played.findLast((event): event is Extract<StoredEvent, { type: Type }> => event.type === type)

  function summary(): CheckSummary {
    const recommendation = latest('recommendation.presented')
    const goal = latest('goal.set')
    return {
      id: DEMO_CHECK_ID,
      created_at: STARTED_AT,
      goal: goal === undefined ? null : goal.data,
      recommendation:
        recommendation === undefined
          ? null
          : {
              preferred_option_id: recommendation.data.preferred.option_id,
              alternative_option_id:
                recommendation.data.alternative === null
                  ? null
                  : recommendation.data.alternative.option_id,
              loan_amount: recommendation.data.sizing.loan_amount,
              payment_ceiling: recommendation.data.bounds.payment_ceiling,
              created_at: STARTED_AT,
            },
      recommends_examples_only:
        recommendation !== undefined && examplesOnly(recommendation.data),
      profile_stale: false,
      archived: false,
      restorable: false,
    }
  }

  const profile = () => {
    const updated = latest('profile.updated')
    return updated === undefined ? EMPTY_PROFILE : updated.data
  }

  const routes: Record<string, () => Response> = {
    'GET /api/auth/me': () => json(DEMO_USER),
    'GET /api/checks': () => json([summary()]),
    'GET /api/profile': () => json(profile()),
    'PUT /api/profile': () => json(profile()),
    [`POST /api/checks/${DEMO_CHECK_ID}/messages`]: () => new Response(null, { status: 202 }),
  }

  async function fetch(path: string, init?: RequestInit): Promise<Response> {
    const key = `${init?.method ?? 'GET'} ${path}`
    const route = routes[key]
    if (route === undefined) throw new Error(`the demo serves no ${key}`)
    return route()
  }

  /** The check's event stream as the page's useCheckEvents hook reads it. */
  class DemoEventSource {
    static readonly CLOSED = 2
    readyState = 1
    onerror: (() => void) | null = null
    private readonly typed = new Map<string, Listener[]>()
    private readonly forward = (event: CheckEvent) => {
      const frame = new MessageEvent(event.type, {
        data: JSON.stringify(event.data),
        lastEventId: event.seq === null ? '' : String(event.seq),
      })
      for (const listener of this.typed.get(event.type) ?? []) listener(frame)
    }

    constructor(url: string) {
      if (url !== `/api/checks/${DEMO_CHECK_ID}/events`) {
        throw new Error(`the demo streams no ${url}`)
      }
      // The hook adds its listeners right after constructing the source, so the catch-up waits a
      // microtask for them, as a real stream's first frame arrives after its connection opens.
      queueMicrotask(() => {
        if (this.readyState === DemoEventSource.CLOSED) return
        for (const event of played) this.forward(event)
        listeners.add(this.forward)
      })
    }

    addEventListener(type: string, listener: Listener) {
      this.typed.set(type, [...(this.typed.get(type) ?? []), listener])
    }

    removeEventListener(type: string, listener: Listener) {
      this.typed.set(
        type,
        (this.typed.get(type) ?? []).filter((kept) => kept !== listener),
      )
    }

    close() {
      this.readyState = DemoEventSource.CLOSED
      listeners.delete(this.forward)
    }
  }

  return { fetch, EventSource: DemoEventSource }
}
